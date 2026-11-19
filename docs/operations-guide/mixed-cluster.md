# bootc-mke3 mixed clusters

Mirantis tested a cluster that includes both manually managed machines and bootc-mke3 based machines in an MCR/MKE3 cluster. Mirantis found no defects.

Mirantis considers a mixed cluster to be a transition state for customers who intend to move to a full bootc-mke3 cluster. The mixed cluster itself has no limitations. However, the bootc-mke3 tooling does not support the upgrade of a mixed cluster.

Obey these limitations:
1. You must use a single MCR and MKE3 version across the existing cluster. The bootc-mke3 machines that you add must be based on the same versions.
2. You cannot use the bootc-mke3 cluster tooling for installation and upgrade until the cluster contains only bootc-mke3 based machines.

The manual SSH-based docker swarm join/promote/demote workflow below is for only the classic-to-bootc migration scenario. In this scenario, you have direct docker CLI access to an existing classic cluster. To add new bootc-mke3 machines to a cluster that is already fully bootc-mke3, use the standard no-touch join mechanism: [Join machines with no-touch](join-machines-no-touch.md).

## Migrating to bootc-mke3 from a classic MCR/MKE3 cluster

Users of MCR/MKE3 who want to move from their existing stack to a stack based on the bootc-mke3 framework can use these instructions.

### Requirements

1. An existing MCR/MKE3 cluster:
   a. It is best if the cluster is healthy according to MKE3. At least the control plane must be healthy.
