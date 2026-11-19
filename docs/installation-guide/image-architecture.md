# Image architecture

This document describes what a `bootc-mke3` image contains, which parts of
it the build fixes, and where the supported customisation points
are. It is for operators who must know what is always present on a node
and what they must add at provision time.

## Filesystem contract

`bootc-mke3` is a bootc/ostree image. The filesystem has three different
behaviours:

- **`/usr` is immutable. The upgrade replaces it completely.** Data that
  a process writes there at runtime does not survive. The image vendor puts
  all vendor files there.
- **The upgrade does a three-way merge of `/etc`.** Operator edits survive. If
  the image also contains a file and the operator changed it, that file
  does not get the image updates to that file.
- **`/var` is machine-local** and persists across upgrades.

For configuration, vendor-supplied config is in `/usr/lib/...`. Put
operator overrides in the corresponding `/etc/...` drop-in directory. Each
customisation point below follows this split.

## Kernel modules

This part of the image is important for cluster networking, because the
module set that is available to a node is mostly fixed at boot.

### The allowlist and the lockdown latch

| Path | Role |
|---|---|
| `/usr/lib/modules-load.d/mke-modules.conf` | Allowlist of modules that `systemd-modules-load.service` loads at boot |
| `/usr/lib/dracut/dracut.conf.d/mke-modules.conf` | `add_drivers+=` mirror of the same list, which puts those `.ko` files in the initramfs (`dracut --regenerate-all --force` runs at image build) |
| `/usr/lib/sysctl.d/20-secure-kernel-params.conf` | Sets `kernel.modules_disabled`, together with `kernel.dmesg_restrict` and `kernel.yama.ptrace_scope` |

The unit order makes the preload effective.
`systemd-modules-load.service` runs `Before=systemd-sysctl.service`.
Therefore the system loads every module in any `modules-load.d` directory
before it applies `kernel.modules_disabled`.

> [!IMPORTANT]
> **Current images have `kernel.modules_disabled = 0`**, so modules load
> on demand after boot. The value was `1` on images from builds before
> `bootc-mirantis` commit `4a31416` (2026-09-28). Read the live value with
> `sysctl kernel.modules_disabled` before you rely on either behaviour.
>
> Where the value is `1`, it is a **one-way latch**. The kernel can load no module
> for the remainder of the boot session. `modprobe` cannot load a module,
> an on-demand kernel autoload cannot load a module, and a
> sysctl change cannot load a module. A `MachineConfigChange` also cannot
> load a module. The only way to get a module is to list it before the latch
> applies. In practice, this means that you change the module list and reboot.

When a module is missing, the practical symptom is a workload that cannot
program the dataplane. It is not an obvious module error. For example,
kube-proxy logs `iptables-restore: Couldn't load match 'statistic'`. Or
`mount.nfs` reports `No such device` on a node that has `nfs-utils`
installed and the `.ko` files on disk.

### Inspecting the effective list

The allowlist file is the authoritative record. Its contents change
between releases, so this document does not copy it. Read it on any booted
node:

```sh
cat /usr/lib/modules-load.d/mke-modules.conf
lsmod
```

In broad terms, the list includes these items:

- container and overlay filesystems (`overlay`, `loop`, `fuse`, `vfat`)
- L2/bridge networking
- the nftables stack that the `iptables-nft` backend uses
- netfilter/conntrack
- the iptables/xtables and ipset extensions that MKE and Calico program
- IPv6 netfilter
- IPVS and SCTP match support
- the Calico encapsulation devices (IPIP, VXLAN, WireGuard)
- traffic-control modules for Calico bandwidth QoS
- TUN/TAP, kernel TLS, and device mapper

Hardware and root-filesystem modules are intentionally not in the list.
dracut and udev load those modules for the hardware that they detect.

> [!NOTE]
> `bootc-mirantis` extends the list when products need it. It added the Calico Enterprise
> requirements, including `ipip` for its default encapsulation mode, on
> 2026-09-08. They are in every image that `bootc-mirantis` built after that
> date. On an older image, you must add a module that the list does not yet
> contain through the extension point below. This needs a reboot.
> Compare the file on the node with what your workloads need. Do not assume
> the contents of a given release.

### Adding modules

The supported extension point is a drop-in in `/etc/modules-load.d/`, with
one module name on each line. For example, `/etc/modules-load.d/site-extra.conf`
with this content:

```
nfs
nfsv4
```

