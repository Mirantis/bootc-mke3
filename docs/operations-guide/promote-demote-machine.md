# Promote and demote machines

Change the role of a machine in a running `bootc-mke3` cluster: promote a
worker to manager, or demote a manager to worker. Each change is one Swarm API
call that you send from an MKE client bundle. MKE reconciles the Kubernetes
side itself.

You do not need SSH to any machine. You do not install anything in the cluster.

## Requirements

1. `kubectl` and `docker` configured from an MKE client bundle. See
   [Access the cluster](access-cluster.md). Source `env.sh` from inside the
   bundle directory, so that `docker` communicates with the Swarm endpoint of
   the cluster.
2. An MKE administrator identity. Role changes are cluster-level operations.
3. The name of the machine. A machine has **one** name across both layers. Its
   Swarm `HOSTNAME` is identical to its Kubernetes node name. The same string
   works with `docker node` and `kubectl`.

   ```sh
   docker node ls
   kubectl get nodes
   ```

### Manager count and quorum

Managers form a Raft group. A group of `N` managers tolerates the loss of
`(N-1)/2` members. Therefore only odd counts add resilience:

| Managers | Tolerates | Note |
|---|---|---|
| 1 | 0 | No redundancy. |
| 2 | 0 | **Worse than 1**. Two failure domains give no redundancy, and the loss of either stops the control plane. |
| 3 | 1 | Smallest useful production count. |
| 5 | 2 | |

Consequences for these procedures:

- Never leave the cluster with an even number of managers. If you demote one
  of three managers, two remain. Two managers have **zero** fault tolerance
  until you promote a replacement.
- When you swap a manager, promote first and demote second. Then the cluster
  has four managers during the swap, not two.

## Procedure

### 1. Record the current roles

```sh
docker node ls --format '{{.Hostname}}\t{{.Availability}}\t{{.ManagerStatus}}'
docker info --format '{{.Swarm.Managers}} managers, {{.Swarm.Nodes}} nodes'
```

`ManagerStatus` is empty for workers. One manager reports `Leader`.

### 2. Promote a worker to manager

```sh
docker node promote <machine-name>
```

### 3. Or demote a manager to worker

First compare the resulting manager count with the table above. If you can
target another manager, do not demote the `Leader`. A demotion of the leader
forces a leader election in addition to the role change.

```sh
docker node demote <machine-name>
```

### 4. Wait for MKE to reconcile both layers

The Swarm call returns immediately. Then MKE converges the machine. It
installs or removes the manager-only containers and updates the Kubernetes node
object. Watch until the state is stable:

```sh
watch -n5 'docker node ls; kubectl get nodes'
```

## Expected Results

- `docker node ls` shows the new role: `ManagerStatus` has a value for a
  manager and is empty for a worker. `docker info` reports the new manager count.
- MKE updates the Kubernetes side **without any `kubectl` command from
  you**. A manager has the `node-role.kubernetes.io/master` label and the
  `com.docker.ucp.manager:NoSchedule` taint. A demoted machine has no label and
  no taint, and it can run ordinary workloads.
- On a demoted machine, the manager-only containers (`ucp-controller`,
  `ucp-kv`, `ucp-auth-api`) are gone. The worker-side agents keep running. We
  verified this by inspection of the engine of the machine after a demotion.
- `docker node ls` reports every machine as `Ready`, and no machine is `Down`.

## Troubleshooting

### The machine shows `Down` immediately after promotion

This is normal for a short time. Promotion restarts MKE components on the
machine, and the machine shows `Down` in Swarm for a few seconds during the
restart. We expect it to reach `Ready` well inside a minute (measured: about
30 seconds). If it is still `Down` after a few minutes, treat it as a node
problem and not a role problem. Inspect the engine of the machine and its MKE
containers. Do not issue the role change again.

### Demotion appears to do nothing at the Kubernetes layer

MKE owns that side. The node reconciler of MKE, not the Swarm call, applies
and removes the `node-role.kubernetes.io/master` label and the
`com.docker.ucp.manager` taint. Therefore they change a few seconds after the
Swarm role. Do not add or remove them by hand. MKE reverts the change.

### I need to know which manager is the leader

```sh
docker node ls --filter role=manager --format '{{.Hostname}} {{.ManagerStatus}}'
```

## F.A.Q

### Why `docker node promote` rather than a Kubernetes resource?

Manager membership is Swarm state (Raft group membership), and MKE derives the
Kubernetes control-plane role from it. No Kubernetes object expresses "this
machine is a manager". Therefore the Swarm API is the authoritative interface,
and MKE reconciles Kubernetes to match.

### Can I run this against a worker's own engine?

No. Role changes need the Swarm manager API, which only managers serve. The
client bundle points to the manager endpoint of the cluster. This is a
constraint only if you bypass the bundle and communicate directly with the
engine of a machine.

### Does promotion need the machine to be drained first?

No. Promotion and demotion do not depend on scheduling availability. If you
remove the machine afterward, see
[Expel a machine from the cluster](expel-machine.md). That runbook demotes
first for a different reason: a drain of a manager is disruptive.

### How do I replace a manager?

Promote the replacement. Make sure that the new manager is `Ready` and that
the count is odd. Then demote the old manager and expel it. Do these steps in
this order, so that the cluster never has less fault tolerance than it had at
the start.
