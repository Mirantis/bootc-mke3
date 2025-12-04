# MKEx mixed clusters

Mirantis has performed testing, and finds no reason defects for cases where an MCR/MKE3 cluster includes both manually managed cluster and bootc-mke3 based machines.

Conceptually, Mirantis considers using mixed clusters as a transition state, for customer who intend to move to a full bootc-mke3 cluster.  There are no limitations in the mixed cluster itself, but the bootc-mke3 tooling does not accomodate the mixed state for upgrading.

Note the following limitations
1. A single MCR25 and MKE3 version must be used across the existing cluster, and the bootc-mke3 machines added must be based off of the same versions
2. bootc-mke3 cluster tooling for installation and upgrading will not be usable until a cluster contains only bootc-mke3 based machines

## Migrating to bootc-mke3 (MKEx) from a classic MCR/MKE3 cluster

Users of MCR/MKE3 who are interested in moving from their existing stack to a stack based on the bootc-mke3 framework can follow these instructions.

### Requirements

1. An existing MCR25/MKE3 cluster:
   a. The cluster should be healthy according to MKE3 (at least the control plane must be healthy)
2. Docker cli access the cluster (typically using the MKE3 client bundle, to access the swarm docker socket)
3. [Optional] kubectl access to the existing cluster (typically using the MKE3 client bundle, to access the kube API)

### Procedure

The process for transitioning from a self-managed classic MCR/MKE3 cluster to a bootc-mke3 cluster is the exact process taken to rotate any underlying machines for an MKE3 cluster.  There is not collective tooling that will perform the steps, because manual intervention and oversight is important when making this transition.

The transition follows the following phases, which refer either to runbooks mentioned below, or external documentation:

#### 1. Control/Management plane transition

* When rotating machines in the cluster, It is recommended to add a new machine, then take away an old machine - the order can be reversed if needed *
* After each operation, it is important to wait for MKE to report a healthy cluster before proceeding to the next one *
* Try to focus on maintaining a set number of managers in the MKE3 cluster as opposed to drastically changing the net number of managers, which can create election problems *

Iterate through managers, and one at a time add a new bootc-mke3 based machine to the cluster as a manager, followed by removing a manager when the cluster has stabilized.

1. Add a new manager:
   a. Provision a new bootc-mke3 machine: Runbook: [Provision a bootc-mke3 machine](https://github.com/Mirantis/mkex/blob/main/docs/runbooks/provision-manually.md)
   b. Add the new machine to the cluster: Runbook: [Add a machine to the cluster](#add-a-machine-to-the-mcrmke3-cluster)
   c. Promote the new machine to a manager: Runbook: [Promote a worker to a manager](#promote-a-worker-to-a-manager)

2. Remove a manager from the cluster
   a. Demote the manager to a worker: Runbook: [Demote a manager](#demote-a-manager-to-a-worker)
   b. Isolate the worker on the cluster: Runbook: [Isolate a worker on the cluster](#isolate-a-machine-in-the-mcrmke3-cluster)
   c. Runbook: [Remove a machine from the cluster](#remove-a-machine-from-the-mcrmke3-cluster)

#### 2. Worker plan transition

* It is recommended to add worker machines to a cluster before removing old machines, in order to maintain scheduling capacity *

Iterate through workers, and one at a time add a new bootc-mke3 based machine to the cluster as a worker, followed by removing a worker when the cluster has stabilized. It is common also to swap machine in batches, if your workload can handle the capacity disruption.

1. Add a new worker:
   a. Provision a new bootc-mke3 machine: Runbook: [Provision a bootc-mke3 machine](https://github.com/Mirantis/mkex/blob/main/docs/runbooks/provision-manually.md)
   b. Add the new machine to the cluster: Runbook: [Add a machine to the cluster](#add-a-machine-to-the-mcrmke3-cluster)

2. Remove a worker from the cluster
   a. Isolate the worker on the cluster: Runbook: [Isolate a worker on the cluster](#isolate-a-machine-in-the-mcrmke3-cluster)
   b. Runbook: [Remove a machine from the cluster](#remove-a-machine-from-the-mcrmke3-cluster)

### Supporting runbooks

#### Retrieve the Join token

Run the following docker command against the swarm cluster: 
```
docker swarm join-token worker
```
@see [https://docs.docker.com/reference/cli/docker/swarm/join-token/](https://docs.docker.com/reference/cli/docker/swarm/join-token/)

#### Determine a cluster machine ID

Run the following docker command against the swarm cluster: 
```
docker node ls
```
@see [https://docs.docker.com/reference/cli/docker/node/ls/](https://docs.docker.com/reference/cli/docker/node/ls/)

From the returned list, identify your machine by hostname, and find its ID value

#### Promote a worker to a manager

You will need the machine id: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Run the following docker command against the swarm cluster: 
```
docker node promote [machine ID]
```
@see [https://docs.docker.com/reference/cli/docker/node/promote/](https://docs.docker.com/reference/cli/docker/node/promote/)

#### Demote a manager to a worker

You will need the machine id: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Run the following docker command against the swarm cluster: 
```
docker node demote [machine ID]
```
@see [https://docs.docker.com/reference/cli/docker/node/demote/](https://docs.docker.com/reference/cli/docker/node/demote/)

#### Isolate a Machine in the MCR/MKE3 cluster

* before isolating a worker from the cluster, consider what workloads are running on the kubernetes/swarm node. If your workloads don't handle disruptions well then manually move workloads from the machine *

You will need the machine id: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Run the following kubectl commands again the kube api:
```
kubectl cordon [machine id]
kubectl drain [machine id]
```
@see [https://kubernetes.io/docs/reference/kubectl/generated/kubectl_cordon/](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_cordon/)
@see [https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/)

* this will drop all kubernetes workloads on the machine *

Run the following docker command against the swarm cluster:
```
docker node update --availability=drain [machine id]
```
@see [https://docs.docker.com/reference/cli/docker/node/update/](https://docs.docker.com/reference/cli/docker/node/update/)

* this will drop all docker swarm workloads on the machine *

#### Add a Machine to the MCR/MKE3 cluster

* In these instructions we only join machines as workers. Managers are joined as workers and then promoted *

You will need the machine id: Runbook: [Retrieve the join token](#retrieve-the-join-token)

On the machine to add, run:
```
docker swarm join --token==[worker join token]
``` 
@see [https://docs.docker.com/reference/cli/docker/swarm/join/](https://docs.docker.com/reference/cli/docker/swarm/join/)

* this will join the machine as a new worker *

#### Remove a Machine from the MCR/MKE3 cluster

You will need the machine id: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

* Run the following docker command against the swarm cluster *
```
docker node rm [machine id]
```
@see [https://docs.docker.com/reference/cli/docker/node/rm/](https://docs.docker.com/reference/cli/docker/node/rm/)

### Expected Results

After following the manager and worker operations for all machines in the cluster, the result should be the same MCR/MKE3 cluster, but now running on bootc-mke3 machines.  

There should be no significant change to the MKE3 cluster, and the same workloads should be running, as long as the workload disruption survived rotation of machines.

### FAQ

#### How long can I keep the cluster mid-transition

There are no functional issues running and standard MCR/MKE operations while the cluster is mid transition. The bootc-mke3 components in the cluster afect only the Operating System layers of the stack.

Workoads can be managed as needed, interupting the process if needed, and the transition can take as long as needed.

Note that you will not be able to perform any MCR / MKE3 upgrades until the transition is complete.
