# Provisioning

Provisioning is the process of preparing cluster infrastructure that meets the requirements to be used for `bootc-mke3` installation.

## Registry

`bootc-mke3` represents a release via OCI image. The registry is used to store and distribute such OCI images.

For a use cases where cluster machines has access to the internet, official Mirantis `bootc-mke3` OCI images are stored in public accessible MSR registry (registry.mirantis.com) and can be used by anyone.

For production-grade air-gapped clusters, users should have their own registry that can be accessed by the cluster machines. This registry should contain `bootc-mke3` OCI images with desired version of products. The way of obtaining the image can vary, but the most common way is to set up a mirroring from official Mirantis registry (registry.mirantis.com).

Before pulling an image from either registry for use, verify its cosign
signature — see
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

## Private registry usage

If you're planning to use private OCI registry to store `bootc-mke3` artifacts (OCI images) and use them for your cluster, you will need to provide registry credentials in order to authenticate. To do so, you will need to add credentials file into the each machine, because for most of the operations (like upgrade) there will be a need to pull OCI image from the registry.

The way of injecting credentials into the machine can vary from case to case. Common ways, in order of applicability: **kickstart** (`%post`) for ISO-provisioned machines — the standard production path; the provided [ansible playbook](../../ansible/reg-creds-playbook.yml) (setup below) where SSH access is still available; or cloud-init user-data — cloud-platform builds (AMI/QCOW2) only, AMI primarily used for internal testing while QCOW2 is publicly announced/downloadable. The user should select the way that is most suitable for the use case.

Requirements for the registry credentials:

1. Credentials should be stored in the file and following [containers registry authentication file syntax](https://github.com/containers/image/blob/main/docs/containers-auth.json.5.md)
2. File should be stored as `/etc/ostree/auth.json`

You can also use [existing ansible playbook](../../ansible/reg-creds-playbook.yml) to perform this operation.

### Ansible playbook setup

The playbook reads credentials from `ansible/vars/reg-creds`, which is excluded from version control. Before running the playbook, create the file from the provided template:

```bash
cp ansible/vars/reg-creds.example ansible/vars/reg-creds
```

Then edit `ansible/vars/reg-creds` and replace `<username>` and `<password>` with your actual registry credentials. Each line follows the format:

```
registry.mirantis.com <username> <password>
```

Add one line per registry. The file is gitignored and will never be committed.

## Machines

Cluster should consist of one or more compute machine nodes. In order to use `bootc-mke3`, machines should meet following requirements:

1. All machines must use the `bootc-mke3` source base (image). For available images see [Assets section](../../README.md#assets)

> [!NOTE]
> **Simple** ISO edition is used mostly for demo/test purposes. For production-grade clusters consider using **Generic** ISO. The QCOW2 cloud image ships uncustomised — it is the user's responsibility to customise and secure it appropriately for production use.

2. All machines meet MKE hardware requirements. For the list of requirements, please see Mirantis Kubernetes Engine official documentation pages, [hardware requirements section](https://docs.mirantis.com/mke/3.9/common/mke-hw-reqs.html)

### Machine customisation at provision time

Machine customization at provision time is done via **kickstart** for
ISO-provisioned machines — the standard production mechanism (see
[ISO editions](iso-editions.md#generic-image-customisation) for the
mandatory lines and
[Common kickstart customisations](iso-editions.md#common-kickstart-customisations)
for recipes). cloud-init is only available on the cloud-platform builds
(AMI/QCOW2) — AMI builds are primarily used for internal testing, while
QCOW2 is publicly announced/downloadable. Where this documentation offers
both mechanisms, prefer kickstart unless you are specifically working with
a cloud build.

Some configuration has to exist **before the machine first boots**. Extra
kernel modules are the load-bearing case: the image latches
`kernel.modules_disabled=1` early in boot, after which no module can be
loaded until the next reboot. Disabling a baked service is the other common
case. Both require a machine source you can customise — the **Generic** ISO
with your own kickstart file, or a cloud build with cloud-init user-data.
The **Simple** ISO embeds its own kickstart and exposes no such hook, so on
it these changes can only be made after installation, on the running node,
with a reboot wherever the module latch is involved. See
[Image architecture](image-architecture.md) for what the image ships and
which customisation points are supported.

### Machine connection

In order for the installer to interact with the cluster, the ansible tooling must be able to connect to the machines. As ansible has a flexible system for connecting to machines, a wide variety of [options are available](https://docs.ansible.com/ansible/latest/inventory_guide/connection_details.html).

Preferred way of machine connection is SSH with a passwordless user that has sudo access.

## Network 

The cluster machines must all be in a valid network. Please see Mirantis Kubernetes Engine official documentation pages, [networking section](https://docs.mirantis.com/mke/3.9/install/predeployment/configure-networking.html), on how to properly configure networking.

## Provisioning output (coupling to the installer/upgrader)

When provisioning is complete, and the machine cluster is ready, provisioning needs to produce an ansible inventory which defines how ansible can connect to all of the machine nodes of the cluster. Description of Ansible tooling input parameters can be found in [Ansible inventory input document](ansible-inventory-input.md).

## Provisioning approach

### Terraform tooling

This `bootc-mke3` tooling includes a number of terraform modules that can provision a cluster. 

- **vSphere.** Full guide on how to provision `bootc-mke3` cluster on vSphere can be found in [this document](provision-terraform-vsphere.md)
- **AWS.** Full guide on how to provision `bootc-mke3` cluster on AWS can be found in [this document](provision-terraform-aws.md)

> [!IMPORTANT]
> AWS-based provisioning is considered **dev/testing only**, not a production-grade `bootc-mke3` provisioning path. Mirantis maintains AWS AMIs for `bootc-mke3` builds for this purpose, but AMI IDs are not published in this document and are not publicly announced. Contact your Mirantis representative to obtain a current AMI ID and its owning AWS account for your region.

### Manual provisioning (roll your own)

There is no requirement to use any of the Mirantis tooling for provisioning. If a cluster has custom needs that are not addressed with the Mirantis provisioning, then the cluster can be created with any approach, as long as the resulting cluster provides the needed machine and cluster components, and an ansible inventory can be created.

Further details can be found in the runbook for [manually provisioning a cluster](provision-manually.md)

