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

As `bootc-mke3` is based on Rocky Linux, it is using [Anaconda](https://www.anaconda.com/docs/main) to perform installation and customisation with the help of Kickstart.

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
where `<oci-name>` is the name of `bootc-mke3` OCI image. The default one for Generic `bootc-mke3` image is `registry.mirantis.com/bootc-mke3/r9-bare:mcr25.0-mke3.8`. If you're not planning to perform air-gapped installation and/or use your own image registry, go with the default value.

> [!WARNING]
> It's user's responsibility to add those specific kickstart file lines. If it wasn't done, `bootc-mke3` won't be installed properly.

#### Summary

In order to perform a kickstart-based Generic `bootc-mke3` ISO customisation, following actions need to be performed:

1. Create a kickstart file that must contain `bootc-mke3` specific configuration lines (listed in previous section) along with user-provided customisation options.
2. Add `inst.ks=<kickstart-file-location>` to kernel parameters during the boot of ISO with the location of kickstart file specified.
