# Expel a machine from the cluster

Remove a machine from a running `bootc-mke3` cluster: cordon it at both the
Swarm and Kubernetes layers, move its workloads off, then remove it from Swarm.
MKE removes the Kubernetes node object itself.

Also covers **forced expel** of a machine that is already unreachable, where
there is nothing left to drain.

Every step is an API call from an MKE client bundle. No SSH to any machine is
required, and nothing is installed in the cluster to do this.

## Security

Expelling a machine is **destructive and not reversible from the cluster side**.
A removed machine cannot simply be added back: its engine keeps stale Swarm
state, and clearing that requires access to the machine itself, which the
hardened `bootc-mke3` image denies by disabling SSH. Plan on terminating the
machine, or on having console access, before you start.

Read [Manager count and quorum](promote-demote-machine.md#manager-count-and-quorum)
before expelling a manager. Removing one of three managers leaves two, which has
**zero** fault tolerance.

## Requirements

1. `kubectl` and `docker` configured from an MKE client bundle — see
   [Access the cluster](access-cluster.md).
2. An MKE administrator identity.
3. The machine's name — one string serves both layers, since a machine's Swarm
   `HOSTNAME` is identical to its Kubernetes node name.
4. A decision about the machine's fate afterwards: terminate it, or reset it by
   hand. See [After removal](#after-removal-the-machine-is-orphaned).

## Procedure

> [!WARNING]
> Never cordon a manager at the Swarm layer. `docker node update --availability
> drain` against a manager evicts MKE's own components from it.

Draining a manager sets the machine's Swarm `Status` to **`Down`**, and cluster
API calls through the load balancer can fail intermittently while the load
balancer still has the machine in rotation. Setting `--availability active`
restores it.

Demoting first avoids this entirely — a *worker* set to `drain` stays `Ready`
and simply stops accepting tasks. So the safe sequence is **demote, then
cordon, then drain, then remove**.

### 1. Identify the machine and check what it is running

```sh
docker node ls
kubectl get pods -A --field-selector spec.nodeName=<machine-name> \
  -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,OWNER:.metadata.ownerReferences[0].kind
```

Pods owned by a `DaemonSet` will not be evicted and do not need to be; anything
else must have somewhere else to run.

### 2. Demote it, if it is a manager

```sh
docker node demote <machine-name>
```

Wait for the role change to settle before continuing — see
[Promote and demote machines](promote-demote-machine.md).

### 3. Cordon at both layers

Kubernetes first, then Swarm:

```sh
kubectl cordon <machine-name>
docker node update --availability drain <machine-name>
```

`kubectl cordon` sets `.spec.unschedulable` and adds the
`node.kubernetes.io/unschedulable` taint. The Swarm call stops new tasks and
shuts down tasks already there. Confirm:

```sh
kubectl get node <machine-name> -o jsonpath='{.spec.unschedulable}{"\n"}'
docker node inspect <machine-name> --format '{{.Spec.Availability}}/{{.Status.State}}'
```

A drained **worker** reads `drain/ready`. If it reads `drain/down`, the machine
is still a manager — go back to step 2.

### 4. Drain the Kubernetes workloads

```sh
kubectl drain <machine-name> --ignore-daemonsets --delete-emptydir-data --timeout=180s
```

`--ignore-daemonsets` is required, not optional: DaemonSet pods are recreated on
the node immediately and `drain` refuses to proceed without it.
`--delete-emptydir-data` is needed for any pod carrying an `emptyDir` volume.

Confirm only DaemonSet-owned pods remain:

```sh
kubectl get pods -A --field-selector spec.nodeName=<machine-name>
```

### 5. Remove it from Swarm

```sh
docker node rm --force <machine-name>
```

`--force` is required for a machine that is still running. Without it the call
fails, and this is the exact refusal:

```text
Error response from daemon: rpc error: code = FailedPrecondition
desc = node <node-id> is not down and can't be removed
```

Judge the outcome by the command's **exit status**, not by matching that text —
daemon error prose is not a stable interface.

### 6. Confirm the machine is gone from both layers

```sh
docker node ls
kubectl get nodes
```

MKE removes the Kubernetes node object as part of reconciling the Swarm
removal. You do **not** need `kubectl delete node`.

## Expected Results

- `docker node ls` and `kubectl get nodes` both omit the machine, and
  `docker info` reports the reduced counts.
- The remaining machines are `Ready` at both layers, with one Swarm `Leader`.
- Workloads that were evicted are `Running` on the remaining machines —
  observed for the System Upgrade Controller and node-feature-discovery
  deployments after an expel.
- The manager count is odd, or you have a replacement promotion planned.

## Forced expel of an unreachable machine

When the machine is already gone — powered off, network-partitioned, engine
dead — steps 3 and 4 have nothing to act on, and Kubernetes will report the node
`NotReady`.

```sh
docker node ls                      # the machine reads Down
kubectl drain <machine-name> --ignore-daemonsets --delete-emptydir-data --timeout=60s --force
docker node rm <machine-name>
```

Two differences from the live path:

- `--force` on `docker node rm` is unnecessary once Swarm already considers the
  machine `Down`; that is precisely the precondition the refusal in step 5 is
  about. Run it without `--force` first and let the exit status decide.
- `kubectl drain` needs `--force` of its own to discard any pod that has no
  controller to recreate it, and will otherwise block on pods it cannot evict
  from an unreachable kubelet. Expect it to report failures; the goal is to free
  the workload names, not to shut anything down gracefully.

> This path is documented from the live path's observed preconditions plus Swarm
> removal semantics. It has not been exercised against a genuinely dead machine
> on a test cluster, because doing so on a three-manager cluster costs the Raft
> quorum needed to issue the removal.

## After removal: the machine is orphaned

The machine keeps running, and its engine still holds the Swarm state it had
before removal — verified after a forced removal: the instance was still up,
while the cluster no longer listed it at either layer.

Nothing in the cluster can reach it any more, so on a hardened image with SSH
disabled there is no in-cluster way to clean it up. Choose one:

- **Terminate it.** The right answer for cloud or otherwise disposable machines,
  and the assumption behind the AWS and vSphere provisioning paths.
- **Reset it from the console.** `docker swarm leave --force` on the machine
  clears the stale state, after which it can be re-provisioned and rejoined with
  [no-touch join](join-machines-no-touch.md).

Do not leave it running and untouched: it is a machine holding cluster
certificates that the cluster no longer manages.

## Troubleshooting

### `node is not down and can't be removed`

The machine is still live. Either add `--force` (step 5) or, if you have access
to it, `docker swarm leave` on the machine first and then remove it without
`--force`.

### The Kubernetes node object is still listed

Give MKE's reconciler a few seconds. If it persists, check that the Swarm
removal actually succeeded (`docker node ls`); MKE removes the node object in
response to the Swarm state, so a failed removal leaves both layers unchanged.

### `kubectl drain` hangs

Usually a `PodDisruptionBudget` that cannot be satisfied, or a pod with no
controller. `--timeout` bounds the wait; `--force` discards uncontrolled pods.
Check what is blocking with
`kubectl get pods -A --field-selector spec.nodeName=<machine-name>`.

### I drained a manager by mistake and the cluster is flapping

```sh
docker node update --availability active <machine-name>
```

That restored the machine to `Ready` in testing. Then demote it before draining
again.

## F.A.Q

### Can I expel several machines at once?

Do them one at a time, confirming cluster health between each. The commands are
per-machine, and the risk with a batch is quorum: each manager removal changes
the fault tolerance of the group the next removal depends on.

### Does this drain Swarm services as well as Kubernetes pods?

Yes — that is what step 3's `docker node update --availability drain` does.
Swarm reschedules replicated service tasks elsewhere; `global` service tasks
simply stop on that machine, since global means one task per node.

### Why cordon at both layers when the machine is being removed anyway?

So the removal is quiet. Cordoning first stops both schedulers from placing new
work on a machine that is about to disappear, which would otherwise race the
drain.

### Is there a controller-driven equivalent?

`machine-config-controller` is the mechanism for host-level configuration and
structured reboots — see
[machine configuration changes](machine-config-operations.md). Node lifecycle
actions are cluster-scoped API calls rather than per-host changes, which is why
this runbook uses the APIs directly: an operator with a client bundle has
nothing in-cluster that a node removal can disrupt.
