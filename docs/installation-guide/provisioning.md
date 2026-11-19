# Provisioning

Provisioning is the process that prepares cluster infrastructure which meets the requirements for a `bootc-mke3` installation.

## Registry

`bootc-mke3` releases as an OCI image. The registry stores and distributes these OCI images.

If the cluster machines have access to the internet, the official Mirantis `bootc-mke3` OCI images are in the publicly accessible MSR registry (registry.mirantis.com). Anyone can use them.

For production-grade air-gapped clusters, we recommend that you have your own registry that the cluster machines can access. We recommend that you put `bootc-mke3` OCI images with the desired version of the products in this registry. There are different methods to get the image. The most common method is to set up mirroring from the official Mirantis registry (registry.mirantis.com).

Before you pull an image from either registry for use, verify its cosign
signature. See
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

## Private registry usage

If you plan to use a private OCI registry to store `bootc-mke3` artifacts (OCI images) for your cluster, you must supply registry credentials for authentication. Add a credentials file to each machine, because most operations (for example, upgrade) must pull the OCI image from the registry.

There are different methods to inject the credentials into the machine. These are the common methods, in order of applicability:

- **kickstart** (`%post`) for ISO-provisioned machines. This is the standard production path.
- The provided [ansible playbook](../../ansible/reg-creds-playbook.yml) (setup below), where SSH access is still available.
- cloud-init user-data, for cloud-platform builds (AMI/QCOW2) only. AMI is mainly for internal testing. QCOW2 is publicly announced and downloadable.

Select the method that is most suitable for your use case.

Requirements for the registry credentials:

1. Store the credentials in a file that follows the [containers registry authentication file syntax](https://github.com/containers/image/blob/main/docs/containers-auth.json.5.md).
2. Store the file as `/etc/ostree/auth.json`.

You can also use the [existing ansible playbook](../../ansible/reg-creds-playbook.yml) to do this operation.

### Ansible playbook setup

The playbook reads credentials from `ansible/vars/reg-creds`, which Git ignores. Before you run the playbook, create the file from the provided template:

```bash
cp ansible/vars/reg-creds.example ansible/vars/reg-creds
```

Then edit `ansible/vars/reg-creds` and replace `<username>` and `<password>` with your registry credentials. Each line has this format:

```
registry.mirantis.com <username> <password>
```

Add one line for each registry. Git ignores the file, so Git never commits it.

## Machines

The cluster must have one or more compute machine nodes. To use `bootc-mke3`, the machines must meet these requirements:

1. All machines must use the `bootc-mke3` source base (image). For available images, see the [Releases page](https://github.com/Mirantis/bootc-mke3/releases)

> [!NOTE]
> **Simple** ISO edition is mostly for demo and test purposes. For production-grade clusters, we recommend the **Generic** ISO. The QCOW2 cloud image is not customised. The user must customise and secure it appropriately for production use.

2. All machines must meet the MKE hardware requirements. For the list of requirements, see the Mirantis Kubernetes Engine official documentation, [hardware requirements section](https://docs.mirantis.com/mke/3.9/common/mke-hw-reqs.html)

### Machine customisation at provision time

You customise machines at provision time with **kickstart** for
ISO-provisioned machines. This is the standard production mechanism. For
the mandatory lines, see
[ISO editions](iso-editions.md#generic-image-customisation). For recipes, see
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations).
cloud-init is available only on the cloud-platform builds
(AMI/QCOW2). AMI builds are mainly for internal testing. QCOW2 is publicly
announced and downloadable. Where this documentation offers
both mechanisms, we recommend kickstart, unless you work specifically with
a cloud build.

It is best to make some configuration **before the machine first boots**. Extra
kernel modules are the main example. A module that a kickstart payload
declares is present from first boot, because `%post` writes into
the installed tree before the machine boots. A cloud-init payload is not
equivalent. It runs after `systemd-modules-load.service`, so the module
arrives on the second boot, unless the payload runs `modprobe` for it
together with the write. See [Adding
modules](image-architecture.md#adding-modules). On an image that latches
`kernel.modules_disabled=1` early in boot, a reboot is the only method
in that case (current images have `0`). Disabling a baked service
is the other common example. Both examples need a machine source that you
can customise: the **Generic** ISO with your own kickstart file, or a
cloud build with cloud-init user-data. The **Simple** ISO has its own
embedded kickstart and has no such hook. On it, you can make these
changes only after installation, on the running node. Where the module
latch applies, you must also reboot. See
[Image architecture](image-architecture.md) for what the image contains and
which customisation points Mirantis supports.

### Machine connection

For the installer to interact with the cluster, the ansible tooling must be able to connect to the machines. Ansible has a flexible system to connect to machines. Many [options are available](https://docs.ansible.com/ansible/latest/inventory_guide/connection_details.html).

The preferred method of machine connection is SSH with a passwordless user that has sudo access.

## Network 

All cluster machines must be in a valid network. For how to configure the network correctly, see the Mirantis Kubernetes Engine official documentation, [networking section](https://docs.mirantis.com/mke/3.9/install/predeployment/configure-networking.html).

## Provisioning output (coupling to the installer/upgrader)

When provisioning is complete and the machine cluster is ready, provisioning must produce an ansible inventory. The inventory defines how ansible connects to all of the machine nodes of the cluster. The [Ansible inventory input document](ansible-inventory-input.md) describes the input parameters of the Ansible tooling.

## Provisioning approach

### Terraform tooling

This `bootc-mke3` tooling includes a number of terraform modules that can provision a cluster.

- **vSphere.** For the full guide to provision a `bootc-mke3` cluster on vSphere, see [this document](provision-terraform-vsphere.md).
- **AWS.** For the full guide to provision a `bootc-mke3` cluster on AWS, see [this document](provision-terraform-aws.md).

> [!IMPORTANT]
> Mirantis considers AWS-based provisioning **dev/testing only**. It is not a production-grade `bootc-mke3` provisioning path. Mirantis maintains AWS AMIs for `bootc-mke3` builds for this purpose. The AMI IDs are not published in this document and are not publicly announced. Contact your Mirantis representative to get a current AMI ID and its owning AWS account for your region.

### Manual provisioning (roll your own)

You do not have to use the Mirantis tooling to provision. If a cluster has custom needs that the Mirantis provisioning does not address, you can create the cluster with any approach. The resulting cluster must have the needed machine and cluster components, and you must be able to create an ansible inventory.

For more details, see the runbook for [manually provisioning a cluster](provision-manually.md).