The same `systemd-modules-load.service` reads the files there, so they
have the same `Before=systemd-sysctl.service` order. The time when the
drop-in takes effect depends on when you create it:

| Created | Effective |
|---|---|
| Kickstart `%post` | **First boot**, no extra reboot. The installer writes the drop-in into the installed tree before the first boot |
| Cloud-init (`write_files`/`runcmd`) | **Second boot**. Both run after `systemd-modules-load.service` is already complete, and a new drop-in does not run it again. To get the module on first boot, run `modprobe` for it together with the write (possible while `kernel.modules_disabled` is `0`), or reboot after provisioning. Under the lockdown, a reboot is the only method |
| On an already-running node | **After one reboot**, or immediately with `modprobe` while `kernel.modules_disabled` is `0` |

A module is loadable only if its `.ko` is reachable. Therefore this method
works for modules that are in the image but not loaded. It cannot add a
module that the image does not contain.

For provision-time recipes, see
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations).
For the cloud-init equivalent, see
[Join machines with no-touch join](../operations-guide/join-machines-no-touch.md).
That document is the authoritative worked procedure and shows when the
drop-in takes effect on that path.
For an existing cluster, have `machine-config-controller` maintain the
drop-in and start the reboot as a separate resource. Do not edit nodes by
hand. See
[Machine configuration changes](../operations-guide/machine-config-operations.md)
and the worked NFS example in
[Collect support bundles](../operations-guide/collect-support-bundles.md).

## NetworkManager

The image installs and enables NetworkManager. The image contains
`/usr/lib/NetworkManager/conf.d/10-calico-unmanaged.conf`. This file marks
the Calico interfaces as unmanaged, so NetworkManager does not compete
with Calico for their configuration:

```
[keyfile]
unmanaged-devices=interface-name:cali*;interface-name:tunl*;interface-name:vxlan.calico;interface-name:vxlan-v6.calico;interface-name:wireguard.cali;interface-name:wg-v6.cali
```

The list includes the veth pairs (`cali*`) and the tunnel devices of each
encapsulation mode: IPIP (`tunl*`), VXLAN (`vxlan.calico`,
`vxlan-v6.calico`) and WireGuard (`wireguard.cali`, `wg-v6.cali`).

To override the file, put a file with the same name in
`/etc/NetworkManager/conf.d/`. It has priority over the `/usr/lib` copy.

> [!WARNING]
> NetworkManager parses `/usr/lib` snippets **first**. It replaces
> `unmanaged-devices` and does not merge it. A snippet of your own in `/etc`
> or `/run` that sets `unmanaged-devices` discards the list above. In that
> snippet, list the Calico interfaces again. If you do not, NetworkManager
> starts to manage them.

## Baked services

| Unit | Purpose |
|---|---|
| `mke-images.service` | On first boot, loads the MKE image tarball from `/usr/share/mke/` and each controller image tarball from `/usr/share/mke-controllers/images/` into Docker |
| `swarm-join.service` (with `/usr/libexec/swarm-join`) | No-touch worker join, gated on the `/var/lib/mke3/joined` sentinel. See [no-touch join](../operations-guide/no-touch-join.md) |
| `cri-dockerd-mke.service` / `cri-dockerd-mke.socket` | The MKE CRI shim for the Docker engine |

The image build enables only `mke-images.service` and `swarm-join.service`
(`systemctl enable mke-images swarm-join.service`). The
`cri-dockerd-mke` units are in the image as definitions. The build does not
enable them.

The image also contains:

- firewalld service definitions in `/usr/lib/firewalld/services/`
  (`mke_manager_external`, `mke_manager_internal`, `mke_manager_self`,
  `mke_worker_internal`, `mke_worker_self`). They are definitions only.
  Nothing binds them to a zone until the Ansible installer's
  `tasks/mke-open-ports-tasks.yml` or your own provisioning payload does.
- sshd crypto hardening at
  `/etc/ssh/sshd_config.d/10-crypto-hardening.conf`. This file is in
  `/etc`, not `/usr`, because sshd uses `Include` only for drop-ins from
  `/etc`.

You can disable each of these units at provision time. See
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations).

## Controller artifacts

Controller images, manifests and pinned versions are in
`/usr/share/mke-controllers/`. The post-install step deploys from them.
[Post-install controllers](install-controllers.md#in-image-sources-are-the-source-of-truth)
describes them. This document does not duplicate that description.
