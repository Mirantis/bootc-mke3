# Provisioning

Provisioning is the process of preparing a cluster of MKEx compute nodes in a network cluster that can support the Mirantis products.

# Components of the cluster

## Machines

One or more compute machine nodes

1. All machines must use the MKEx source base (image)
2. All machines can be connected to by the installer, using any valid ansible connection method
3. All machines meet the minimum product requirements for the used Mirantis products: memory, disk, machine-firewall

### Machine connection

In order for the installer to interact with the cluster, the ansible tooling must be able to connect to the machines. As ansible has a flexible system for connecting to machines, a wide variety of [options are available](https://docs.ansible.com/ansible/latest/inventory_guide/connection_details.html).

Machine users used for installation and upgrading will need to be able to escalate privilege. This is done using sudo on MKEx, so sudo will need to be configured on the machine.

* SSH is the most common connection method, so each machine should have a system user, with acceptible connection method (ssh keys), with sudo access configured *

## Network 

The cluster machines must all be in a valid network. Please see Mirantis Kubernetes Engine official documentation pages, [networking section](https://docs.mirantis.com/mke/3.8/install/predeployment/configure-networking.html), on how to properly configure networking.

## Provisioning output (coupling to the installer/upgrader)

When provisioning is complete, and the machine cluster is ready, provisioning needs to produce an ansible inventory which defines how ansible can connect to all of the machine nodes of the cluster. Description of Ansible tooling input parameters can be found in [Ansible inventory input document](ansible-inventory-input.md).

## Provisioning approach

### Terraform tooling

This MKEx tooling includes a number of terraform modules that can provision a cluster. 

- **vSphere.** Full guide on how to provision MKEx cluster on vSphere can be found in [this document](runbooks/provision-terraform-vsphere.md)

### Manual provisioning (roll your own)

There is no requirement to use any of the Mirantis tooling for provisioning. If a cluster has custom needs that are not addressed with the Mirantis provisioning, then the cluster can be created with any approach, as long as the resulting clustess provides the needed machine and cluster components, and an ansible inventory can be created.

Further details can be found in the runbook for [manually provisioning a cluster](runbooks/provision-manually.md)

## Private registry usage

If you're planning to use private OCI registry to store MKEx artifacts (OCI images) and use them for your cluster, you will need to provide registry credentials in order to authenticate. To do so, you will need to add credentials file into the each machine, because for most of the operations (like upgrade) there will be a need to pull OCI image from the registry.

The way of injecting credentials into the machine can vary from case to case. Some common ways to do so is to use cloud-init or ansible. The user should select the way that is more suitable for the use case.

Requirements for the registry credentials:

1. Credentials should be stored in the file and following [containers registry authentication file syntax](https://github.com/containers/image/blob/main/docs/containers-auth.json.5.md)
2. File should be stored as `/etc/ostree/auth.json`