2. Docker CLI access to the cluster (typically with the MKE3 client bundle, to access the swarm docker socket). See the [cluster access runbook](access-cluster.md).
3. [Optional] kubectl access to the existing cluster (typically with the MKE3 client bundle, to access the kube API). See the [cluster access runbook](access-cluster.md).
4. Read access to the registry that hosts the `bootc-mke3` OCI images for the new machines. See [registry requirements](../installation-guide/provisioning.md#registry).

### Procedure

You transition from a self-managed classic MCR/MKE3 cluster to a bootc-mke3 cluster with this process. It is the exact process that you use to replace any underlying machines of an MKE3 cluster. No single tool does the steps, because manual intervention and oversight are important in this transition.

The transition has these phases. Each phase refers to the runbooks below or to external documentation:

#### 1. Control/Management plane transition

> [!NOTE]
> When you replace machines in the cluster, we recommend that you add a new machine and then remove an old machine. You can reverse the order if it is necessary.

> [!WARNING]
> After each operation, wait for MKE to report a healthy cluster before you do the next operation.

> [!WARNING]
> We recommend that you keep a constant number of managers in the MKE3 cluster. Large changes to the net number of managers can cause election problems.

Do these steps for each manager, one manager at a time. Add a new bootc-mke3 based machine to the cluster as a manager. When the cluster is stable, remove a manager.

1. Add a new manager:
   a. Provision a new bootc-mke3 machine: Runbook: [Provision a bootc-mke3 machine](../installation-guide/provision-manually.md)
   b. Add the new machine to the cluster: Runbook: [Add a machine to the cluster](#add-a-machine-to-the-mcrmke3-cluster)
   c. Promote the new machine to a manager: Runbook: [Promote a worker to a manager](#promote-a-worker-to-a-manager)

2. Remove a manager from the cluster:
   a. Demote the manager to a worker: Runbook: [Demote a manager](#demote-a-manager-to-a-worker)
   b. Isolate the worker on the cluster: Runbook: [Isolate a worker on the cluster](#isolate-a-machine-in-the-mcrmke3-cluster)
   c. Remove the machine from the cluster: Runbook: [Remove a machine from the cluster](#remove-a-machine-from-the-mcrmke3-cluster)

#### 2. Worker plane transition

> [!NOTE]
> We recommend that you add worker machines to a cluster before you remove old machines. This keeps the scheduling capacity.

Do these steps for each worker, one worker at a time. Add a new bootc-mke3 based machine to the cluster as a worker. When the cluster is stable, remove a worker. It is common to replace machines in batches if your workload can accept the capacity disruption.

1. Add a new worker:
   a. Provision a new bootc-mke3 machine: Runbook: [Provision a bootc-mke3 machine](../installation-guide/provision-manually.md)
   b. Add the new machine to the cluster: Runbook: [Add a machine to the cluster](#add-a-machine-to-the-mcrmke3-cluster)

2. Remove a worker from the cluster:
   a. Isolate the worker on the cluster: Runbook: [Isolate a worker on the cluster](#isolate-a-machine-in-the-mcrmke3-cluster)
   b. Remove the machine from the cluster: Runbook: [Remove a machine from the cluster](#remove-a-machine-from-the-mcrmke3-cluster)

### Supporting runbooks

#### Retrieve the Join token

Run the following docker command against the swarm cluster: 
```
docker swarm join-token worker
```
See the [docker swarm join-token reference](https://docs.docker.com/reference/cli/docker/swarm/join-token/).

#### Determine a cluster machine ID

Run the following docker command against the swarm cluster: 
```
docker node ls
```
See the [docker node ls reference](https://docs.docker.com/reference/cli/docker/node/ls/).

From the returned list, identify your machine by hostname and find its ID value.

#### Promote a worker to a manager

You need the machine ID: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Run the following docker command against the swarm cluster: 
```
docker node promote [machine ID]
```
See the [docker node promote reference](https://docs.docker.com/reference/cli/docker/node/promote/).

#### Demote a manager to a worker

You need the machine ID: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Run the following docker command against the swarm cluster: 
```
docker node demote [machine ID]
```
See the [docker node demote reference](https://docs.docker.com/reference/cli/docker/node/demote/).

#### Isolate a Machine in the MCR/MKE3 cluster

> [!WARNING]
> Before you isolate a worker from the cluster, check which workloads run on the kubernetes/swarm node. If your workloads do not tolerate disruptions, manually move the workloads away from the machine.

You need the machine ID: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

Note: these kubectl commands need the Kubernetes node NAME (from `kubectl get nodes`). The NAME is typically the same as the machine hostname. The NAME is NOT the docker node ID from the swarm lookup above. Do not confuse the two.

Run the following kubectl commands against the kube api:
```
kubectl cordon [kubernetes node name]
kubectl drain [kubernetes node name]
```
See the [kubectl cordon reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_cordon/).
See the [kubectl drain reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/).

> [!WARNING]
> This command removes all kubernetes workloads from the machine.

Run the following docker command against the swarm cluster:
```
docker node update --availability=drain [machine id]
```
See the [docker node update reference](https://docs.docker.com/reference/cli/docker/node/update/).

> [!WARNING]
> This command removes all docker swarm workloads from the machine.

#### Add a Machine to the MCR/MKE3 cluster

> [!NOTE]
> In these instructions, you join machines only as workers. To add a manager, join it as a worker and then promote it.

You need the join token: Runbook: [Retrieve the join token](#retrieve-the-join-token)

On the machine to add, run:
```
docker swarm join --token [worker join token] [manager-host]:2377
``` 
See the [docker swarm join reference](https://docs.docker.com/reference/cli/docker/swarm/join/).

Note: `[manager-host]` is the address of an existing manager. To retrieve the address, run `docker info --format '{{.Swarm.NodeAddr}}'` on a manager. On some Docker versions, the output of the join-token command also shows the address.

> [!NOTE]
> This command joins the machine as a new worker.

#### Remove a Machine from the MCR/MKE3 cluster

You need the machine ID: Runbook: [Determine a cluster machine ID](#determine-a-cluster-machine-id)

> [!NOTE]
> Run the following docker command against the swarm cluster.

```
docker node rm [machine id]
```
See the [docker node rm reference](https://docs.docker.com/reference/cli/docker/node/rm/).

### Expected Results

After you do the manager and worker operations for all machines in the cluster, the result is the same MCR/MKE3 cluster. The cluster now runs on bootc-mke3 machines.

The MKE3 cluster has no significant change. The same workloads run, if the workloads tolerated the replacement of the machines.

### FAQ

#### How long can I keep the cluster mid-transition

The cluster has no functional issues with standard MCR/MKE operations while it is in mid-transition. The bootc-mke3 components in the cluster affect only the operating system layers of the stack.

You can manage workloads as necessary. You can interrupt the process if it is necessary. The transition can take as long as necessary.

Note that you cannot do any MCR/MKE3 upgrades until the transition is complete.
