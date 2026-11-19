# Provision `bootc-mke3` with Terraform on vSphere

Use Terraform to provision machines on a vSphere backend.

## Requirements

A vSphere setup has many requirements. VMware clusters usually have a pre-defined network and resource allocation that are separate from machine provisioning. In this guide, the requirements define how to pre-configure a VMware system.

### Prerequisites 

Before you start this guide, make sure that you have these items:

1. Terraform installed locally. [The AWS module](provision-terraform-aws.md#prerequisites) requires `>= 1.5`. `terraform/vsphere` does not pin a `required_version`. Use a reasonably current Terraform release.
2. The `bootc-mke3` ISO in the vSphere datastore that you use for the `bootc-mke3` cluster installation.
3. vSphere networking that you configured as described in the [MKE documentation for network preparation](https://docs.mirantis.com/mke/3.9/install/predeployment/configure-networking.html).
    - In addition, we recommend that the `bootc-mke3` nodes have access to the NTP server (a local server or a public server) and to https://get.mirantis.com
4. The credentials of a user that can operate vSphere. Terraform uses them to provision VMs in vSphere. For a full list of the privileges that the user needs, see the [Terraform vSphere provisioner documentation](https://registry.terraform.io/providers/hashicorp/vsphere/latest/docs#notes-on-required-privileges).

### Image and VM template

Terraform creates all the VMs for the `bootc-mke3` cluster by cloning a VM template. You must create this template in advance. There are two options to prepare the template: manual and automated. Only the manual option is implemented and tested at this time.

The instructions below show how to prepare the VM template for the `bootc-mke3` cluster nodes.

#### Option 1 - Manual

##### Base OS installation

In the vSphere Web UI:

1. Create a new VM from the `bootc-mke3` ISO. During VM creation:
    - For `Guest OS Family`, select `Linux`.
    - For `Guest OS Version`, select `Other 4.x or later Linux (64-bit)`.
    - In the `Customize hardware` section, set the values according to the [official MKE hardware requirements](https://docs.mirantis.com/mke/3.9/common/mke-hw-reqs.html).
    - In the `Customize hardware` section, set the `New CD/DVD Drive` parameter to the `bootc-mke3` ISO and select the `Connect` check box.
2. Power on the VM.
3. Open the Web Console for the VM and boot into the Anaconda installer. Then do the standard installation steps (language, storage, user creation, network, and Begin Installation).
4. Click `Installation Destination`. Select automatic storage configuration (selected by default) and click `Done`.
5. Click `User Creation`. Create a user to pre-configure the VM template in the next steps. Set the password and select the `Make this user administrator` check box.
6. Configure the network interface in `Network & Host Name`. If there is a DHCP server in the network, turn the interface on and go to the next step. If there is no DHCP server, configure the network interface manually.
7. When all the configuration is complete, click `Begin Installation` and wait for the installation to complete.
8. Reboot the VM.
9. Convert the VM to a template.

**NOTE:** You can use multiple VM templates for different types of workloads or roles.

### Variables
To run the Terraform module, the Terraform provider needs the configuration to connect to the VMware system.

To configure the connection to vSphere, make a copy of the [terraform.tfvars.example](../../terraform/vsphere/terraform.tfvars.example) file in the same `terraform/vsphere` folder and name it `terraform.tfvars`.

All sections below use this copy (the `terraform.tfvars` file).

#### Authentication and Authorization

To authenticate, use user credentials that can operate vSphere (see the Prerequisites section).

Set the `vsphere_server` variable to the URL or IP address of vSphere without the protocol prefix (without `https://`).

Terraform uses `vsphere_user` and `vsphere_password` to authenticate to vSphere and do operations. The variables file (`terraform.tfvars`) is gitignored, so sensitive data is not exposed by mistake.

`allow_unverified_ssl` defaults to `false`, so Terraform verifies the vSphere server certificate. If your vSphere uses a self-signed certificate, set `allow_unverified_ssl = true` in `terraform.tfvars` (this is not recommended outside lab environments).

#### vSphere resources

Next, specify the resources for VM placement and provisioning.

You can get all the necessary resources with the [govc tool](https://github.com/vmware/govmomi/blob/main/govc/README.md), especially with the [govc ls](https://github.com/vmware/govmomi/blob/main/govc/USAGE.md#ls) and [govc find](https://github.com/vmware/govmomi/blob/main/govc/USAGE.md#find) commands.

**Important note:** `datastore` and `datastore_cluster` are two conflicting variables. Choose either a datastore or a datastore cluster.

These are examples:
- the `govc ls` command without arguments:
```
❯ govc ls
/MIRANTIS/vm
/MIRANTIS/network
/MIRANTIS/host
/MIRANTIS/datastore
```
- get resource pools:
```
❯ govc find . -type p
./host/vCluster-MKEx/Resources
./host/vCluster-MKEx/Resources/MKEx-ResPool
```
- get network resources:
```
❯ govc ls /MIRANTIS/network/
/MIRANTIS/network/DMZ_MKEx_demo
/MIRANTIS/network/DSwitch-MKEx
```

#### bootc-mke3 cluster infrastructure configuration

The variables for the `bootc-mke3` cluster infrastructure are self-descriptive.

Note these points:
1. Make the manager and worker disk sizes not smaller than the sizes in the VM template.
2. Configure the IP addresses of the managers, workers, and gateway according to the vSphere network configuration. Make sure that the VMs can reach DNS.
3. Terraform uses the `cluster_name` variable as a prefix for VM names. For example, if cluster_name = "bootc-mke3-cluster", the names of the managers are `bootc-mke3-cluster-mngr1`, `bootc-mke3-cluster-mngr2`, and so on. The names of the workers are `bootc-mke3-cluster-wrk1`, `bootc-mke3-cluster-wrk2`, and so on.
4. `vm_user` (required, no default) — the username that the deployed VMs
   are configured with. Current vSphere testing practice is to provision
   the VM template with the **bare** ISO variant and kickstart (see [Option
   1](#option-1---manual) above), not with cloud-init. A vSphere-specific
   cloud-init platform build existed previously, but it is not in use
   today (see the note in [provisioning.md](provisioning.md#machines)).
   The value must match the user that your template is configured to
   create and authorize, however you built the template.
5. `firmware` (required, no default) — `bios` or `efi`. The value must match how the VM
   template was created.

## Procedure

1. Configure Terraform with your vSphere credentials and environment-specific variables (see previous section).
2. Prepare Terraform: `terraform init`
3. Run Terraform: `terraform apply`
4. To get the Ansible inventory, run: `terraform output -raw ansible_inventory`

Terraform state is local (`terraform/vsphere/terraform.tfstate`, gitignored). It contains the vSphere password in plain text, so keep it private. There is no locking or sharing. To collaborate, add a `backend` block in `providers.tf` and run `terraform init -migrate-state`.

## Expected Results

1. Terraform operations ended without error.
2. Terraform created the VMs according to the Terraform configuration.
3. Terraform produced an ansible inventory for the management stage.
