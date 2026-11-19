# Manually provision a cluster

If none of the `bootc-mke3` provisioning tools meets the needs of a `bootc-mke3` infrastructure cluster, you must provision the cluster manually. You create a number of machine node targets for an MKE cluster. The machines must be in a network that meets the documented Mirantis product needs.

Manual provisioning varies a lot. For this reason, this runbook does not give technical directives. It describes abstract concepts.

## Requirements

1. A machine installation source. Mirantis offers an installation ISO image for this purpose.

## Procedure

1. Provision a network for your `bootc-mke3` cluster
   a. that allows communication based on the [MKE networking requirements](https://docs.mirantis.com/mke/3.9/install/predeployment/configure-networking.html)
   
2. Provision a number of `bootc-mke3` machines, using the `bootc-mke3` image source
   a. Machine resource specifications that meet the [MKE minimum resource requirements](https://docs.mirantis.com/mke/3.9/common/mke-hw-reqs.html)
   b. Machines must use static IP addresses
   c. You must configure the machines to allow access for the ansible installation tools, typically an ssh user with sudo access

3. Generate an [ansible inventory](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html) for the ansible tools. List the machines of the cluster with their connection information. Put each machine in the manager group or the worker group.

## Expected Results

The result is a cluster of running machine nodes. The nodes come from the `bootc-mke3` source. The network of the nodes follows the Mirantis product requirements.

The process also delivers an ansible inventory file. The file describes the machines that the installation tools use for the `bootc-mke3` cluster.
