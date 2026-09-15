# Image architecture

This document describes what a `bootc-mke3` image ships, which parts of it
are fixed at build time, and where the supported customisation points are.
It is aimed at operators deciding what they can rely on being present on a
node and what they must add themselves at provision time.

## Filesystem contract

`bootc-mke3` is a bootc/ostree image, which gives the filesystem three
distinct behaviours:

- **`/usr` is immutable and replaced wholesale on upgrade.** Nothing written
  there at runtime survives; everything the image vendor ships lives there.
- **`/etc` is three-way merged on upgrade.** Operator edits survive, but a
  file that the image also ships and the operator has modified stops
  tracking the image's own updates to that file.
- **`/var` is machine-local** and persists across upgrades.

The consequence for configuration: vendor-supplied config ships under
`/usr/lib/...`, and operator overrides belong in the corresponding
`/etc/...` drop-in directory. Every customisation point below follows that
split.

## Kernel modules

This is the most consequential part of the image for cluster networking,
because module loading is permanently disabled part-way through boot.

### The allowlist and the lockdown latch

| Path | Role |
|---|---|
| `/usr/lib/modules-load.d/mke-modules.conf` | Allowlist of modules loaded at boot by `systemd-modules-load.service` |
| `/usr/lib/dracut/dracut.conf.d/mke-modules.conf` | `add_drivers+=` mirror of the same list, embedding those `.ko` files in the initramfs (`dracut --regenerate-all --force` runs at image build) |
| `/usr/lib/sysctl.d/20-secure-kernel-params.conf` | Sets `kernel.modules_disabled = 1`, alongside `kernel.dmesg_restrict` and `kernel.yama.ptrace_scope` |

What makes the preload effective is unit ordering:
`systemd-modules-load.service` is ordered `Before=systemd-sysctl.service`,
so every module in any `modules-load.d` directory is loaded before
`kernel.modules_disabled = 1` is applied.

> [!IMPORTANT]
> `kernel.modules_disabled = 1` is a **one-way latch**. Once set, no module
> can be loaded for the remainder of the boot session — not by `modprobe`,
> not by a kernel autoload triggered on demand, and not by any sysctl
> change, `MachineConfigChange` included. The only way to gain a module is
> to have it listed before the latch applies, which in practice means
> changing the module list and rebooting.

The practical symptom of a missing module is a workload failing to program
the dataplane rather than an obvious module error — for example
kube-proxy logging `iptables-restore: Couldn't load match 'statistic'`, or
`mount.nfs` reporting `No such device` on a node that has `nfs-utils`
installed and the `.ko` files on disk.

### Inspecting the effective list

The allowlist file is the authoritative record and its contents change
between releases, so it is not reproduced here. Read it off any booted
node:

```sh
cat /usr/lib/modules-load.d/mke-modules.conf
lsmod
```

The list covers, in broad terms: container and overlay filesystems
(`overlay`, `loop`, `fuse`, `vfat`), L2/bridge networking, the nftables
stack used by the `iptables-nft` backend, netfilter/conntrack, the
iptables/xtables and ipset extensions MKE and Calico program, IPv6
netfilter, IPVS and SCTP match support, Calico's encapsulation devices
(IPIP, VXLAN, WireGuard), traffic-control modules for Calico bandwidth QoS,
TUN/TAP, kernel TLS, and device mapper. Hardware and root-filesystem
modules are deliberately omitted — dracut and udev load those from detected
hardware.

> [!NOTE]
> The list is extended as products need it — Calico Enterprise's
> requirements, including `ipip` for its default encapsulation mode, were
> added on 2026-09-08 and are present in every image built after that
> date. On an older image, a module the list does not yet carry has to be
> added through the extension point below, which costs a reboot. Check the
> file on the node against what your workloads need rather than assuming a
> given release's contents.

### Adding modules

The supported extension point is a drop-in in `/etc/modules-load.d/`, one
module name per line — for example `/etc/modules-load.d/site-extra.conf`
containing:

