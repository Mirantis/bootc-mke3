# ISO editions 

Mirantis provides two ISO editions: Simple and Generic.

**Simple** is mostly for demo and test purposes. Mirantis considers **Generic** a production-grade solution. You can also use it for demo and test purposes.

## Simple 

The Simple ISO has a default and basic configuration that is already applied. After the machine boots, only a few customisation options are available in the user space.

Simple ISO considerations:

1. The default login is **bootc-mke3/password**. After you log in, the system forces you to change the password of the default `bootc-mke3` user.
2. The installation uses auto-partitioning.
3. The installation is non-interactive.
4. The default network configuration method is DHCP. If the network has no DHCP server, you can change the network configuration after you log in to the booted machine. [NetworkManager](https://networkmanager.dev/) configures the networking.

## Generic

The Generic ISO is a plain ISO that has no customisation.

`bootc-mke3` is based on Rocky Linux. It uses [Anaconda](https://anaconda-installer.readthedocs.io/en/latest/) for the installation, and Kickstart for the customisation.

### Generic image customisation

You can use [kickstart](https://en.wikipedia.org/wiki/Kickstart_(Linux)) to customise the Generic `bootc-mke3` image that Mirantis provides. Note these details:

1. Usually, the `inst.ks=<kickstart-file-location>` kernel parameter gives the kickstart file to the Anaconda installer. The Generic `bootc-mke3` image **does not contain** that line in the kernel boot parameters. This is on purpose, because the end user can use different ways to provide the kickstart file. For more details, see [this documentation page](https://docs.fedoraproject.org/en-US/fedora/f36/install-guide/advanced/Kickstart_Installations/).

2. The kickstart that you provide for customisation **MUST** contain these lines:
```
ostreecontainer --url=/run/install/repo/container --transport=oci --no-signature-verification

%post
bootc switch --mutate-in-place --transport registry <oci-name>
if [ -c /dev/ttyS0 ]; then
  echo "Install finished" > /dev/ttyS0 || true
fi
%end
```
where `<oci-name>` is the name of the `bootc-mke3` OCI image, of the form `registry.mirantis.com/bootc-mke3/r<rocky-version>-mcr<mcr-version>-mke<mke-version>-bare:<build-tag>` (for example, `registry.mirantis.com/bootc-mke3/r9.8-mcr29.8.0.0-mke3.9.7-bare:20261008-90`). `<build-tag>` is a unique identifier for each build. It is not derived from the version. It always changes between builds, even at the same MCR, MKE, and Rocky version. For the exact current tag, see the [Releases page](https://github.com/Mirantis/bootc-mke3/releases). If you do not plan to do an air-gapped installation or use your own image registry, use the default `bootc-mke3` image for your target platform.

Before you put `<oci-name>` in the kickstart file, verify its cosign signature.
See
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

> [!WARNING]
> The user is responsible for adding those specific kickstart file lines. If the user does not add them, `bootc-mke3` is not installed correctly.

### Common kickstart customisations

Put the recipes below in the same kickstart file as the mandatory lines
above. Put them in its `%post` section (or a second `%post --erroronfail`
block). They cover the two customisations that most often must be done at
provision time and not afterwards. For what the image contains, and why
these are the supported extension points, see
[Image architecture](image-architecture.md).

#### Preload additional kernel modules

The image loads a fixed module allowlist at boot. Declare here each module
that your workloads need in addition to that list. Then the module is
present from the first boot of the node. This is necessary on an image that
sets `kernel.modules_disabled=1`. That latch works in one direction only. A
module that is not loaded before the latch applies cannot be loaded later
by any means. Current images set `kernel.modules_disabled` to `0`. Because this is a kickstart
`%post`, the drop-in is written into the installed tree, and the module is
loaded on the first boot of the node. The cloud-init path is different. See
[Adding modules](image-architecture.md#adding-modules) for the timing
table and [Kernel modules](image-architecture.md#kernel-modules) for the
allowlist.

```
%post --erroronfail
cat > /etc/modules-load.d/site-extra.conf <<'EOF'
nfsd
EOF
%end
```

`%post` runs before the installed system has ever booted. Thus the
drop-in is effective on **first boot**, and no additional reboot is necessary.
`systemd-modules-load.service` reads `/etc/modules-load.d/` and is ordered
`Before=systemd-sysctl.service`. Thus the modules load while loading is still
permitted. Verify on the booted node with:

```sh
lsmod | grep <module>
```

#### Disable a baked service

You can disable any unit that the image contains from `%post`. You can also
mask the unit, if something else might start it:

```
%post --erroronfail
systemctl disable firewalld.service
%end
```

The same pattern (`systemctl disable <unit>` / `systemctl mask <unit>`)
applies to each of the baked units listed in
[Image architecture](image-architecture.md#baked-services).

> [!NOTE]
> For firewalld, this is usually not necessary. The Ansible installer
> manages the firewall of the nodes that it installs. It uses per-service
> rules from `tasks/mke-open-ports-tasks.yml`, or it disables firewalld
> with the `disable_firewalld` variable (see
> [Harden MKE 3 Kubernetes](../operations-guide/harden-mke3-kubernetes.md)).
> The installer never changes workers that join with no-touch join.
> The same provisioning payload configures their firewall
> (see [Join machines with no-touch join](../operations-guide/join-machines-no-touch.md)).

#### Cloud builds

The cloud-platform builds (AMI/QCOW2) do both of the above with
cloud-init `write_files`/`runcmd` and not with kickstart. Worked examples of
both are in
[Join machines with no-touch join](../operations-guide/join-machines-no-touch.md).
They include the reboot gating that is necessary when you add a module to a
node that is already running.

### Summary

To customise the Generic `bootc-mke3` ISO with kickstart, do these steps:

1. Create a kickstart file. It must contain the `bootc-mke3` specific configuration lines (listed in [Generic image customisation](#generic-image-customisation)). Add your own customisation options, such as those in [Common kickstart customisations](#common-kickstart-customisations).
2. Add `inst.ks=<kickstart-file-location>` to the kernel parameters when you boot the ISO. Set it to the location of the kickstart file.
