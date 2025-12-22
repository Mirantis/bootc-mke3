# Manually provision a cluster

If none of the `bootc-mke3` provisioning tooling meets the needs of an `bootc-mke3` infrastructure cluster, then manual provisoning will be needed. This involves the creation of a number of machine node targets for an MKE cluster, in a network that meets the documented Mirantis product needs.

Because manual provisioning is so diverse, this runbook won't be able to focus on technical directives, and will have to focus on more abstract concepts.

## Pre-Requisites

1. A machine installation source. Mirantis offers an installation ISO image for this purpose.

## Process

1. Provision a network for your `bootc-mke3` cluster
   a. that allows communication based on the [MKE networking requirements](https://docs.mirantis.com/mke/3.7/install/predeployment/configure-networking.html)
   
2. Provision a number of `bootc-mke3` machines, using the `bootc-mke3` image source
   a. Machine resource specifications that meet the [MKE minimum resource requirements](https://docs.mirantis.com/mke/3.7/common/mke-hw-reqs.html)
   b. Machines must use static IP requirements
   c. Machines must be configured to allow access for the ansible installation tooling, typically an ssh user with sudo access

3. Generate an [ansible inventory](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html) for use with the ansible tooling by listing the machines of the cluster, with their connection information, and including the machines in either the manager or worker group.

## Expected Results

The end result is that a cluster of running machine nodes, based on the `bootc-mke3` source, networked according to the Mirantis product requirements.

A deliverable of this process an ansible inventory file, describing the machines to be used for the `bootc-mke3` cluster with the installation tools.