```
nfs
nfsv4
```

Files there are read by the same `systemd-modules-load.service`, so they
benefit from the same `Before=systemd-sysctl.service` ordering. When the
drop-in takes effect depends on when it is created:

| Created | Effective |
|---|---|
| At provision time (kickstart `%post`, cloud-init) | **First boot**, no extra reboot — the installed system has not booted yet |
| On an already-running node | **After one reboot** — the latch is already set on the current boot |

Because a module is only loadable if its `.ko` is reachable, this works for
modules present in the image but unloaded; it cannot add a module the image
does not ship.

For provision-time recipes see
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations),
and for the cloud-init equivalent and a worked example of the
reboot-gating problem see
[Join machines with no-touch join](../operations-guide/join-machines-no-touch.md).
Across an existing cluster, have `machine-config-controller` maintain the
drop-in and drive the reboot as a separate resource rather than editing
nodes by hand — see
[Machine configuration changes](../operations-guide/machine-config-operations.md)
and the worked NFS example in
[Collect support bundles](../operations-guide/collect-support-bundles.md).

## NetworkManager

NetworkManager is installed and enabled. The image ships
`/usr/lib/NetworkManager/conf.d/10-calico-unmanaged.conf`, which marks
Calico's interfaces unmanaged so NetworkManager does not compete with
Calico for their configuration:

```
[keyfile]
unmanaged-devices=interface-name:cali*;interface-name:tunl*;interface-name:vxlan.calico;interface-name:vxlan-v6.calico;interface-name:wireguard.cali;interface-name:wg-v6.cali
```

The list covers the veth pairs (`cali*`) and the tunnel devices of every
encapsulation mode: IPIP (`tunl*`), VXLAN (`vxlan.calico`,
`vxlan-v6.calico`) and WireGuard (`wireguard.cali`, `wg-v6.cali`).

To override it, drop a file of the same name into
`/etc/NetworkManager/conf.d/`, which wins over the `/usr/lib` copy.

> [!WARNING]
> `/usr/lib` snippets are parsed **first**, and `unmanaged-devices` is
> replaced rather than merged. Any snippet of your own in `/etc` or `/run`
> that sets `unmanaged-devices` discards the list above — restate the Calico
> interfaces in it, or NetworkManager resumes managing them.

## Baked services

| Unit | Purpose |
|---|---|
| `mke-images.service` | On first boot, loads the MKE image tarball from `/usr/share/mke/` and every controller image tarball from `/usr/share/mke-controllers/images/` into Docker |
| `swarm-join.service` (with `/usr/libexec/swarm-join`) | No-touch worker join, gated on the `/var/lib/mke3/joined` sentinel — see [no-touch join](../operations-guide/no-touch-join.md) |
| `cri-dockerd-mke.service` / `cri-dockerd-mke.socket` | MKE's CRI shim for the Docker engine |

Only `mke-images.service` and `swarm-join.service` are enabled at image
build time (`systemctl enable mke-images swarm-join.service`). The
`cri-dockerd-mke` units ship as definitions and are not enabled in the
image.

The image also ships:

- firewalld service definitions in `/usr/lib/firewalld/services/`
  (`mke_manager_external`, `mke_manager_internal`, `mke_manager_self`,
  `mke_worker_internal`, `mke_worker_self`). They are definitions only —
  nothing binds them to a zone until the Ansible installer's
  `tasks/mke-open-ports-tasks.yml` or your own provisioning payload does.
- sshd crypto hardening at
  `/etc/ssh/sshd_config.d/10-crypto-hardening.conf`. This one lives in
  `/etc`, not `/usr`, because sshd only `Include`s drop-ins from `/etc`.

Any of these units can be disabled at provision time; see
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations).

## Controller artifacts

Controller images, manifests and pinned versions ship under
`/usr/share/mke-controllers/` and are what the post-install step deploys
from. They are described in
[Post-install controllers](install-controllers.md#in-image-sources-are-the-source-of-truth)
and not duplicated here.
