# No-touch cluster join

`bootc-mke3` images ship a first-boot mechanism that lets a freshly provisioned
machine join an existing Docker Swarm / MKE 3 cluster **as a worker** with no
SSH access and no manual `docker swarm join` — "no-touch". The only per-node
input is a worker join token and a manager endpoint, injected by whatever
provisions the machine (kickstart for bare-metal ISO installs — the standard
production path; cloud-init user-data on cloud-platform builds only (AMI,
primarily used for internal testing; QCOW2, publicly announced/downloadable);
or systemd credentials).

No-touch join is the **standard process for adding machines to a cluster after
the initial install**: production clusters typically disable SSH on cluster
machines once installed, so the Ansible installer cannot join machines later.

This page describes how the mechanism works. For step-by-step instructions on
joining machines, see the [no-touch join runbook](join-machines-no-touch.md).

## Components baked into the image

| Component | Path | Role |
|---|---|---|
| systemd unit | `/usr/lib/systemd/system/swarm-join.service` | Oneshot, enabled by default, ordered after `docker.service` |
| Resolver script | `/usr/libexec/swarm-join` | Finds the credential, performs the join, cleans up |
| Sentinel | `/var/lib/mke3/joined` | Written after a successful join; makes the mechanism idempotent |

## First-boot flow

On boot, `swarm-join.service` starts once Docker is up and runs the resolver,
which:

1. **Exits immediately** if the sentinel `/var/lib/mke3/joined` exists
   (already joined; safe across reboots).
2. **Resolves the credential** from the first available source, in priority
   order:
   1. **systemd credentials** — `swarm.token` + `swarm.manager` imported via
      `ImportCredential=` (SMBIOS, kernel cmdline, or encrypted/TPM-bound
      credstore). Most secure option.
   2. **tmpfs file** — `/run/mke3/swarm-join.env`. Intended for cloud-init
      (cloud-platform builds only): the file lives in RAM and never persists
      across reboot.
   3. **persistent file** — `/etc/mke3/swarm-join.env`. Intended for
      kickstart-provisioned bare metal; shredded after a confirmed join.
3. **Waits for Docker** to become healthy (up to 300 s by default).
4. **Joins the swarm**: `docker swarm join --token <token> <SWARM_MANAGER>`
   (the value already carries the `host:2377` join address), retrying up to 5
   times at 10 s intervals.
5. **Cleans up** on success: shreds the persistent `/etc` file (if that was the
   source), scrubs any copy of the credential that cloud-init cached under
   `/var/lib/cloud` (cloud-init persists raw user-data regardless of which
   delivery path was used), writes the sentinel, and disables
   `swarm-join.service`.

If **no credential is found**, the unit exits 0 as a no-op and stays enabled —
injecting a token later plus a reboot still joins the machine. If the join
**fails**, the unit fails visibly (`systemctl status swarm-join`), stays
enabled, and retries on the next boot.

Once the machine is in the swarm, MKE onboards it automatically — the new
worker appears in the MKE UI and `docker node ls` without further action.
Note: `docker node ls` has been observed to show a joined worker as `Down`
indefinitely ("Node not yet found in classic node inventory", sourced from
`ucp-controller`) even though the node is `Ready` and schedulable in
`kubectl get nodes` — treat `kubectl get nodes` as the authoritative check
and don't block on `docker node ls` catching up.

## Credential format

Both file sources use the same shell env-file format:

```
SWARM_TOKEN=SWMTKN-1-...
SWARM_MANAGER=<manager-host-or-ip>:2377
```

`SWARM_MANAGER` must be the full `host:port` join address (port `2377`).
The token must be a **worker** token (`docker swarm join-token -q worker` on a
manager). The full `SWMTKN-1-<ca-hash>-<secret>` token embeds the manager CA
hash, so the join validates the manager's TLS certificate — no extra pinning is
needed.

## Security properties

- The token value is **never logged**; `journalctl -u swarm-join` shows only
  the manager endpoint and the source label.
- The tmpfs path never touches disk. The persistent path is shredded after a
  confirmed join. Cloud-init's own user-data cache copies are scrubbed too.
- The systemd-credential path supports encrypted and TPM-bound delivery.
- The mechanism joins **workers only** — there is no manager-promotion path.
- **Token lifecycle (SOP):** issue a worker token per **batch** of machines,
  and rotate it on a manager (`docker swarm join-token --rotate worker`) as
  soon as the batch has joined. Rotation invalidates the issued token, so a
  leaked copy is no longer a risk; already-joined machines are unaffected.
- **Host hardening is not part of the join.** The mechanism changes no host
  state beyond joining the swarm, so a machine that joins this way is not
  hardened the way the Ansible installer hardens the machines it installs
  (sshd masked, the connecting user's sudo revoked). Masking sshd and
  revoking the provisioning user's sudo belong to whoever provisions the
  machine — see [Does the joined machine end up hardened (sshd masked, sudo
  revoked)?](join-machines-no-touch.md#does-the-joined-machine-end-up-hardened-sshd-masked-sudo-revoked)
  in the runbook.

## Tunables

Environment overrides honored by the resolver (set via a systemd drop-in):

| Variable | Default | Meaning |
|---|---|---|
| `SWARM_READY_TIMEOUT` | `300` | Seconds to wait for Docker to become healthy |
| `SWARM_JOIN_RETRIES` | `5` | Join attempts before the unit fails |
| `SWARM_JOIN_INTERVAL` | `10` | Seconds between join attempts |
