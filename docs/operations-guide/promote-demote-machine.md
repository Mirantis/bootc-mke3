# Promote and demote machines

Change a machine's role in a running `bootc-mke3` cluster: promote a worker to
manager, or demote a manager to worker. Both are single Swarm API calls issued
from an MKE client bundle; MKE reconciles the Kubernetes side itself.

No SSH to any machine is required, and nothing is installed in the cluster to do
this.

## Requirements

1. `kubectl` and `docker` configured from an MKE client bundle — see
   [Access the cluster](access-cluster.md). Source `env.sh` from inside the
   bundle directory so `docker` talks to the cluster's Swarm endpoint.
2. An MKE administrator identity. Role changes are cluster-level operations.
3. The machine's name. A machine has **one** name across both layers: its Swarm
   `HOSTNAME` is identical to its Kubernetes node name,
   so the same string works with `docker node` and `kubectl`.

   ```sh
   docker node ls
   kubectl get nodes
   ```

### Manager count and quorum

Managers form a Raft group. A group of `N` managers tolerates the loss of
`(N-1)/2` members, so only odd counts add resilience:

| Managers | Tolerates | Note |
|---|---|---|
| 1 | 0 | No redundancy. |
| 2 | 0 | **Worse than 1** — two failure domains, still no redundancy, and losing either stops the control plane. |
| 3 | 1 | Smallest useful production count. |
| 5 | 2 | |

Consequences for these procedures:

- Never leave the cluster on an even manager count. Demoting one of three
  managers leaves two, which has **zero** fault tolerance until you promote a
  replacement.
- Promote first, demote second, when swapping a manager: the cluster passes
  through four managers rather than two.

## Procedure

### 1. Record the current roles

```sh
docker node ls --format '{{.Hostname}}\t{{.Availability}}\t{{.ManagerStatus}}'
docker info --format '{{.Swarm.Managers}} managers, {{.Swarm.Nodes}} nodes'
```

`ManagerStatus` is empty for workers, and one manager reports `Leader`.

### 2. Promote a worker to manager

```sh
docker node promote <machine-name>
```

### 3. Or demote a manager to worker

Check the resulting manager count against the table above first — and never
demote the `Leader` if you can target another manager instead, since demoting it
forces a leader election on top of the role change.

```sh
docker node demote <machine-name>
```

### 4. Wait for MKE to reconcile both layers

The Swarm call returns immediately, but MKE then converges the machine: it
installs or removes the manager-only containers and updates the Kubernetes node
object. Watch until it settles:

```sh
watch -n5 'docker node ls; kubectl get nodes'
```

## Expected Results

- `docker node ls` shows the new role — `ManagerStatus` populated for a manager,
  empty for a worker — and `docker info` reports the new manager count.
- MKE has updated the Kubernetes side **without any `kubectl` command from you**:
  a manager carries the `node-role.kubernetes.io/master` label and the
  `com.docker.ucp.manager:NoSchedule` taint; a demoted machine has both removed
  and becomes schedulable for ordinary workloads.
- On a demoted machine the manager-only containers (`ucp-controller`, `ucp-kv`,
  `ucp-auth-api`) are gone while the worker-side agents keep running — verified
  by inspecting the machine's own engine after a demotion.
- `docker node ls` reports every machine `Ready`, and no machine sits in `Down`.

## Troubleshooting

### The machine shows `Down` immediately after promotion

Expected transiently. Promotion restarts MKE components on the machine, and it
reports `Down` in Swarm for a few seconds in the middle of that. It should reach
`Ready` well inside a minute; measured ~30s. If it is still `Down` after a few
minutes, treat it as a node problem rather than a role problem: inspect the
machine's engine and its MKE containers rather than re-issuing the role change.

### Demotion appears to do nothing at the Kubernetes layer

MKE owns that side. The `node-role.kubernetes.io/master` label and
`com.docker.ucp.manager` taint are applied and removed by MKE's node
reconciler, not by the Swarm call, so they change a few seconds later than the
Swarm role. Do not add or remove them by hand — MKE will revert the change.

### I need to know which manager is the leader

```sh
docker node ls --filter role=manager --format '{{.Hostname}} {{.ManagerStatus}}'
```

## F.A.Q

### Why `docker node promote` rather than a Kubernetes resource?

Manager membership is Swarm state — Raft group membership — and MKE derives the
Kubernetes control-plane role from it. There is no Kubernetes object that
expresses "this machine is a manager", so the Swarm API is the authoritative
interface, and MKE reconciles Kubernetes to match.

### Can I run this against a worker's own engine?

No. Role changes require the Swarm manager API, which only managers serve. The
client bundle points at the cluster's manager endpoint, so this is only a
constraint if you bypass the bundle and talk to a machine's engine directly.

### Does promotion need the machine to be drained first?

No. Promotion and demotion are independent of scheduling availability. If you
are removing the machine afterwards, see
[Expel a machine from the cluster](expel-machine.md), which demotes first for a
different reason: draining a manager is disruptive.

### How do I replace a manager?

Promote the replacement, confirm the new manager is `Ready` and the count is
odd, then demote and expel the old one — in that order, so the cluster never
drops below the fault tolerance you started with.
