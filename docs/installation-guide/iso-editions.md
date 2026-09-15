# ISO editions 

Mirantis provides two ISO editions - Simple and Generic.

**Simple** is used mostly for demo/test purposes, while **Generic** is considered production-grade solution (although it is still can be used for demo/test purposes).

## Simple 

Simple ISO contains default and quite basic configuration that is already applied to an ISO. Limited customisation options are available in the user space once machine is booted.

Simple ISO considerations:

1. Default login is **bootc-mke3/password**. Once login, you will be immediately forced to change password of the default `bootc-mke3` user.
2. Auto-partitioning is used.
3. Non-interactive installation is used.
4. For network configuration DHCP is selected as default way of setting up the configuration. However, if you don't have DHCP server in the network, you can change network configuration later when you login into the booted machine. [NetworkManager](https://networkmanager.dev/) is used to configure networking.

## Generic

Generic ISO - is a plain ISO that lacks any customisation.

As `bootc-mke3` is based on Rocky Linux, it is using [Anaconda](https://anaconda-installer.readthedocs.io/en/latest/) to perform installation and customisation with the help of Kickstart.

### Generic image customisation

You can use [kickstart](https://en.wikipedia.org/wiki/Kickstart_(Linux)) to customise Generic `bootc-mke3` image provided by Mirantis. However, some details need to be mentioned:

1. Kickstart file usually fed to Anaconda installer by using `inst.ks=<kickstart-file-location>` kernel parameter. Generic `bootc-mke3` image **does not contain** that line in kernel boot parameters. It was done on purpose because the end user can user different ways of providing kickstart file, see [this documentation page](https://docs.fedoraproject.org/en-US/fedora/f36/install-guide/advanced/Kickstart_Installations/) for more details.

2. The kickstart provided for customisation **MUST** contain following lines:
```
ostreecontainer --url=/run/install/repo/container --transport=oci --no-signature-verification

%post
bootc switch --mutate-in-place --transport registry <oci-name>
if [ -c /dev/ttyS0 ]; then
  echo "Install finished" > /dev/ttyS0 || true
fi
%end
```
where `<oci-name>` is the name of the `bootc-mke3` OCI image, of the form `registry.mirantis.com/bootc-mke3/r<rocky-version>-mcr<mcr-version>-mke<mke-version>-bare:<build-tag>` (for example, `registry.mirantis.com/bootc-mke3/r9.8-mcr29.6.1-mke3.9.5-bare:20260814-15`) — `<build-tag>` is a unique per-build identifier, not derived from the version, so it always changes between builds even at the same MCR/MKE/Rocky version; check the [Assets section](../../README.md#assets) or the current release notes for the exact current tag. If you're not planning to perform air-gapped installation and/or use your own image registry, go with the default `bootc-mke3` image for your target platform.

Verify `<oci-name>`'s cosign signature before putting it in the kickstart
file — see
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

> [!WARNING]
> It's user's responsibility to add those specific kickstart file lines. If it wasn't done, `bootc-mke3` won't be installed properly.

### Common kickstart customisations

The recipes below go in the same kickstart file as the mandatory lines
above, inside its `%post` section (or a second `%post --erroronfail`
block). They cover the two customisations that most often have to happen at
provision time rather than afterwards. For what the image ships and why
these are the supported extension points, see
[Image architecture](image-architecture.md).

#### Preload additional kernel modules

The image loads a fixed module allowlist at boot and then sets
`kernel.modules_disabled=1`, which locks the module subsystem for the rest
of the boot session. That latch is one-way: a module not loaded before it
applies cannot be loaded later by any means, so any module your workloads
need beyond the image's list must be declared before the node first boots —
or the node must be rebooted after adding it. See
[Kernel modules](image-architecture.md#kernel-modules).

```
%post --erroronfail
cat > /etc/modules-load.d/site-extra.conf <<'EOF'
nfsd
EOF
%end
```

Because `%post` runs before the installed system has ever booted, the
drop-in is effective on **first boot** — no additional reboot is needed.
`systemd-modules-load.service` reads `/etc/modules-load.d/` and is ordered
`Before=systemd-sysctl.service`, so the modules load while loading is still
permitted. Verify on the booted node with:

```sh
lsmod | grep <module>
```

#### Disable a baked service

Any unit the image ships can be disabled — or masked, if something else
might pull it in — from `%post`:

```
%post --erroronfail
systemctl disable firewalld.service
%end
```

The same pattern (`systemctl disable <unit>` / `systemctl mask <unit>`)
applies to any of the baked units listed in
[Image architecture](image-architecture.md#baked-services).

> [!NOTE]
> For firewalld specifically this is usually unnecessary. Nodes installed
> by the Ansible installer have their firewall managed for them — per-service
> rules from `tasks/mke-open-ports-tasks.yml`, or firewalld disabled
> outright via the `disable_firewalld` variable (see
> [Harden MKE 3 Kubernetes](../operations-guide/harden-mke3-kubernetes.md)).
> Workers that arrive by no-touch join are never touched by the installer,
> so their firewall is configured by the same provisioning payload instead
> (see [Join machines with no-touch join](../operations-guide/join-machines-no-touch.md)).

#### Cloud builds

The cloud-platform builds (AMI/QCOW2) achieve both of the above through
cloud-init `write_files`/`runcmd` instead of kickstart. Worked examples of
both, including the reboot gating needed when a module is added to an
already-running node, are in
[Join machines with no-touch join](../operations-guide/join-machines-no-touch.md).

### Summary

In order to perform a kickstart-based Generic `bootc-mke3` ISO customisation, following actions need to be performed:

1. Create a kickstart file that must contain `bootc-mke3` specific configuration lines (listed in [Generic image customisation](#generic-image-customisation)) along with any user-provided customisation options, such as those in [Common kickstart customisations](#common-kickstart-customisations).
2. Add `inst.ks=<kickstart-file-location>` to kernel parameters during the boot of ISO with the location of kickstart file specified.
