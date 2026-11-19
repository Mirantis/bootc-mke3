# Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)

This is the **canonical** way to upgrade an existing `bootc-mke3` cluster.
Apply a kube-native `ClusterUpgrade` custom resource. The
`cluster-upgrade-controller` that the install puts on the cluster by default
handles the resource. You do not need SSH or an Ansible inventory. You need
only `kubectl` access through the [client bundle](access-cluster.md).

> [!NOTE]
> A manual, Ansible-driven exception path exists for clusters where
> `cluster-upgrade-controller` is unavailable or disabled. See the
> [Ansible upgrade runbook](upgrade-with-ansible.md). Both paths run the
> same underlying `mirantis/ucp upgrade` checks and commands.

## Prerequisites

1. `cluster-upgrade-controller` runs in the cluster. A standard
   [install](../installation-guide/install-bootc-mke3.md) installs it by
   default.
2. A [client bundle](access-cluster.md) with `kubectl` configured against the
   cluster (`export KUBECONFIG=<bundle>/kube.yml`). This path does not need
   SSH to cluster machines.
3. The manager(s) must be able to reach the workers on the full
   `mke_worker_internal`/`mke_worker_self` port sets. See the [port
   requirements](join-machines-no-touch.md#port-requirements) table for the
   complete list. The complete list has more ports than the minimum ports
   for [no-touch join](join-machines-no-touch.md). `mke3-verify-environment`
   probes the full set from the control plane to every worker. If the
   network layer blocks any of the ports (for example a security group or a
   firewall between subnets), the step fails. The failure names the blocked
   ports and nodes. This is true even if the OS firewall of the workers
   allows the ports.
4. Read access to the target bootc OS image and the MKE upgrade image that
   this runbook references below (see
   [registry requirements](../installation-guide/provisioning.md#registry)).

## Procedure

### 1. Confirm the cluster is ready to upgrade

After you apply the CR, the controller upgrades every node without
supervision. A cluster that is already degraded, or that has state from a
previous upgrade, fails part-way through. Do these checks first. Each check
names the action to do when the check does not pass.

**Kubernetes.** Make sure that every node is `Ready` and that no node reports
a pressure condition:

```sh
kubectl get nodes
kubectl get nodes -o json | jq -r '.items[] | .metadata.name as $n
  | .status.conditions[] | select(.type!="Ready" and .status=="True")
  | "\($n) \(.type)"'
```

The second command prints nothing on a healthy cluster. Each `MemoryPressure`,
`DiskPressure` or `PIDPressure` row names a node that you must clear before
you upgrade. The upgrade pulls images and writes a new OS deployment on every
node, and both need disk space.

Make sure that no workload is stuck or failing. The phase alone is not
enough. A pod whose container is in `CrashLoopBackOff`, or fails its
readiness probe, stays in phase `Running`. Therefore check both:

```sh
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get pods -A -o json | jq -r '.items[]
  | select([.status.containerStatuses[]? | select(.ready == false)] | length > 0)
  | "\(.metadata.namespace)/\(.metadata.name)"'
```

The first command lists pods that never reached `Running`. The second
command lists running pods that have a container that is not ready. A
crash-looping workload shows in the second list. Investigate each pod that
either command prints. A pod that is already `Pending` because of a lack of
capacity does not schedule more easily while the nodes drain in sequence.

**Custom resource definitions.** Both CRDs that the upgrade uses must be
present and `Established`. They must also serve the API versions that the CR
and the controller use:

```sh
kubectl get crd clusterupgrades.upgrade.mirantis.com plans.upgrade.cattle.io \
  -o custom-columns=\
'NAME:.metadata.name,ESTABLISHED:.status.conditions[?(@.type=="Established")].status,SERVED:.spec.versions[?(@.served==true)].name'
```

Both rows must read `True`. The `SERVED` column of
`clusterupgrades.upgrade.mirantis.com` must list the `apiVersion` that the CR
uses in step 3 (`v1alpha1`). The column filters on `served: true` on
purpose. The API server rejects a version that is in the CRD but not served.
If the command listed every version, it could pass this check and the
`kubectl apply` could still fail. A missing CRD means that nobody installed the relevant
controller or that someone removed it. In that case, `kubectl apply -f`
of the CR fails with `no matches for kind`. `Established=False` means that
the API server did not yet accept the definition. Check again before you
continue.

**cluster-upgrade-controller.** Make sure that the Deployment is available:

```sh
kubectl -n mke get deploy cluster-upgrade-controller
```

`READY` must read `1/1`. A `CrashLoopBackOff` or a pod that restarts again
and again means that the controller cannot reconcile the CR that you are
about to create. Before you continue, diagnose with
`kubectl -n mke logs deploy/cluster-upgrade-controller`.

Make sure that no upgrade is in progress or left behind:

```sh
kubectl get clusterupgrades
```

Each CR in a non-terminal phase must reach a terminal phase first.
`Upgrading` and `RollingBack` both actively change nodes. You must resolve a
CR that is in `Failed` or `RollbackFailed` before you create a new CR. See
[Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) for the phase
model (`Failed` → `RollingBack` → `RolledBack` or `RollbackFailed`) and for
the requirements of `RollbackFailed`. `Completed` and `RolledBack` are
terminal and do not block a new upgrade.

**system-upgrade-controller.** This controller runs the per-node work. The
upgrade cannot continue without it:

```sh
kubectl -n system-upgrade get deploy system-upgrade-controller
kubectl -n system-upgrade get plans,jobs
```

The deployment must read `1/1`. We expect the second command to return
`No resources found` on a cluster with no upgrade history. A remaining `Plan`
runs again on nodes that join later. A `Job` that is still running or in
error is a previous upgrade that did not finish. The TTL of SUC
(`SYSTEM_UPGRADE_JOB_TTL_SECONDS_AFTER_FINISH`, 900s) removes completed
jobs. Therefore each older job is residue. We recommend that you clear it.

Do not extend this command to `pods`. The `system-upgrade` namespace also
holds the `system-upgrade-controller` and `machine-config-controller` pods.
We expect these pods to be `Running`. They are not upgrade residue.

**MKE and Swarm.** Make sure that the expected number of machines is present
and that the manager quorum is intact:

```sh
kubectl get nodes -l node-role.kubernetes.io/master
(cd <bundle-dir> && source env.sh && docker node ls)
```

`docker node ls` needs the Docker environment of the client bundle, not only
`KUBECONFIG`. If you do not source `env.sh` from inside the bundle directory,
the command uses the local Docker daemon, not the cluster.

The manager count must be odd and every manager must be reachable. If a
manager is already down when you upgrade, no quorum margin remains when the
next manager reboots. `docker node ls` can report a worker as `Down` while
`kubectl get nodes` shows it as `Ready`. Run `docker node inspect <node>`
before you dismiss it. The only known benign case is the `"Node not yet found
in classic node inventory"` message that the [no-touch
join](join-machines-no-touch.md) page describes. Any other reason is a real problem. Resolve
it first.

### 2. Verify target image access

Before you apply the CR, make sure that you can pull the target
`mirantis/ucp:<version>` upgrade image. If you set `spec.os.image`, make sure
that you can also pull the target bootc OS image. The pull must work from the
location where the nodes of the cluster read images. See
[registry requirements](../installation-guide/provisioning.md#registry).
`cluster-upgrade-controller` uses its own image to run the `mke3-upgrade`
step. There is no separate `spec.product.mke3.image` field to configure.

On an air-gapped cluster, also make sure that
`SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` in `system-upgrade/default-controller-env`
is not `Always`. Images from builds before 2026-10-29 set it to
`Always`. With this value, SUC creates the Job of every step with
`imagePullPolicy: Always`. The kubelet then goes to the registry, even for
images that are already on the node. See
[Older images: SUC Job pull policy](../installation-guide/airgap-bootc-mke3.md#older-images-suc-job-pull-policy).

If you set `spec.os.image`, check its cosign signature before you apply the
CR. See
[Verify bootc-mke3 image signatures](verify-image-signatures.md#at-installswitch-time).

### 3. Apply the `ClusterUpgrade` CR

```yaml
apiVersion: upgrade.mirantis.com/v1alpha1
kind: ClusterUpgrade
metadata:
  name: <upgrade-name>
spec:
  os:
    type: bootc
    image: <target bootc OCI ref>              # switches OS + MCR together
  product:
    type: mke3
    version: "<target MKE version>"
    mke3:
      upgradeFlags: ["--force-minimums"]
      backupDir: <backup-dir>
      controllersUpgrade:
        enabled: true                          # see callout below before omitting this
  controlPlaneConcurrency: 1
  workerConcurrency: <N>
```

- `spec.os` is optional. To upgrade only the MKE product and keep the
  OS/MCR version the same, omit it.
- `backupDir` is optional. The CRD sets the default to `/var/lib/mke-backup`.
- `controlPlaneConcurrency` and `workerConcurrency` set the maximum number
  of nodes of each role that the controller drives through the upgrade steps
  at the same time. The controller always upgrades the manager nodes one
  after the other before the workers start. The workers proceed in batches
  of `workerConcurrency`.
- `controllersUpgrade.enabled` controls a sixth, final step,
  `mke3-controllers-upgrade`. This step applies the System Upgrade
  Controller, `machine-config-controller`, and `cluster-upgrade-controller`
  manifests again. The target OS image contains these manifests. **The CRD
  sets the default to `false`, by design.** The step replaces cluster-wide
  CRDs, RBAC and Deployments, including those of
  `cluster-upgrade-controller` itself.
  Therefore you must opt in for each upgrade. A CR does not get this step
  implicitly.

  > [!NOTE]
  > **If the field is unset, the step does not upgrade the controllers and
  > nothing records that.** `.status.phase` reaches `Completed`, no condition
  > appears, and no log line reports a skipped step. The only signal
  > is that `MKE3ControllersUpgraded` is absent from `.status.conditions`.
  > The target OS image stages newer SUC/`machine-config-controller`/
  > `cluster-upgrade-controller` manifests on disk
  > (`/usr/share/mke-controllers/manifests`). If the field is unset, the
  > upgrade applies none of the manifests. The cluster keeps the versions from
  > its *install*, across any number of later OS or product upgrades,
  > until an upgrade sets the field.
  >
  > **Set the field to `true`** when you want the platform controllers to
  > follow the OS image. This is the normal case when you installed the
  > controllers from these images and do not manage them
  > elsewhere. **Leave the field unset or `false`** in these cases:
  >
  > - You manage any of the three controllers out-of-band (for example with
  >   a separate Helm release).
  > - You need the product upgrade and the controller upgrade in separate
  >   change windows.
  > - You want to keep a known-good controller version across a product
  >   upgrade.
  >
  > The field needs `cluster-upgrade-controller` `v0.1.9-tp1`/`v0.2.0` or
  > later. It does not exist in earlier CRDs. Immediately after you apply
  > the CR, check that the API server accepted the CR. Do not wait for the complete
  > upgrade:
  > ```sh
  > kubectl get clusterupgrade <name> \
  >   -o jsonpath='{.spec.product.mke3.controllersUpgrade.enabled}'   # must print: true
  > ```
  > If the command prints nothing, the `cluster-upgrade-controller` before
  > the upgrade is too old for this field. In that case, upgrade the three
  > controllers by hand after the product upgrade. Use the manifests that
  > the new OS image staged on each node.
  >
  > These manifests are at `/usr/share/mke-controllers/manifests` **on the
  > nodes**, not on your workstation. `kubectl apply -f` reads the file
  > system of the client. If you point it at that path, it fails with a
  > missing-path error. First copy the manifests from a node. This does not
  > need SSH (managers revoke SSH after install). `kubectl debug node` runs
  > a pod with the host file system mounted at `/host`. You must set
  > `--attach=true`. Without it, the command returns no output.
  >
  > **Prerequisite.** `DEBUG_IMAGE` has no default. You must set it
  > explicitly. Before this procedure starts, the image must be on the node
  > or the cluster must be able to pull it. The image must contain both a
  > shell and `chroot`. A distroless image has neither and does not work. On
  > a cluster with public registry access, `busybox` is sufficient. CI uses
  > `busybox`. **On an air-gapped cluster, the cluster cannot pull `busybox`.** The
  > debug pod stays in `ImagePullBackOff` before you copy any manifest.
  >
  > On an air-gapped cluster, use the image of `cluster-upgrade-controller`
  > itself. It has `/bin/sh` and `/usr/sbin/chroot`.
  > The node that runs the controller already pulled it. This procedure
  > exists because that controller runs an older version than the version
  > that the target OS image stages on disk. Therefore its image is present on that node.
  > This is true **on the node that runs the controller, not on every
  > master**. Select the node from the pod of the controller. Do not take the
  > first master in the list. On a multi-manager cluster these are usually
  > different nodes. A master that never ran the controller can be unable to
  > pull the image.
  >
  > Read both the image reference and the node from the running Deployment.
  > Then this document does not hardcode a version or a label that can become outdated:
  > ```sh
  > cuc_debug_env() {
  >   local selector pod
  >   unset CUC_DEBUG_READY CUC_MANIFESTS_FRESH NODE DEBUG_IMAGE
  >   selector=$(kubectl -n mke get deploy cluster-upgrade-controller \
  >     -o go-template='{{range $k, $v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}') || return 1
  >   selector=${selector%,}
  >   [ -n "$selector" ] || { echo "no selector on the cluster-upgrade-controller Deployment" >&2; return 1; }
  >   pod=$(kubectl -n mke get pod -l "$selector" \
  >     --field-selector=status.phase=Running \
  >     -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status' \
  >     --no-headers | awk '$2 == "True" {print $1; exit}')
  >   [ -n "$pod" ] || { echo "no Running and Ready cluster-upgrade-controller pod found" >&2; return 1; }
  >   NODE=$(kubectl -n mke get pod "$pod" -o jsonpath='{.spec.nodeName}')
  >   [ -n "$NODE" ] || { echo "could not determine the node running $pod" >&2; return 1; }
  >   DEBUG_IMAGE=$(kubectl -n mke get pod "$pod" -o jsonpath='{.spec.containers[0].image}')
  >   [ -n "$DEBUG_IMAGE" ] || { echo "could not determine the image of $pod" >&2; return 1; }
  >   CUC_DEBUG_READY=1
  > }
  > if ! cuc_debug_env; then
  >   echo "debug environment not derived; the later steps will refuse to run" >&2
  > fi
  > ```
  >
  > The guards are important because the failure that they prevent is silent
  > and not loud. An empty selector is not an error for `kubectl`. `-l ''`
  > matches every pod. Then the function uses the node and image of an unrelated pod
  > and they pass every later check. It is important to select a `Running` and
  > `Ready` pod and not the first pod. This procedure runs *during* a
  > controller upgrade. A rollout can be in progress. In that case, the
  > query returns the ready old pod and its pending replacement together,
  > and `READY 1/1` still reads as expected.
  >
  > The block is a function for one reason: it must **stop**. A bare
  > `: "${VAR:?message}"` guard prints its message, and the shell continues
  > to the next pasted line, which is the dangerous line. `exit` stops the
  > block but closes the session of the operator. On an air-gapped host this
  > is a disproportionate result for a transient lookup failure. `return`
  > inside a function does both: it skips the remaining derivation and the
  > shell stays open. We checked both behaviors by pasting this block into
  > an interactive shell. We did not only reason about them.
  >
  > The `NODE` that this block sets replaces the `kubectl get nodes … | head -1`
  > selection that the steps below use. The debug pod must start on the node whose
  > image availability the block just established. The block reads the selector
  > from the Deployment and does not hardcode it, because the chart generates
  > the selector from the release name. Today it resolves to
  > `app.kubernetes.io/name=cluster-upgrade-controller,
  > app.kubernetes.io/instance=<release>`. A renamed release changes it.
  >
  > Read the image from the cluster and not from `versions.txt` of the node.
  > That file is on the node, and the debug pod exists to reach the node.
  >
  > `mirantis/ucp` also has both and is a sound second choice.
  > **Two preloaded images do not work, although both look as if they
  > should:** `rancher/kubectl` contains only the `kubectl` binary and two
  > `/etc` files. It has no shell, so `chroot` fails in a way that looks like
  > a permissions or path error and not like a missing binary.
  > `machine-config-controller` has a large file system but no shell and no
  > `chroot`. The `machine-config-controller/agent` image next to it has
  > both.
  >
  > The namespace must permit a privileged pod with a host mount. We derived
  > this procedure from a run that used `-n default` with the MKE admin
  > client bundle.
  > ```sh
  > cuc_copy_manifests() {
  >   local m tmp
  >   unset CUC_MANIFESTS_FRESH
  >   [ "${CUC_DEBUG_READY:-}" = 1 ] || {
  >     echo "NODE and DEBUG_IMAGE were not freshly derived; run cuc_debug_env first" >&2; return 1; }
  >   for m in system-upgrade-controller-crd system-upgrade-controller \
  >            machine-config-controller-manifest cluster-upgrade-controller-manifest; do
  >     tmp=$(mktemp "./${m}.yaml.XXXXXX") || return 1
  >     if kubectl -n default debug "node/${NODE}" --image="${DEBUG_IMAGE}" --quiet --attach=true -- \
  >          chroot /host cat "/usr/share/mke-controllers/manifests/${m}.yaml" > "$tmp" && [ -s "$tmp" ]; then
  >       if ! mv "$tmp" "${m}.yaml"; then
  >         rm -f "$tmp"
  >         echo "copy of ${m}.yaml failed; any existing copy was left untouched" >&2
  >         return 1
  >       fi
  >     else
  >       rm -f "$tmp"
  >       echo "copy of ${m}.yaml failed; any existing copy was left untouched" >&2
  >       return 1
  >     fi
  >   done
  >   CUC_MANIFESTS_FRESH=1
  > }
  > if ! cuc_copy_manifests; then
  >   echo "manifests not copied; do not apply" >&2
  > fi
  > ```
  > The command writes each file through `mktemp` and renames it only after
  > the copy succeeds and produces a non-empty result. A redirect directly
  > onto `${m}.yaml` truncates the file when the shell opens it. This
  > happens before `kubectl` runs, and before `kubectl` can fail. A failed
  > retry then destroys the manifests that a previous successful run copied.
  >
  > Then apply all four manifests. If you apply only the SUC pair,
  > `machine-config-controller` and `cluster-upgrade-controller` stay on their
  > old versions, including an outdated `ClusterUpgrade` CRD. The
  > `cluster-upgrade-controller` manifest sets no `metadata.namespace`.
  > Therefore it needs `--namespace` explicitly. Otherwise it goes to
  > `default` (compare `ansible/tasks/cluster-upgrade-controller-tasks.yml`):
  > ```sh
  > cuc_apply_manifests() {
  >   [ "${CUC_MANIFESTS_FRESH:-}" = 1 ] || {
  >     echo "manifests were not freshly copied; not applying" >&2; return 1; }
  >   kubectl apply -f system-upgrade-controller-crd.yaml &&
  >   kubectl apply -f system-upgrade-controller.yaml &&
  >   kubectl apply -f machine-config-controller-manifest.yaml &&
  >   kubectl apply --namespace mke -f cluster-upgrade-controller-manifest.yaml
  > }
  > cuc_apply_manifests
  > ```
  > The apply step refuses to run unless the copy above completed in this
  > shell. Files that remain from an earlier attempt look the same as fresh
  > files on disk. An apply of a stale manifest is worse than no apply.
  > The apply of the manifest of `cluster-upgrade-controller` replaces the
  > controller that does the upgrade. Do it last, as the step itself does.

  This step runs **last**, after `mke3-upgrade`. By then, every node has
  booted the target image. The final action of the chain is that
  `cluster-upgrade-controller` replaces its own CRD/Deployment/RBAC with a
  plain Kubernetes Job. This is not a SUC Plan on purpose. A SUC Plan would
  make SUC watch the Job that replaces the CRD of SUC. The step has **no
  rollback counterpart**. The controller records a failure in this step as
  condition `MKE3ControllersUpgradedRollbackUnsupported` and does not revert it. See
  [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md).
- To apply the CR, run `kubectl apply -f <file>.yaml`.

### 4. Monitor progress

```sh
# High-level phase and active step
kubectl get clusterupgrade <name> -w

# Full status, including conditions
kubectl describe clusterupgrade <name>

# Underlying per-node work is driven by System Upgrade Controller plans
kubectl get plans.upgrade.cattle.io -n system-upgrade
kubectl get pods -n system-upgrade
```

`.status.phase` moves through `Upgrading` to a terminal `Completed` or
`Failed`. `.status.activeStep` names the current step during `Upgrading`
(for example `mke3-backup`, `bootc-os`, `mke3-verify-environment`,
`mke3-upgrade`, `mke3-controllers-upgrade`).
`mke3-controllers-upgrade` appears only if you set `controllersUpgrade.enabled`.

## Expected Results

- `.status.phase` reaches `Completed`.
- `kubectl get nodes` shows every node `Ready`.
- The MKE UI/API and `docker version` report the target product version. If
  you specified an OS image, `bootc status` on each node shows it as booted.
- **If you set `controllersUpgrade.enabled`**: `.status.conditions` includes
  `MKE3ControllersUpgraded: "True"`. The running images match the images
  that the node now has in `/usr/share/mke-controllers/versions.txt`:
  ```sh
  kubectl -n system-upgrade get deploy system-upgrade-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  kubectl -n system-upgrade get deploy machine-config-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  kubectl -n mke get deploy cluster-upgrade-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  ```
  `.status.phase: Completed` alone does not prove this. If the field is
  unset, there is no such condition and the Deployments do not change.
  `.status.phase` reaches `Completed` in both cases.

## System Upgrade Controller v0.14.0 → v0.20.2

Images that pin System Upgrade Controller (SUC) v0.20.2 cannot apply that
manifest over a cluster that still runs v0.14.0. This is true if the
`cluster-upgrade-controller` is older than the fix that this section describes.
The `mke3-controllers-upgrade` step fails and the whole `ClusterUpgrade`
reaches `Failed`:

```
applying /manifests/system-upgrade-controller.yaml
(Deployment system-upgrade/system-upgrade-controller):
Deployment.apps "system-upgrade-controller" is invalid:
spec.strategy.rollingUpdate: Forbidden: may not be specified
when strategy `type` is 'Recreate'
```

Cause: the v0.14.0 manifest sets no `spec.strategy`. The API server
therefore sets the live Deployment to `RollingUpdate` by default, with a
populated `rollingUpdate` block. The v0.20.2 manifest sets `type: Recreate`
and no `rollingUpdate` key. Server-Side Apply changes the type but cannot
remove the block that the API server set by default. The client that applied v0.14.0
owns that block. Therefore the API server rejects the merged object. Fresh
installs of v0.20.2 are not affected, because there is no existing
Deployment to merge against.

**Upgrade order.** Upgrade to a release that has the fixed
`cluster-upgrade-controller` *before* you upgrade to a release that pins SUC
v0.20.2. The `mke3-controllers-upgrade` Job runs the
`cluster-upgrade-controller` image that already runs on the cluster. It does
not run the image that the target image stages. A cluster that goes
directly to the SUC v0.20.2 release does the apply with the old controller
and has the failure above. A single image that contains both does not
prevent the failure.

**Recovery for a cluster that had the failure.** In a *single* patch, set
the strategy type and remove the orphaned field. Then apply the
`ClusterUpgrade` again:

```sh
kubectl patch deploy -n system-upgrade system-upgrade-controller --type=json \
  -p '[{"op":"remove","path":"/spec/strategy/rollingUpdate"},
       {"op":"replace","path":"/spec/strategy/type","value":"Recreate"}]'
```

Both operations are necessary, and they must be in one patch. If you remove
`rollingUpdate` but leave `type: RollingUpdate`, the problem remains. The
API server sets `rollingUpdate` by default whenever the type is
`RollingUpdate`. Therefore the API server fills the block again. This is how
the block came to exist in the first place, from the manifest of v0.14.0
that has no strategy. The next apply fails in the same way. A JSON patch
applies as a unit, so the object never has that state. If you set
`type: Recreate`, nothing remains to set by default, because the API server
sets `rollingUpdate` by default only for `RollingUpdate`.

Before you apply anything again, check the result:

```sh
# must print: Recreate
kubectl -n system-upgrade get deploy system-upgrade-controller \
  -o jsonpath='{.spec.strategy.type}'

# must print nothing at all — an empty result means the block is gone
kubectl -n system-upgrade get deploy system-upgrade-controller \
  -o jsonpath='{.spec.strategy.rollingUpdate}'
```

Both checks are important. The second check catches the failure state:
`type: Recreate` with a remaining `rollingUpdate` block is the exact
combination that the API server rejects. Each check selects a scalar or an
absent field and not the whole `strategy` object, because the way that
`jsonpath` shows a map differs between `kubectl` versions.

`kubectl apply` is not a workaround by itself. Client-side apply also keeps
the field that the API server set by default.

We did **not test** this recovery procedure on a live cluster. The
upgrade path itself ran on a live cluster (see the verification record
on PRODENG-3820). That run used a controller that already had the fix and
did not need this patch.

The only evidence for the patch itself is client-side. When you apply it
with `kubectl patch --local` to a Deployment in the pre-patch state
(`type: RollingUpdate` with `maxSurge`/`maxUnavailable` 25%), the result is
`type: Recreate` with no `rollingUpdate` key. This proves that the patch
document changes the object as intended. It does **not** prove that an API
server accepts the result. It does not test server-side defaulting. It does
not prove that the subsequent `ClusterUpgrade` apply succeeds.

## Rollback

If `.status.phase` reaches `Failed`, the same CR can revert the steps that
it already applied (OS, MCR, and MKE together) with
`spec.rollback.requested`. See
[Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) for the
prerequisites, the per-step undo table (what is and is not reverted), and
the procedure.

## Where this is documented upstream

The upstream repository documents these topics:

- The full step-by-step behavior of each upgrade step (`mke3-docker-config`,
  `mke3-backup`, `bootc-os`, `mke3-verify-environment`, `mke3-upgrade`,
  `mke3-controllers-upgrade`).
- Additional scenarios (product-only upgrade, Docker daemon config
  distribution).
- The `cluster-upgrade-controller` install procedure itself.

See the documentation in the
[`cluster-upgrade-controller`](https://github.com/Mirantis/cluster-upgrade-controller)
repository itself. This runbook intentionally does not duplicate it.
