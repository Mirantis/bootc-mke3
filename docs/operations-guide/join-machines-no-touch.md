# Join machines with no-touch join

Add new worker machines to an existing `bootc-mke3` MKE 3 cluster with the
first-boot join that is built into the image. This process does not use SSH
to the new machine. It does not run the Ansible installer again.

**This is the standard process to join machines after the initial
install.** Production clusters usually disable SSH on cluster machines after
the install. Then the Ansible installer cannot add more machines. No-touch
join is designed for this situation.

The standard operating procedure uses batches:

1. Issue a worker join token on a manager.
2. Join a **batch** of machines with that token.
3. **Rotate the token immediately after the batch joins.** Rotation
   invalidates the issued token, so a leaked credential is no longer a risk.
   Machines that already joined are not affected.

For a description of how the mechanism works, see the
[no-touch join description](no-touch-join.md).

## Requirements

1. A running MKE 3 / Docker Swarm cluster with at least one manager that you
   can reach.
2. New machines that are provisioned from a `bootc-mke3` image. All current
   images ship with `swarm-join.service` enabled.
3. A network path from each new machine to a manager, as given in the [port
   requirements](#port-requirements) below. The join itself needs only the
   join-minimum row.
4. Access to a manager node to issue a join token.

### Port requirements

| Scenario | Ports |
|---|---|
| Join minimum | `2377/tcp`, `7946/tcp+udp`, `4789/udp` |
| Full post-join operation | `mke_worker_internal`: `179/tcp`, `4789/udp`, `7946/tcp+udp`, `9091/tcp`, `9100/tcp`, `10250/tcp`, `12376/tcp`. `mke_worker_self`: `6444/tcp`, `9099/tcp`, `10248/tcp`, `12378/tcp`, `12389/tcp` |

Both service definitions are visible with `firewall-cmd --get-services` on
any manager. If you open only the join-minimum set, the join handshake works.
But a later `ucp upgrade checks` run, or any full-cluster health probe,
fails and names the blocked ports. Open the full set at the AWS
security-group (or equivalent network) layer from the start. Do not widen the
set after the fact.

## Procedure

### 1. Collect the join credential (on any manager)

```
docker swarm join-token -q worker                    # -> SWMTKN-1-...
docker info --format '{{.Swarm.NodeAddr}}'           # -> manager advertise IP
```

Use the **worker** token. The manager endpoint is `<NodeAddr>:2377`.

### 2. Inject the credential into each new machine

Select the delivery path that matches how the machine is provisioned. The
credential payload is the same in all cases:

```
SWARM_TOKEN=SWMTKN-1-<your-worker-token>
SWARM_MANAGER=10.0.0.10:2377
```

**Kickstart is the primary path.** Production `bootc-mke3` machines are
provisioned from the ISO (bare metal), where kickstart is the standard
customization mechanism. Cloud-init applies **only to the cloud-platform
builds** (AMI/QCOW2). It does not exist on bare-metal ISO installs. AMI
builds are mainly for internal testing. QCOW2 is publicly announced and
downloadable. systemd credentials work on both, where the infrastructure can
deliver them.

The payload may need to carry more than the credential. Whoever provisions the
machine applies firewall rules, kernel module preloading, and hardening. The
join does not apply them. Read [What else should the provisioning payload
include?](#what-else-should-the-provisioning-payload-include) before you
copy an example below.

#### Bare metal (kickstart — the standard path; file shredded after join)

Append the credential file to the kickstart `%post`. Add the optional items
from [What else should the provisioning payload
include?](#what-else-should-the-provisioning-payload-include) too. This
example adds the firewalld services in the correct zones:

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
%end
```

The credential file is written to disk. It is shredded automatically after a
confirmed join.

#### Cloud (cloud-init user-data — cloud builds only; tmpfs delivery)

This applies only to the cloud-platform builds (AMI/QCOW2). AMI is mainly for
internal testing. QCOW2 is publicly announced and downloadable. The
credential file is written to tmpfs and never touches the disk. Cloud-init
separately caches the raw user-data under `/var/lib/cloud`. This cache is
scrubbed automatically after a successful join.

The cloud-config below does the same firewalld steps as the kickstart path
above. Pass it as instance user-data (for example `aws ec2 run-instances
--user-data file://...`):

```yaml
#cloud-config
write_files:
  - path: /run/mke3/swarm-join.env
    permissions: '0600'
    content: |
      SWARM_TOKEN=SWMTKN-1-<your-worker-token>
      SWARM_MANAGER=10.0.0.10:2377
runcmd:
  - firewall-cmd --zone=trusted --add-interface=lo --permanent
  - firewall-cmd --zone=public --add-service=mke_worker_internal --permanent
  - firewall-cmd --zone=trusted --add-service=mke_worker_self --permanent
  - firewall-cmd --reload
```

On AWS, harden the instance metadata service so that containers cannot reach
the token in user-data. Require IMDSv2 with a hop limit of 1:

```
--metadata-options HttpTokens=required,HttpPutResponseHopLimit=1
```

#### systemd credentials (most secure)

Deliver `swarm.token` and `swarm.manager` as systemd system credentials
(SMBIOS OEM strings, kernel cmdline, or an encrypted/TPM-bound credstore).
The unit already imports both, so no change is necessary on the node. This
source has precedence over both file paths.

### 3. Boot the machines

No other action is necessary. On first boot, after Docker is healthy, each
machine joins the swarm as a worker. MKE onboards it automatically.

### 4. Rotate the join token (after the batch has joined)

After every machine in the batch appears in `docker node ls`, rotate the
worker token on a manager:

```
docker swarm join-token --rotate worker
```

Rotation invalidates the token that was used for the batch. A leaked copy
(user-data snapshot, kickstart archive, or a token read from a console
screen) can no longer join the cluster. Machines that already joined are not
affected. The next batch starts again at step 1 with the new token.

## Expected Results

On a manager, `kubectl get nodes` is the authoritative check. Make sure that
the new machine appears and is `Ready`:

```
kubectl get nodes
```

`docker node ls` and the MKE UI (Shared Resources → Nodes) also list the
node. Use both only as secondary information. A confirmed anomaly (from
`ucp-controller`) can cause a `Ready`, schedulable worker to show `Down` in
`docker node ls` indefinitely. The message is "Node not yet found in classic
node inventory". This does not mean that the node is broken. Do not block a
batch, and do not start troubleshooting, on `docker node ls` or the MKE UI
alone. Check `kubectl get nodes` first.

> [!NOTE]
> `Ready` in `kubectl get nodes` does not mean that the local firewall of the
> node is configured. `mke-images.service` is ordered `Before=getty.target`
> (`WantedBy=getty.target`). This places it before `multi-user.target` in
> the boot sequence. `cloud-final.service` runs the cloud-init `runcmd`
> (that is, the firewalld steps above on cloud builds). It depends on
> `multi-user.target`.
>
> `mke-images.service` loads the baked-in product and controller image tars.
> This can take several minutes. On a freshly no-touch-joined node, the
> kubelet/swarm-join path can report `Ready` long before
> `cloud-final.service` runs and opens the firewall.
>
> The gap closes by itself, because `cloud-final.service` always runs
> eventually. But some automation joins a node and immediately probes it or
> runs commands on it over the cluster ports. The join handshake is
> outbound-only, so it does not need these ports. We recommend that this
> automation waits for `systemctl is-active mke-images` on that node first.
> Or the automation can tolerate closed ports for a few minutes after `Ready`.

If you have access to the joined machine, do these checks:

```
systemctl status swarm-join.service               # active (exited); unit now disabled
cat /var/lib/mke3/joined                          # UTC join timestamp
docker info --format '{{.Swarm.LocalNodeState}}'  # active
```

No token residue remains. `/etc/mke3/swarm-join.env` is shredded (bare
metal). `/run/mke3` is RAM-only (cloud). The cached copies of user-data from
cloud-init are scrubbed. The token value does not appear in any log.

## Troubleshooting

First, examine `journalctl -u swarm-join` on the machine. A failure logs a
`swarm-join: ERROR` prefix (never the token value).

| Symptom | Likely cause | Remediation |
|---|---|---|
| `failed to join swarm after 5 attempts` | Manager unreachable: wrong `SWARM_MANAGER`, or TCP `2377` blocked | Run `nc -vz <manager> 2377` from the machine. Correct the address or the firewall. Re-trigger the join |
| Join rejected on every attempt | The token was rotated on the swarm, or a manager token was supplied | Issue a new token with `docker swarm join-token -q worker`. Inject it again. Re-trigger the join |
| `SWARM_TOKEN and SWARM_MANAGER must both be set` | Malformed or partial env file | Correct the injected file. Both keys are necessary, and `SWARM_MANAGER` needs `:2377` |
| `Docker not ready after 300s` | `docker.service` failed to start | Diagnose with `systemctl status docker` on the machine. Correct the fault. Re-trigger the join |
| Unit exits 0, no join, no sentinel | No credential was injected (wrong path, user-data not applied) | Make sure that the file exists at `/run/mke3/swarm-join.env` or `/etc/mke3/swarm-join.env`. Inject it and reboot |
| Unit does nothing on boot | Sentinel `/var/lib/mke3/joined` is present from a prior join | This is expected. To force a re-join, remove the sentinel and enable the unit again |

### Re-triggering a join

The unit disables itself only on success, so after a failure it runs again on
the next boot. To run it again immediately, after you correct the credential
or the network:

```
sudo rm -f /var/lib/mke3/joined          # only if a sentinel was written
sudo systemctl enable --now swarm-join.service
sudo systemctl status swarm-join.service
```

## F.A.Q

### Can this join managers?

No. The mechanism joins **workers only**. After the initial install, add a
new manager in two steps. First, no-touch-join the machine as a worker. Then
promote it with `docker node promote` from an MKE client bundle. This needs
no SSH to the machine. See [Promote or demote a
machine](promote-demote-machine.md). Promote the machine only after it
reports `Ready`. Note the fault-tolerance window that the runbook describes
while the manager count is even. The Ansible installer joins managers at
install time only.

Check the provisioning payload of the machine. If it opened only the worker
firewall services (as the examples in this guide do), open the manager
firewall services before you promote it. A promoted machine needs the services that
the installer gives a manager: `mke_manager_external` and
`mke_manager_internal` in the `public` zone, and `mke_manager_self` in
`trusted` (`ansible/tasks/mke-open-ports-tasks.yml`). Otherwise, the machine
is `Ready` as a worker but blocks manager traffic after promotion. Add the
services in the same way as the worker services. Or include them in the
payload from the start for any machine that you plan to promote.

### Does this replace the Ansible worker join?

After the initial install, yes. The Ansible installer joins the workers that
it provisions at install time. But SSH is usually disabled on cluster
machines afterward, so the installer cannot add machines later. No-touch
join is the standard process for all additions after the initial install.

### Is the join secure against a rogue manager?

The `SWMTKN-1-<ca-hash>-<secret>` token contains the cluster CA hash. The
joining node therefore validates the TLS certificate of the manager as part
of the join.

### What else should the provisioning payload include?

The no-touch join adds the machine to the cluster and changes nothing else
on it. Whatever provisions the machine applies anything else that the
machine needs. This is done in the same kickstart `%post` or cloud-init
configuration that carries the join credential.

**Hardening.** For a cluster that is expected to be hardened, these two
actions also belong in the payload. Mask sshd and revoke the sudo of the
provisioning user. See
[Does the joined machine end up hardened (sshd masked, sudo
revoked)?](#does-the-joined-machine-end-up-hardened-sshd-masked-sudo-revoked).

**Firewall rules.** The firewalld of a fresh machine is active by default.
It ships only the `ssh`, `cockpit` and `dhcpv6-client` services, and none of
the cluster ports. The join succeeds because it is outbound-only. But the
machine cannot receive inbound gossip and overlay traffic until the firewall
is opened. There are two options:

- Open the cluster ports. Use the same zones and services that a worker gets
  from `tasks/mke-open-ports-tasks.yml` of the installer. The `public` zone is
  for `mke_worker_internal`. The `trusted` zone plus a trusted loopback
  interface is for `mke_worker_self`. `firewall-cmd --permanent` followed by
  `firewall-cmd --reload` takes effect immediately. No reboot is necessary.
- Disable firewalld, where a perimeter firewall already restricts the
  equivalent ports. This is the no-touch equivalent of the
  `disable_firewalld` variable of the installer. The value of that variable
  for the cluster has no effect here, because the installer never runs on
  this machine. Use this command in a kickstart `%post` or a cloud-init
  `runcmd`:

  ```
  systemctl disable --now firewalld
  ```

  Nothing pulls firewalld in with `Wants=`, so `disable` is enough. Use
  `mask` only to prevent a later `systemctl start`.

Open the [full post-join port set](#port-requirements), and not only the
join-minimum rows. Then you do not need a second pass after the machine
carries workloads.

**Kernel modules.** The image preloads the modules that MKE and Calico need.
To add a module that a workload needs, write it as a drop-in, with one module
name on each line. In a kickstart `%post`:

```
cat > /etc/modules-load.d/site-extra.conf <<'EOF'
nfs
nfsv4
EOF
```

In cloud-init, use the same commands in `runcmd` or a `write_files` entry:

```yaml
write_files:
  - path: /etc/modules-load.d/site-extra.conf
    permissions: '0644'
    content: |
      nfs
      nfsv4
```

`systemd-modules-load.service` loads the drop-in on every boot, before any
`kernel.modules_disabled` setting applies.

**The time when it takes effect is different for each path.** A kickstart
`%post` writes into the installed tree, so the module is loaded on the
*first* boot of the machine. Cloud-init is different. `write_files` and
`runcmd` both run after `systemd-modules-load.service` finishes.
Creating the drop-in does not run it again. On the cloud path, the module
therefore loads from the *second* boot onward.

To load it on the first boot of a cloud machine, do one of these two things.
Use `modprobe <module>` together with the `write_files` entry. This is
possible where `kernel.modules_disabled` is `0`, as on current images. Or
reboot after the join. Under the lockdown, `modprobe` fails and a reboot is
the only option.

**systemd service changes.** Changes to units are also part of the payload.
This includes enabling, disabling or masking a unit (firewalld and sshd
above, and anything else that the role of the machine needs). The reason is
the same: the join changes no unit except `swarm-join.service`, which disables
itself on success. A kickstart `%post` can use `services --enabled=` or
`--disabled=` in the main command section, or `systemctl` against the
installed tree. Cloud-init `runcmd` runs `systemctl` against the live
system, where `--now` prevents a reboot. You must mask (not disable) any unit
that another unit pulls in with `Wants=`. For the sshd case, see the
hardening entry below.

### Does the joined machine end up hardened (sshd masked, sudo revoked)?

Only if the provisioning configuration does it. Whoever provisions the
machine is responsible for the hardening. The hardening belongs in the same
kickstart `%post` or cloud-init configuration that carries the join
credential. The no-touch mechanism joins the machine to the cluster and changes
nothing else. `swarm-join.service` and `/usr/libexec/swarm-join` need neither
sshd nor sudo. You can therefore apply the hardening before, during or after
the join, and it does not affect the join.

For a cluster that is expected to be hardened, add both of the following to the
provisioning configuration.

Revoke the sudo of the provisioning user. Substitute the user that your
configuration creates:

```
gpasswd -d <provisioning-user> wheel 2>/dev/null || true
gpasswd -d <provisioning-user> sudo 2>/dev/null || true
sed -i '/^<provisioning-user>[[:space:]]/d' /etc/sudoers
find /etc/sudoers.d/ -maxdepth 1 -type f \
  -exec sed -i '/^<provisioning-user>[[:space:]]/d' {} \;
```

Disable SSH. Mask the unit (do not disable it), and use `--now` so that no
reboot is necessary:

```
systemctl mask --now sshd
```

Notes:

- **Mask, not disable.** On cloud images, `cloud-init.service` has
  `Wants=sshd.service`. This activates a disabled unit on every boot. Only a
  masked unit stays inactive across reboots. See
  [Harden MKE 3 Kubernetes](harden-mke3-kubernetes.md).
- **A reboot is not necessary.** In a kickstart `%post`, the mask and the
  sudo removal are written into the installed tree. The first boot of the
  machine is then already hardened. In cloud-init `runcmd`,
  `systemctl mask --now sshd` stops the running daemon and installs the mask
  in the same call.
- **Run both in one elevated context. Revoke sudo first.** If you mask sshd
  first, an existing SSH session drops before the revocation can run. It is
  safe to revoke sudo first, because the shell is already root and the loss
  of `wheel` does not affect it.
- If you mask sshd before the join is confirmed, no shell access is left to
  diagnose a failed join. A one-shot `runcmd` test for
  `/var/lib/mke3/joined` is not a usable gate. `cloud-final.service` can run
  while the join is still retrying. It then finds no sentinel, skips the
  hardening, and never runs again. To keep a diagnosis window, do one of
  these two things. Install a unit that is ordered after `swarm-join.service`,
  waits for the sentinel, and then hardens. Or harden as a separate step after
  the machine reports `Ready`. In both cases, decide what happens to a machine
  whose join never succeeds.
- To recover, use the console or a [node debug shell](node-debug-shell.md).
  Run `systemctl unmask sshd` and then `systemctl enable --now sshd`. If you
  only unmask, the daemon stays stopped.

If a configuration also hardens the kernel with
`kernel.modules_disabled = 1`, the module subsystem is locked after the
sysctl applies. Any module that is loaded on demand after that point fails.
Current images ship `0` in `/usr/lib/sysctl.d/20-secure-kernel-params.conf`.
Do not assume either setting. Verify the live value with
`sysctl kernel.modules_disabled`. Under the lockdown, the image still
preloads the modules that MKE and Calico need. The lockdown therefore
affects only a workload that needs a different module. Preload that module
as described above.

