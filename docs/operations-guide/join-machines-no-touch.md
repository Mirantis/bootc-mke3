# Join machines with no-touch join

Add new worker machines to an existing `bootc-mke3` MKE 3 cluster using the
image's built-in first-boot join — no SSH to the new machine and no re-run of
the Ansible installer.

**This is the standard process for joining machines after the initial
install.** Production clusters typically disable SSH on cluster machines once
installed, which makes the Ansible installer unusable for later additions —
no-touch join is designed for exactly that situation.

The standard operating procedure is batch-oriented:

1. Issue a worker join token on a manager.
2. Join a **batch** of machines with that token.
3. **Rotate the token immediately after the batch has joined** — rotation
   invalidates the issued token, so a leaked credential is no longer a risk.
   Already-joined machines are unaffected.

For how the mechanism works internally, see the
[no-touch join description](no-touch-join.md).

## Requirements

1. A running MKE 3 / Docker Swarm cluster with at least one reachable manager.
2. New machines provisioned from a `bootc-mke3` image (all current images ship
   `swarm-join.service` enabled).
3. Network path from each new machine to a manager per the [port
   requirements](#port-requirements) below — the join itself only needs the
   join-minimum row.
4. Access to a manager node to issue a join token.

### Port requirements

| Scenario | Ports |
|---|---|
| Join minimum | `2377/tcp`, `7946/tcp+udp`, `4789/udp` |
| Full post-join operation | `mke_worker_internal`: `179/tcp`, `4789/udp`, `7946/tcp+udp`, `9091/tcp`, `9100/tcp`, `10250/tcp`, `12376/tcp`; `mke_worker_self`: `6444/tcp`, `9099/tcp`, `10248/tcp`, `12378/tcp`, `12389/tcp` |

Both service definitions are visible via `firewall-cmd --get-services` on any
manager. Opening only the join-minimum set is enough for the join handshake
itself, but a later `ucp upgrade checks` run — or any full-cluster health
probe — will fail naming blocked ports once it reaches past the
join-minimum set. Provision the full set at the AWS security-group (or
equivalent network) layer from the start rather than widening it after the
fact.

## Procedure

### 1. Collect the join credential (on any manager)

```
docker swarm join-token -q worker                    # -> SWMTKN-1-...
docker info --format '{{.Swarm.NodeAddr}}'           # -> manager advertise IP
```

Use the **worker** token. The manager endpoint is `<NodeAddr>:2377`.

### 2. Inject the credential into each new machine

Pick the delivery path that matches how the machine is provisioned. The
credential payload is identical in all cases:

```
SWARM_TOKEN=SWMTKN-1-<your-worker-token>
SWARM_MANAGER=10.0.0.10:2377
```

**Kickstart is the primary path**: production `bootc-mke3` machines are
provisioned from the ISO (bare metal), where kickstart is the standard
customization mechanism. Cloud-init applies **only to the cloud-platform
builds** (AMI/QCOW2) — it does not exist on bare-metal ISO installs. AMI
builds are primarily used for internal testing; QCOW2 is publicly
announced/downloadable. systemd credentials work on either, where the
infrastructure can deliver them.

Node-local gaps must be handled in the same provisioning payload, whichever
delivery path you use. The firewall is one on every image; kernel module
preloading is another on older images (see the F.A.Q):

- **Firewall.** A fresh machine's own firewalld (active by default) ships
  only the `ssh`, `cockpit`, and `dhcpv6-client` services — none of the
  cluster ports. The swarm join itself still succeeds (it's outbound-only),
  but the node is then unreachable for inbound gossip/overlay traffic until
  the firewall is opened. This is unrelated to the cluster's
  `disable_firewalld` Ansible variable (default `false` — Ansible-managed
  nodes keep firewalld on and get per-service rules from
  `tasks/mke-open-ports-tasks.yml`): a no-touch-joined worker is never
  touched by the Ansible installer at all, so that variable's value
  elsewhere is irrelevant here — the node keeps the OS image's raw
  firewalld defaults until the provisioning payload configures it directly.
  Use the same zones/services `mke-open-ports-tasks.yml` applies to a
  worker (`public` zone for `mke_worker_internal`, `trusted` zone plus a
  trusted loopback interface for `mke_worker_self`), so the node ends up
  firewall-equivalent to one Ansible actually installed. The
  `firewall-cmd --permanent` + `--reload` pair takes effect immediately; no
  reboot is needed.

#### Bare metal (kickstart — the standard path; file shredded after join)

Append to the kickstart `%post`: the credential file, the firewalld
services (correct zones), the `xt_statistic` preload and the
sentinel-gated reboot unit (see [Do the examples need the `xt_statistic`
preload and the reboot unit?](#do-the-examples-need-the-xt_statistic-preload-and-the-reboot-unit)):

```
%post --erroronfail
install -d -m 0700 /etc/mke3
cat > /etc/mke3/swarm-join.env <<'EOF'
SWARM_TOKEN=SWMTKN-1-<your-worker-token>
SWARM_MANAGER=10.0.0.10:2377
EOF
chmod 600 /etc/mke3/swarm-join.env

firewall-cmd --zone=trusted --add-interface=lo --permanent
firewall-cmd --zone=public --add-service=mke_worker_internal --permanent
firewall-cmd --zone=trusted --add-service=mke_worker_self --permanent
firewall-cmd --reload

echo xt_statistic > /etc/modules-load.d/xt_statistic.conf

cat > /etc/systemd/system/mke3-postjoin-reboot.service <<'EOF'
[Unit]
Description=Reboot once to activate xt_statistic after no-touch join
After=swarm-join.service
ConditionPathExists=!/var/lib/mke3/postjoin-reboot-done

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for i in $(seq 1 60); do [ -f /var/lib/mke3/joined ] && break; sleep 5; done; [ -f /var/lib/mke3/joined ] || exit 0; touch /var/lib/mke3/postjoin-reboot-done; lsmod | grep -q xt_statistic && exit 0; systemctl reboot'
EOF
systemctl enable --now mke3-postjoin-reboot.service
%end
```

The credential file is written to disk but shredded automatically after a
confirmed join.

#### Cloud (cloud-init user-data — cloud builds only; tmpfs delivery)

Applies only to the cloud-platform builds (AMI/QCOW2) — AMI primarily used
for internal testing, QCOW2 publicly announced/downloadable. The credential
file itself is written to tmpfs and never touches disk. Note that cloud-init independently caches the raw user-data
under `/var/lib/cloud`; that cache is scrubbed automatically after a
successful join.

The same firewalld and `xt_statistic` handling as the kickstart path above,
expressed as cloud-config — pass as instance user-data (e.g. `aws ec2
run-instances --user-data file://...`):

```yaml
#cloud-config
write_files:
  - path: /run/mke3/swarm-join.env
    permissions: '0600'
    content: |
      SWARM_TOKEN=SWMTKN-1-<your-worker-token>
      SWARM_MANAGER=10.0.0.10:2377
  - path: /etc/systemd/system/mke3-postjoin-reboot.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Reboot once to activate xt_statistic after no-touch join
      After=swarm-join.service
      ConditionPathExists=!/var/lib/mke3/postjoin-reboot-done

      [Service]
      Type=oneshot
      ExecStart=/bin/sh -c 'for i in $(seq 1 60); do [ -f /var/lib/mke3/joined ] && break; sleep 5; done; [ -f /var/lib/mke3/joined ] || exit 0; touch /var/lib/mke3/postjoin-reboot-done; lsmod | grep -q xt_statistic && exit 0; systemctl reboot'
runcmd:
  - firewall-cmd --zone=trusted --add-interface=lo --permanent
  - firewall-cmd --zone=public --add-service=mke_worker_internal --permanent
  - firewall-cmd --zone=trusted --add-service=mke_worker_self --permanent
  - firewall-cmd --reload
  - echo xt_statistic > /etc/modules-load.d/xt_statistic.conf
  - systemctl enable --now mke3-postjoin-reboot.service
```

On AWS, harden the instance metadata service so the token in user-data is not
reachable from containers — require IMDSv2 with a hop limit of 1:

```
--metadata-options HttpTokens=required,HttpPutResponseHopLimit=1
```

#### systemd credentials (most secure)

Deliver `swarm.token` and `swarm.manager` as systemd system credentials
(SMBIOS OEM strings, kernel cmdline, or an encrypted/TPM-bound credstore). The
unit already imports both; no node-side change is needed. This source takes
precedence over both file paths.

### 3. Boot the machines

Nothing else to do. On first boot, after Docker is healthy, each machine joins
the swarm as a worker and MKE onboards it automatically.

### 4. Rotate the join token (after the batch has joined)

Once every machine in the batch appears in `docker node ls`, rotate the worker
token on a manager:

```
docker swarm join-token --rotate worker
```

Rotation invalidates the token used for the batch: even if a copy leaked
(user-data snapshot, kickstart archive, shoulder-surfed console), it can no
longer be used to join the cluster. Machines that already joined are
unaffected. The next batch starts again at step 1 with the fresh token.

## Expected Results

On a manager, `kubectl get nodes` is the authoritative check — confirm the
new machine appears and is `Ready`:

```
kubectl get nodes
```

`docker node ls` and the MKE UI (Shared Resources → Nodes) also list the
node, but treat both as secondary/informational only. A confirmed anomaly
(sourced from `ucp-controller`) can leave a fully `Ready`, schedulable
worker showing `Down` in `docker node ls` indefinitely, with the message
"Node not yet found in classic node inventory" — this does not mean the
node is broken. Don't block a batch, or start troubleshooting, on
`docker node ls`/the MKE UI alone; cross-check `kubectl get nodes` first.

> [!NOTE]
> `Ready` in `kubectl get nodes` does not mean the node's local firewall is
> configured yet. `mke-images.service` is ordered `Before=getty.target`
> (`WantedBy=getty.target`), which places it ahead of `multi-user.target` in
> the boot sequence — and `cloud-final.service` (the unit that runs
> cloud-init's `runcmd`, i.e. the firewalld/`xt_statistic` steps above on
> cloud builds) depends on `multi-user.target`. `mke-images.service` loading
> the baked-in product/controller image tars can take several minutes, so on
> a freshly no-touch-joined node the kubelet/swarm-join path can report
> `Ready` well before `cloud-final.service` has run and opened the firewall.
> The gap self-heals — `cloud-final.service` always runs eventually — but
> automation that joins a node and immediately probes/execs against it over
> the cluster ports (rather than waiting on the join handshake alone, which
> is outbound-only) should wait for `systemctl is-active mke-images` on that
> node first, or tolerate closed ports for a few minutes after `Ready`.

On the joined machine (if you have access):

```
systemctl status swarm-join.service               # active (exited); unit now disabled
cat /var/lib/mke3/joined                          # UTC join timestamp
docker info --format '{{.Swarm.LocalNodeState}}'  # active
```

No token residue remains: `/etc/mke3/swarm-join.env` is shredded (bare metal),
`/run/mke3` is RAM-only (cloud), and cloud-init's cached user-data copies are
scrubbed. The token value appears in no log.

## Troubleshooting

Inspect `journalctl -u swarm-join` on the machine first — failures log a
`swarm-join: ERROR` prefix (never the token value).

| Symptom | Likely cause | Remediation |
|---|---|---|
| `failed to join swarm after 5 attempts` | Manager unreachable: wrong `SWARM_MANAGER`, or TCP `2377` blocked | Check `nc -vz <manager> 2377` from the machine; fix address/firewall; re-trigger |
| Join rejected on every attempt | Token was rotated on the swarm, or a manager token was supplied | Issue a fresh `docker swarm join-token -q worker`; re-inject; re-trigger |
| `SWARM_TOKEN and SWARM_MANAGER must both be set` | Malformed or partial env file | Fix the injected file; both keys are required, `SWARM_MANAGER` needs `:2377` |
| `Docker not ready after 300s` | `docker.service` failed to start | Diagnose `systemctl status docker` on the machine; fix; re-trigger |
| Unit exits 0, no join, no sentinel | No credential was injected (typo'd path, user-data not applied) | Confirm the file exists at `/run/mke3/swarm-join.env` or `/etc/mke3/swarm-join.env`; inject and reboot |
| Unit no-ops on boot | Sentinel `/var/lib/mke3/joined` present from a prior join | Expected. To force a re-join, remove the sentinel and re-enable the unit |

### Re-triggering a join

The unit disables itself only on success, so after a failure it runs again on
the next boot. To re-run immediately after fixing the credential or network:

```
sudo rm -f /var/lib/mke3/joined          # only if a sentinel was written
sudo systemctl enable --now swarm-join.service
sudo systemctl status swarm-join.service
```

## F.A.Q

### Can this join managers?

No. The no-touch mechanism joins **workers only**. Managers are added via the
Ansible installer.

### Does this replace the Ansible worker join?

After the initial install — yes. The Ansible installer joins the workers it
provisions at install time, but SSH is typically disabled on cluster machines
afterwards, so the installer cannot add machines later. No-touch join is the
standard process for all post-install additions.

### Is the join secure against a rogue manager?

The `SWMTKN-1-<ca-hash>-<secret>` token embeds the cluster CA hash, so the
joining node validates the manager's TLS certificate as part of the join.

### Does the joined machine end up hardened (sshd masked, sudo revoked)?

Only if the provisioning configuration does it. Hardening a machine is the
responsibility of whoever provisions it, and belongs in the same kickstart
`%post` or cloud-init configuration that carries the join credential. The
no-touch mechanism joins the machine to the cluster and changes nothing else:
`swarm-join.service` and `/usr/libexec/swarm-join` need neither sshd nor sudo,
so hardening can be applied before, during or after the join without affecting
it.

For a cluster that is expected to be hardened, add to the provisioning
configuration, substituting the user your configuration creates:

```
gpasswd -d <provisioning-user> wheel 2>/dev/null || true
sed -i '/^<provisioning-user>[[:space:]]/d' /etc/sudoers
find /etc/sudoers.d/ -maxdepth 1 -type f \
  -exec sed -i '/^<provisioning-user>[[:space:]]/d' {} \;
systemctl mask --now sshd
```

Notes:

- **Mask, not disable.** On cloud images `cloud-init.service` carries
  `Wants=sshd.service`, which activates a disabled unit on every boot; only a
  masked unit stays inactive across reboots. See
  [Harden MKE 3 Kubernetes](harden-mke3-kubernetes.md).
- **No reboot is required.** In a kickstart `%post` the mask and the sudo
  removal are written into the installed tree, so the machine's first boot is
  already hardened. In cloud-init `runcmd`, `systemctl mask --now sshd` stops
  the running daemon and installs the mask in the same call.
- **Revoke sudo before masking sshd** when both run over an existing SSH
  session, and run them in a single elevated context — revoking sudo first
  removes the escalation the mask needs.
- Masking sshd before the join is confirmed leaves no shell access for
  diagnosing a failed join. To keep a diagnosis window, gate the hardening on
  `/var/lib/mke3/joined` existing, or apply it as a separate step once the
  machine reports `Ready`.
- Recovery, from the console or a
  [node debug shell](node-debug-shell.md): `systemctl unmask sshd`.

### Do the examples need the `xt_statistic` preload and the reboot unit?

Not on an image built from current `bootc-mirantis` `main`. The examples
keep both because they cost nothing there and cover older images.

Baked-in host hardening sets `kernel.modules_disabled=1`, which blocks
loading the `xt_statistic` kernel module on any node whose kube-proxy starts
*after* that lockdown sysctl has applied — which used to be every node
except whichever one won the boot-time race during the initial cluster
stand-up. On a current image `xt_statistic` is preloaded via
`dracut-mke-modules.conf`/`mke-modules.conf` and is present on **first
boot**, before the lockdown sysctl applies, on every node including
no-touch-joined workers — confirmed with zero `calico-node` restarts across
managers, Ansible-joined workers and no-touch-joined workers on the same
image.

On an **older** image the symptom is calico-node's `install-cni` init
container in `CrashLoopBackOff`, with kube-proxy logging `iptables-restore:
Couldn't load match 'statistic'`. The fix is to preload the module via
`/etc/modules-load.d/xt_statistic.conf` (content: the single line
`xt_statistic`). `systemd-modules-load.service` is ordered
`Before=systemd-sysctl.service`, so a module listed there loads before the
lockdown sysctl applies — but only on the *next* boot, so an already-running
no-touch-joined worker needs a self-triggered reboot. The reboot unit in the
examples is gated on the join sentinel (`/var/lib/mke3/joined`, see
[no-touch join](no-touch-join.md)) so it cannot race the join itself.

The examples check for the module before rebooting, so on a current image
the reboot is skipped entirely. The check is necessary: on an image where
the module is already preloaded, unconditionally rebooting every joined
worker restarts `calico-node` for no reason and produces a transient
`docker node ls` "Down" reading right after each join. It self-resolves, but
it is disruptive and misleading. Keep the check even with a fleet on current
images — it guards against an older image joining the mix.

### Does loading any other kernel module need the same treatment?

Yes. `kernel.modules_disabled=1` blocks every late `modprobe`, not just
`xt_statistic`. A module a workload needs must be listed in
`/etc/modules-load.d/` by the provisioning payload and be loaded before the
lockdown sysctl applies, which means it is in force from the next boot
onward, not from the moment the file is written.
