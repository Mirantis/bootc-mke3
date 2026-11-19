# No-touch cluster join

`bootc-mke3` images ship a first-boot mechanism. With it, a freshly
provisioned machine joins an existing Docker Swarm / MKE 3 cluster **as a
worker**. It needs no SSH access and no manual `docker swarm join`
("no-touch"). The only input for each node is a worker join token and a
manager endpoint. Whatever provisions the machine injects them.

The sources are:

- Kickstart for bare-metal ISO installs (the standard production path).
- Cloud-init user-data on cloud-platform builds only. AMI is mainly for
  internal testing. QCOW2 is publicly announced and downloadable.
- systemd credentials.

No-touch join is the **standard process to add machines to a cluster after
the initial install**. Production clusters usually disable SSH on cluster
machines after the install, so the Ansible installer cannot join machines
later.

This page describes how the mechanism works. For step-by-step instructions to
join machines, see the [no-touch join runbook](join-machines-no-touch.md).

## Components baked into the image

| Component | Path | Role |
|---|---|---|
| systemd unit | `/usr/lib/systemd/system/swarm-join.service` | Oneshot, enabled by default, ordered after `docker.service` |
| Resolver script | `/usr/libexec/swarm-join` | Finds the credential, does the join, and cleans up |
| Sentinel | `/var/lib/mke3/joined` | Written after a successful join. Makes the mechanism idempotent |

## First-boot flow

On boot, `swarm-join.service` starts when Docker is up and runs the resolver.
The resolver does these steps:

1. **Exits immediately** if the sentinel `/var/lib/mke3/joined` exists (the
   machine already joined). This is safe across reboots.
2. **Resolves the credential** from the first available source, in priority
   order:
   1. **systemd credentials**: `swarm.token` and `swarm.manager`, imported
      with `ImportCredential=` (SMBIOS, kernel cmdline, or encrypted/TPM-bound
      credstore). This is the most secure option.
   2. **tmpfs file**: `/run/mke3/swarm-join.env`. It is for cloud-init
      (cloud-platform builds only). The file lives in RAM and does
      not persist across reboot.
   3. **persistent file**: `/etc/mke3/swarm-join.env`. It is for
      kickstart-provisioned bare metal. The resolver shreds it after the
      join succeeds.
3. **Waits for Docker** to become healthy (up to 300 s by default).
4. **Joins the swarm** with `docker swarm join --token <token>
   <SWARM_MANAGER>` (the value already contains the `host:2377` join
   address). It retries up to 5 times at 10 s intervals.
5. **Cleans up** on success. It shreds the persistent `/etc` file (if that
   was the source). It scrubs any copy of the credential that cloud-init
   cached under `/var/lib/cloud` (cloud-init persists raw user-data
   regardless of the delivery path). It writes the sentinel and disables
   `swarm-join.service`.

If the resolver finds **no credential**, the unit exits 0, does nothing, and
stays enabled. If you inject a token later and reboot, the machine still
joins. If
the join **fails**, the unit fails visibly (`systemctl status swarm-join`),
stays enabled, and retries on the next boot.

After the machine is in the swarm, MKE onboards it automatically. The new
worker appears in the MKE UI and in `docker node ls` without further action.
Note: `docker node ls` can show a joined worker as `Down` indefinitely
("Node not yet found in classic node inventory", from `ucp-controller`). This
happens even though the node is `Ready` and schedulable in
`kubectl get nodes`. Use `kubectl get nodes` as the authoritative check. Do
not wait for `docker node ls` to catch up.

## Credential format

Both file sources use the same shell env-file format:

```
SWARM_TOKEN=SWMTKN-1-...
SWARM_MANAGER=<manager-host-or-ip>:2377
```

`SWARM_MANAGER` must be the full `host:port` join address (port `2377`).
The token must be a **worker** token (`docker swarm join-token -q worker` on
a manager). The full `SWMTKN-1-<ca-hash>-<secret>` token contains the
manager CA hash. The join therefore checks the TLS certificate of the
manager, and no extra pinning is necessary.

## Security properties

- The token value is **never logged**. `journalctl -u swarm-join` shows only
  the manager endpoint and the source label.
- The tmpfs path never touches the disk. The resolver shreds the persistent
  path after the join succeeds. It also scrubs the cloud-init user-data
  cache copies.
- The systemd-credential path supports encrypted and TPM-bound delivery.
- The mechanism joins **workers only**. There is no manager-promotion path.
- **Token lifecycle (SOP):** Issue a worker token for each **batch** of
  machines. Rotate it on a manager (`docker swarm join-token --rotate
  worker`) as soon as the batch joins. Rotation invalidates the issued
  token, so a leaked copy is no longer a risk. Machines that already joined
  are not affected.
- **Host hardening is not part of the join.** The mechanism changes no host
  state except the swarm join. A machine that joins this way is therefore not
  hardened in the way that the Ansible installer hardens the machines that it
  installs. The installer masks sshd and revokes the sudo of the connecting
  user. Whoever provisions the machine is responsible for masking sshd and
  revoking the sudo of the provisioning user. See [Does the joined machine end up hardened (sshd
  masked, sudo
  revoked)?](join-machines-no-touch.md#does-the-joined-machine-end-up-hardened-sshd-masked-sudo-revoked)
  in the runbook.

## Tunables

The resolver honors these environment overrides (set them with a systemd
drop-in):

| Variable | Default | Meaning |
|---|---|---|
| `SWARM_READY_TIMEOUT` | `300` | Seconds to wait for Docker to become healthy |
| `SWARM_JOIN_RETRIES` | `5` | Join attempts before the unit fails |
| `SWARM_JOIN_INTERVAL` | `10` | Seconds between join attempts |
