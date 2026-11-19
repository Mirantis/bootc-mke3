# Expel a machine from the cluster

Remove a machine from a running `bootc-mke3` cluster. Cordon it at both the
Swarm and Kubernetes layers. Move its workloads off the machine. Then remove it
from Swarm. MKE removes the Kubernetes node object itself.

This page also covers **forced expel** of a machine that is already
unreachable, where there is nothing left to drain.

You do every step as an API call with an MKE client bundle. You do not need SSH
to any machine. This procedure installs nothing in the cluster.

## Security

Expelling a machine is **destructive and not reversible from the cluster
side**. You cannot simply add a removed machine again. Its engine keeps stale
Swarm state. To clear that state, you need access to the machine itself. The
hardened `bootc-mke3` image denies this access because it disables SSH.
Before you start, plan to terminate the machine, or make sure that you have
console access.

Read [Manager count and quorum](promote-demote-machine.md#manager-count-and-quorum)
before you expel a manager. If you remove one of three managers, two remain.
This gives **zero** fault tolerance.

## Requirements

1. `kubectl` and `docker` configured from an MKE client bundle. See
   [Access the cluster](access-cluster.md).
2. An MKE administrator identity.
3. The name of the machine. Use one string for both layers, because the
   Swarm `HOSTNAME` of a machine is the same as its Kubernetes node name.
4. A decision about what happens to the machine afterwards: terminate it, or
   reset it by hand. See [After removal](#after-removal-the-machine-is-orphaned).

## Procedure

> [!WARNING]
> Never cordon a manager at the Swarm layer. `docker node update --availability
> drain` against a manager evicts the MKE components from it.

If you drain a manager, the Swarm `Status` of the machine becomes **`Down`**.
Cluster API calls through the load balancer can fail intermittently while the
load balancer still has the machine in rotation. `--availability active`
restores it.

To prevent this, demote the manager first. A *worker* that you set to `drain`
stays `Ready`. The only change is that it accepts no new tasks. The safe sequence is therefore:
**demote, then cordon, then drain, then remove**.

### 1. Identify the machine and check what it is running

```sh
docker node ls
kubectl get pods -A --field-selector spec.nodeName=<machine-name> \
  -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,OWNER:.metadata.ownerReferences[0].kind
```

Pods that a `DaemonSet` owns are not evicted, and they do not need to be.
Anything else must have another place to run.

### 2. Demote it, if it is a manager

```sh
docker node demote <machine-name>
```

Wait for the role change to finish before you continue. See
[Promote and demote machines](promote-demote-machine.md).

### 3. Cordon at both layers

Kubernetes first, then Swarm:

```sh
kubectl cordon <machine-name>
docker node update --availability drain <machine-name>
```

`kubectl cordon` sets `.spec.unschedulable` and adds the
`node.kubernetes.io/unschedulable` taint. The Swarm command blocks new tasks
and shuts down the tasks that are already there. Check the result:

```sh
kubectl get node <machine-name> -o jsonpath='{.spec.unschedulable}{"\n"}'
docker node inspect <machine-name> --format '{{.Spec.Availability}}/{{.Status.State}}'
```

A drained **worker** reads `drain/ready`. If it reads `drain/down`, the
machine is still a manager. Go back to step 2.

### 4. Drain the Kubernetes workloads

```sh
kubectl drain <machine-name> --ignore-daemonsets --delete-emptydir-data --timeout=180s
```

`--ignore-daemonsets` is mandatory. Kubernetes recreates DaemonSet pods on the node
immediately, and `drain` refuses to proceed without this flag.
`--delete-emptydir-data` is necessary for any pod that has an `emptyDir`
volume.

Make sure that only DaemonSet-owned pods remain:

```sh
kubectl get pods -A --field-selector spec.nodeName=<machine-name>
```

### 5. Remove it from Swarm

```sh
docker node rm --force <machine-name>
```

`--force` is mandatory for a machine that is still running. Without it, the
command fails. This is the exact refusal:

```text
Error response from daemon: rpc error: code = FailedPrecondition
desc = node <node-id> is not down and can't be removed
```

Use the **exit status** of the command to judge the outcome. Do not match
that text, because the error text of the daemon is not a stable interface.

### 6. Confirm the machine is gone from both layers

```sh
docker node ls
kubectl get nodes
```

MKE removes the Kubernetes node object when it reconciles the Swarm removal.
You do **not** need `kubectl delete node`.

## Expected Results

- `docker node ls` and `kubectl get nodes` both omit the machine, and
  `docker info` reports the reduced counts.
- The remaining machines are `Ready` at both layers, with one Swarm `Leader`.
- Workloads that Kubernetes evicted are `Running` on the remaining machines. We
  observed this for the System Upgrade Controller and node-feature-discovery
  deployments after an expel.
- The manager count is odd, or you plan a replacement promotion.

## Forced expel of an unreachable machine

When the machine is already gone (powered off, network-partitioned, or engine
dead), steps 3 and 4 have nothing to act on. Kubernetes reports the node as
`NotReady`.

```sh
docker node ls                      # the machine reads Down
kubectl drain <machine-name> --ignore-daemonsets --delete-emptydir-data --timeout=60s --force
docker node rm <machine-name>
```

There are two differences from the live path:

- `--force` on `docker node rm` is not necessary when Swarm already considers
  the machine `Down`. That is exactly the precondition that the refusal in
  step 5 describes. Run it without `--force` first, and let the exit status
  decide.
- `kubectl drain` needs its own `--force` to discard any pod that has no
  controller to recreate it. Otherwise, it blocks on pods that it cannot
  evict from an unreachable kubelet. Expect it to report failures. The goal
  is to free the workload names, not to shut anything down gracefully.

> This path comes from the observed preconditions of the live path
> and the Swarm removal semantics. We did not test it against a
> genuinely dead machine on a test cluster. On a three-manager cluster, such
> a test costs the Raft quorum that you need to issue the removal.

## After removal: the machine is orphaned

The machine keeps running, and its engine still holds the Swarm state that it
had before removal. We verified this after a forced removal: the instance
was still up, while the cluster no longer listed it at either layer.

Nothing in the cluster can reach it any more. On a hardened image with SSH
disabled, there is therefore no way in the cluster to clean it up. Choose one
option:

- **Terminate it.** This is the correct choice for cloud or other disposable
  machines. It is the assumption behind the AWS and vSphere provisioning
  paths.
- **Reset it from the console.** `docker swarm leave --force` on the machine
  clears the stale state. Then you can provision the machine again and join
  it again with [no-touch join](join-machines-no-touch.md).

Do not leave it running and untouched. It is a machine that holds cluster
certificates that the cluster no longer manages.

## Troubleshooting

### `node is not down and can't be removed`

The machine is still live. Do one of these: add `--force` (step 5), or, if
you have access to the machine, run `docker swarm leave` on it first and then
remove it without `--force`.

### The Kubernetes node object is still listed

Wait a few seconds for the MKE reconciler. If the node object is still
listed, make sure that the Swarm removal succeeded (`docker node ls`). MKE
removes the node object in response to the Swarm state, so a failed removal
leaves both layers unchanged.

### `kubectl drain` hangs

The cause is usually a `PodDisruptionBudget` that cannot be satisfied, or a
pod with no controller. `--timeout` limits the wait. `--force` discards pods
that have no controller. To find what blocks the drain, run
`kubectl get pods -A --field-selector spec.nodeName=<machine-name>`.

### I drained a manager by mistake and the cluster is flapping

```sh
docker node update --availability active <machine-name>
```

This restored the machine to `Ready` in testing. Demote the machine before
you drain it again.

## F.A.Q

### Can I expel several machines at once?

Expel the machines one at a time, and check cluster health between each.
The commands work on one machine at a time. The risk with a batch is quorum:
each manager removal changes the fault tolerance of the group that the next
removal depends on.

### Does this drain Swarm services as well as Kubernetes pods?

Yes. This is what `docker node update --availability drain` in step 3 does.
Swarm reschedules replicated service tasks on other machines. `global`
service tasks only stop on that machine, because global means one task for
each node.

### Why cordon at both layers when the machine is being removed anyway?

This makes the removal quiet. If you cordon first, both schedulers stop placing
new work on a machine that is about to disappear. Otherwise, this new work
would race the drain.

### Is there a controller-driven equivalent?

`machine-config-controller` is the mechanism for host-level configuration and
structured reboots. See
[machine configuration changes](machine-config-operations.md). Node lifecycle
actions are cluster-scoped API calls and not per-host changes. This is why
this runbook uses the APIs directly. An operator with a client bundle has
nothing in the cluster that a node removal can disrupt.
