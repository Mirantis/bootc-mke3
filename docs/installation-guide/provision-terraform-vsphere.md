# Provision `bootc-mke3` with Terraform on vSphere

Provision machines on a vSphere backend, using terraform.

## Requirements

VSphere setup has a significant set of requirements, because VMWare clusters tend to consist of pre-defined network and resource allocation separate from machine provision. For the purpose of this guide, the requirements define how a VMware system should be pre-configured.

### Prerequisites 

In order to proceed with this guide

1. Terraform installed locally. Unlike [the AWS module](provision-terraform-aws.md#prerequisites) (which requires `>= 1.5`), `terraform/vsphere` pins no `required_version` — use a reasonably current Terraform release.
2. Obtain `bootc-mke3` ISO and put it to the vSphere datastore that will be used for `bootc-mke3` cluster installation
3. Configure vSphere networking by following [MKE documentation for network preparation](https://docs.mirantis.com/mke/3.9/install/predeployment/configure-networking.html)
    - Additionally, `bootc-mke3` nodes should have access to the NTP server (customer's local one or public one) and to https://get.mirantis.com
4. In order to provision VMs in vSphere, you need to specify credentials of a user, that can operate vSphere. For a full list of privileges needed for the user, please see [Terraform vSphere provisioner documentation](https://registry.terraform.io/providers/hashicorp/vsphere/latest/docs#notes-on-required-privileges).

### Image and VM template

All the VMs for `bootc-mke3` cluster will be created by cloning a VM template. This template needs to be created in advance. There are 2 possible options for template preparation -- manual and automated. Currently, only manual option was implemented and tested.

Below you can find the instructions on how to prepare VM template for `bootc-mke3` cluster nodes.

#### Option 1 - Manual

##### Base OS installation

In the vSphere Web UI:

1. Create new VM from `bootc-mke3` ISO. During VM creation:
    - As `Guest OS Family` select `Linux`.
    - As `Guest OS Version` select `Other 4.x or later Linux (64-bit)`.
    - In `Customize hardware` section set values according to [official MKE hardware requirements](https://docs.mirantis.com/mke/3.9/common/mke-hw-reqs.html).
    - In `Customize hardware` section use `bootc-mke3` ISO in `New CD/DVD Drive` parameter and check box to `Connect` it.
2. Power On the VM.
3. Launch Web Console for the VM and boot into the Anaconda installer, then proceed through the standard installation steps (language, storage, user creation, network, and Begin Installation).
4. Next, click on `Installation Destination`. Select automatic storage configuration (selected by default) and click `Done`.
5. Click on `User Creation`. Create a user that will be used to pre-configure VM template in the next steps. Set the password and check box `Make this user administrator`.
6. Configure network interface in `Network & Host Name`. If there is a DHCP server in the network -- just turn the interface on and proceed to the next step. If there is no DHCP server -- please configure network interface manually.
7. When all the configurations are done, click on `Begin Installation` and wait for the installation to complete.
8. Reboot the VM.
9. Convert VM to the template.

**NOTE:** Multiple VM templates can be used for different type of workloads/roles.

### Variables
In order to run the Terraform module, the terraform provider will need configuration for connecting to the VMware system.

To configure connection to vSphere, create a copy of [terraform.tfvars.example](../../terraform/vsphere/terraform.tfvars.example) file in the same `terraform/vsphere` folder and name it `terraform.tfvars`.

In all the sections below we will be working with the copy, i.e. `terraform.tfvars` file.

#### Authentication and Authorization

In order to authenticate, you need to use user credentials that can operate vSphere (see Prerequisites section)

`vsphere_server` variable needs to be set to the URL or IP address of vSphere without the protocol prefix (without `https://`).

`vsphere_user` and `vsphere_password` are used to authenticate to the vSphere and perform operations. Variables file (`terraform.tfvars`) is gitignored, so any sensitive data won't be exposed by mistake.

`allow_unverified_ssl` defaults to `false`, so the vSphere server certificate is verified. If your vSphere uses a self-signed certificate, set `allow_unverified_ssl = true` in `terraform.tfvars` (not recommended outside lab environments).

#### vSphere resources

Next, you need to specify different resources that will be used for VM placement and provisioning.

All the necessary resources can be obtained with the help of [govc tool](https://github.com/vmware/govmomi/blob/main/govc/README.md) and especially with [govc ls](https://github.com/vmware/govmomi/blob/main/govc/USAGE.md#ls) and [govc find](https://github.com/vmware/govmomi/blob/main/govc/USAGE.md#find) commands.

**Important note:** `datastore` and `datastore_cluster` are two conflicting variables. You should choose either Datastore or Datastore cluster to use

Here are some examples:
- `govc ls` command without arguments:
```
❯ govc ls
/MIRANTIS/vm
/MIRANTIS/network
/MIRANTIS/host
/MIRANTIS/datastore
```
- get Resource Pools:
```
❯ govc find . -type p
./host/vCluster-MKEx/Resources
./host/vCluster-MKEx/Resources/MKEx-ResPool
```
- get Network resources:
```
❯ govc ls /MIRANTIS/network/
/MIRANTIS/network/DMZ_MKEx_demo
/MIRANTIS/network/DSwitch-MKEx
```

#### bootc-mke3 cluster infrastructure configuration

Variable for `bootc-mke3` cluster infrastructure are quite self-descriptive. 

Few things that need to be mentioned:
1. Manager and worker disk sizes should be not less that ones defined in VM template.
2. IP addresses of managers, workers and gateway should be configured according to vSphere network configuration. DNS should be reachable by VMs.
3. `cluster_name` variable will be used as a prefix for VM names. E.g. if cluster_name = "bootc-mke3-cluster", then names of managers will look like this: `bootc-mke3-cluster-mngr1`, `bootc-mke3-cluster-mngr2`, etc. Names of workers will look like this: `bootc-mke3-cluster-wrk1`, `bootc-mke3-cluster-wrk2`, etc.
4. `vm_user` (required, no default) — the username the deployed VMs are
   configured with. Current vSphere testing practice provisions the VM
   template using the **bare** ISO variant and kickstart (see [Option
   1](#option-1---manual) above), not cloud-init — a vSphere-specific
   cloud-init platform build existed previously but is not what's used
   today (see the note in [provisioning.md](provisioning.md#machines)).
   Must match whatever user your template is actually configured to
   create/authorize, however that template was built.
5. `firmware` (required, no default) — `bios` or `efi`, matching how the VM
   template itself was created.

## Procedure

1. Configure TF to use your VSphere credentials and environment specific variables (see previous section).
2. Prepare TF: `terraform init`
3. Run TF: `terraform apply`
4. To get Ansible inventory, run: `terraform output -raw ansible_inventory`

Terraform state is local (`terraform/vsphere/terraform.tfstate`, gitignored). It contains the vSphere password in plain text, so keep it private. There is no locking or sharing; to collaborate, add a `backend` block in `providers.tf` and run `terraform init -migrate-state`.

## Expected Results

1. Terraform operations concluded without error.
2. VMs are created according to Terraform configuration.
3. Terraform produced an ansible inventory for the management stage.
