# Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)

This is the **canonical** way to upgrade an existing `bootc-mke3` cluster:
applying a kube-native `ClusterUpgrade` custom resource, handled by the
`cluster-upgrade-controller` already installed on the cluster by default.
No SSH and no Ansible inventory are required — only `kubectl` access via the
[client bundle](access-cluster.md).

> [!NOTE]
> A manual, Ansible-driven exception path exists for clusters where
> `cluster-upgrade-controller` is unavailable or disabled — see the
> [Ansible upgrade runbook](upgrade-with-ansible.md). Both paths run the
> identical underlying `mirantis/ucp upgrade` checks and commands.

## Prerequisites

1. **A manual MKE backup must already exist** before creating the CR. The
   automated `mke3-backup` step runs early in the chain (right after the
   optional `mke3-docker-config` step, before `bootc-os`/`mke3-verify-environment`),
   but the backup-presence check comes from `mirantis/ucp upgrade`'s own
   Pre-Upgrade Checks, embedded in the **`mke3-upgrade`** step — it does not
   create a backup itself, only requires one already be present. On each manager:

   ```sh
   sudo mkdir -p <backup-dir> && sudo chmod o+w <backup-dir>
   docker run --rm --log-driver none \
     --security-opt label=disable \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v <backup-dir>:/backup \
     mirantis/ucp:<current-version> backup --no-passphrase --file <name>.tar
   ```

   The container writes as a non-root uid, hence the `chmod o+w` on the host
   backup directory. `--security-opt label=disable` is required: Rocky 9 bootc
   enforces SELinux, which otherwise denies the container access to the Docker
   socket. This is required regardless of which upgrade mechanism you use.
2. `cluster-upgrade-controller` installed in the cluster — installed by
   default as part of a standard [install](../installation-guide/install-bootc-mke3.md).
3. A [client bundle](access-cluster.md) with `kubectl` configured against the
   cluster (`export KUBECONFIG=<bundle>/kube.yml`). No SSH to cluster
   machines is required for this path.
4. Workers must be reachable from the manager(s) on the full
   `mke_worker_internal`/`mke_worker_self` port sets — see the [port
   requirements](join-machines-no-touch.md#port-requirements) table for the
   complete list, which goes beyond the minimal ports required just for
   [no-touch join](join-machines-no-touch.md). `mke3-verify-environment`
   probes the full set from the control plane to every worker; if any are
   blocked at the network layer (security group, firewall between subnets,
   etc.) the step fails naming the blocked ports and node(s), even if the
   workers' own OS firewall already allows them.
5. Read access to the target bootc OS image and MKE upgrade image referenced
   below (see [registry requirements](../installation-guide/provisioning.md#registry)).

## Procedure

### 1. Confirm the cluster is ready to upgrade

The controller drives every node unattended once the CR is applied, so a
cluster that is already degraded, or that carries state from a previous
upgrade, fails part-way through. Run these checks first; each one names what
to do when it does not hold.

**Kubernetes.** Every node `Ready`, with no pressure condition set:

```sh
kubectl get nodes
kubectl get nodes -o json | jq -r '.items[] | .metadata.name as $n
  | .status.conditions[] | select(.type!="Ready" and .status=="True")
  | "\($n) \(.type)"'
```

The second command prints nothing on a healthy cluster. Any `MemoryPressure`,
`DiskPressure` or `PIDPressure` row names a node to clear before upgrading —
the upgrade pulls images and writes a new OS deployment on every node, both
of which need disk.

No workload is stuck or failing. Phase alone is not enough — a pod whose
container is in `CrashLoopBackOff`, or failing its readiness probe, stays in
phase `Running` — so check both:

```sh
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get pods -A -o json | jq -r '.items[]
  | select([.status.containerStatuses[]? | select(.ready == false)] | length > 0)
  | "\(.metadata.namespace)/\(.metadata.name)"'
```

The first lists pods that never reached `Running`; the second lists running
pods with a container that is not ready, which is where a crash-looping
workload shows up. Investigate anything either prints. A pod already
`Pending` for lack of capacity will not schedule any better while nodes are
being drained in sequence.

**Custom resource definitions.** Both CRDs the upgrade uses must be present
and `Established`, and must serve the API versions the CR and the controller
use:

```sh
kubectl get crd clusterupgrades.upgrade.mirantis.com plans.upgrade.cattle.io \
  -o custom-columns=\
'NAME:.metadata.name,ESTABLISHED:.status.conditions[?(@.type=="Established")].status,SERVED:.spec.versions[?(@.served==true)].name'
```

Both rows must read `True`, and `clusterupgrades.upgrade.mirantis.com` must
list the `apiVersion` used by the CR in step 3 (`v1alpha1`) in its `SERVED`
column. The column filters on `served: true` deliberately: a version present
in the CRD but not served is rejected by the API server, so listing every
version would pass this check and still fail at `kubectl apply`. A missing
CRD means the relevant controller was never installed or was removed —
`kubectl apply -f` of the CR would fail with `no matches for kind`.
`Established=False` means the API server has not yet accepted the definition;
re-check before proceeding.

**cluster-upgrade-controller.** Deployment available:

```sh
kubectl -n mke get deploy cluster-upgrade-controller
```

`READY` must read `1/1`. A `CrashLoopBackOff` or repeatedly restarting pod
means the controller cannot reconcile the CR you are about to create;
diagnose with `kubectl -n mke logs deploy/cluster-upgrade-controller` before
going further.

No upgrade is already in flight or left behind:

```sh
kubectl get clusterupgrades
```

Any CR in a non-terminal phase must reach a terminal one first:
`Upgrading` and `RollingBack` are both actively mutating nodes. A CR left in
`Failed` or `RollbackFailed` must be resolved before a new CR is created —
see [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) for the phase
model (`Failed` → `RollingBack` → `RolledBack` or `RollbackFailed`) and for
what `RollbackFailed` needs. `Completed` and `RolledBack` are terminal and do
not block a new upgrade.

**system-upgrade-controller.** This is what executes the per-node work, so
the upgrade cannot proceed without it:

```sh
kubectl -n system-upgrade get deploy system-upgrade-controller
kubectl -n system-upgrade get plans,jobs
```

The deployment must read `1/1`. The second command should return `No
resources found` on a cluster with no upgrade history: a leftover `Plan`
re-fires against nodes that join later, and a `Job` still running or in
error is a previous upgrade that never finished. SUC's own TTL
(`SYSTEM_UPGRADE_JOB_TTL_SECONDS_AFTER_FINISH`, 900s) removes completed
jobs, so anything older is residue worth clearing.

Do not extend this to `pods`: the `system-upgrade` namespace also holds the
`system-upgrade-controller` and `machine-config-controller` pods themselves,
which are expected to be `Running` and are not upgrade residue.

**MKE and Swarm.** Expected machine count present and manager quorum intact:

```sh
kubectl get nodes -l node-role.kubernetes.io/master
(cd <bundle-dir> && source env.sh && docker node ls)
```

`docker node ls` needs the client bundle's Docker environment, not just
`KUBECONFIG`: without `env.sh` sourced from inside the bundle directory it
talks to whatever local Docker daemon is configured instead of the cluster.

Manager count must be odd and every manager reachable; upgrading with a
manager already down leaves no quorum margin when the next one reboots.
A worker that `docker node ls` reports `Down` while `kubectl get nodes` has
it `Ready` needs `docker node inspect <node>` before it is dismissed: the
known benign case is specifically the `"Node not yet found in classic node
inventory"` message described in [no-touch
join](join-machines-no-touch.md). Any other reason is a real problem to
resolve first.

### 2. Verify target image access

Before applying the CR, confirm the target `mirantis/ucp:<version>` upgrade
image and (if `spec.os.image` is set) the target bootc OS image are both
pullable from wherever the cluster's nodes read images from — see
[registry requirements](../installation-guide/provisioning.md#registry).
`cluster-upgrade-controller` reuses its own image to run the `mke3-upgrade`
step; there is no separate `spec.product.mke3.image` field to configure.

On an air-gapped cluster, also confirm that
`SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` in `system-upgrade/default-controller-env`
is not `Always`. Images built before 2026-10-29 ship it as `Always`, which
makes SUC create every step's Job with `imagePullPolicy: Always` and sends the
kubelet to the registry even for images already on the node — see
[Older images: SUC Job pull policy](../installation-guide/airgap-bootc-mke3.md#older-images-suc-job-pull-policy).

If `spec.os.image` is set, verify its cosign signature before applying the
CR — see
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
      backupDir: <backup-dir>                  # same dir used for the manual backup above
      controllersUpgrade:
        enabled: true                          # see callout below before omitting this
  controlPlaneConcurrency: 1
  workerConcurrency: <N>
```

- `spec.os` is optional — omit it to upgrade the MKE product only, leaving
  the OS/MCR version unchanged.
- `backupDir` is optional — the CRD defaults it to `/var/lib/mke-backup`.
  Set it explicitly (as above) only if your manual backup (prerequisite #1)
  used a different directory.
- `controlPlaneConcurrency` and `workerConcurrency` bound how many nodes of
  each role the controller drives through the upgrade steps at once. Manager
  nodes are always upgraded serially before workers start; workers proceed in
  batches of `workerConcurrency`.
- `controllersUpgrade.enabled` gates a sixth, final step —
  `mke3-controllers-upgrade` — that re-applies the System Upgrade Controller,
  `machine-config-controller`, and `cluster-upgrade-controller` manifests
  baked into the target OS image. **The CRD defaults this to `false`, by
  design**: the step replaces cluster-wide CRDs, RBAC and Deployments,
  including `cluster-upgrade-controller`'s own, so it is opt-in per upgrade
  rather than something a CR acquires implicitly.

  > [!NOTE]
  > **With the field unset, the controllers are not upgraded and nothing
  > records that.** `.status.phase` reaches `Completed`, no condition is
  > set, and no log line reports the step being skipped — the absence of
  > `MKE3ControllersUpgraded` in `.status.conditions` is the only signal.
  > The target OS image stages newer SUC/`machine-config-controller`/
  > `cluster-upgrade-controller` manifests on disk
  > (`/usr/share/mke-controllers/manifests`); with the field unset none of
  > them are applied, and the cluster keeps running the versions it was
  > *installed* with across any number of later OS or product upgrades
  > until an upgrade sets the field.
  >
  > **Set it to `true`** when you want the platform controllers to track the
  > OS image — which is the normal case for a cluster whose controllers were
  > installed from these images and are not managed elsewhere. **Leave it
  > unset or `false`** when you manage any of the three out-of-band (a
  > separate Helm release, for example), when you need the product upgrade
  > and the controller upgrade to land in separate change windows, or when
  > you want to keep a known-good controller version across a product bump.
  >
  > The field requires `cluster-upgrade-controller` `v0.1.9-tp1`/`v0.2.0` or
  > later — it does not exist in earlier CRDs. Confirm it was accepted
  > immediately after applying, rather than after waiting out the whole
  > upgrade:
  > ```sh
  > kubectl get clusterupgrade <name> \
  >   -o jsonpath='{.spec.product.mke3.controllersUpgrade.enabled}'   # must print: true
  > ```
  > If it prints nothing, the pre-upgrade `cluster-upgrade-controller` is too
  > old for this field. Upgrade the three controllers by hand after the
  > product upgrade instead, using the manifests the new OS image staged on
  > each node.
  >
  > These manifests live at `/usr/share/mke-controllers/manifests` **on the
  > nodes**, not on your workstation, and `kubectl apply -f` reads the
  > client's filesystem — pointing it at that path fails with a
  > missing-path error. Copy them off a node first. This needs no SSH
  > (managers revoke it after install) because `kubectl debug node` runs a
  > pod with the host filesystem mounted at `/host`; `--attach=true` is
  > required or the command returns no output.
  >
  > `DEBUG_IMAGE` below is operator-supplied, because the right image
  > depends on the environment. It must be pullable on that cluster — or
  > already present on the node — and must contain both a shell and
  > `chroot`. `busybox` satisfies this wherever the cluster can reach a
  > public registry, which is what CI uses. **On an air-gapped cluster
  > `busybox` will not pull**, leaving the debug pod in `ImagePullBackOff`
  > before any manifest is copied; substitute an image already preloaded on
  > the nodes. A distroless image will not work — it has neither a shell
  > nor `chroot`.
  >
  > The namespace must permit a privileged pod with a host mount. The run
  > this procedure is derived from used `-n default` with the MKE admin
  > client bundle.
  > ```sh
  > DEBUG_IMAGE=busybox   # see the requirements above before using this on an air-gapped cluster
  > NODE=$(kubectl get nodes -l node-role.kubernetes.io/master -o name | head -1 | cut -d/ -f2)
  > for m in system-upgrade-controller-crd system-upgrade-controller \
  >          machine-config-controller-manifest cluster-upgrade-controller-manifest; do
  >   kubectl -n default debug "node/${NODE}" --image="${DEBUG_IMAGE}" --quiet --attach=true -- \
  >     chroot /host cat "/usr/share/mke-controllers/manifests/${m}.yaml" > "${m}.yaml"
  > done
  > ```
  > Then apply all four — applying only the SUC pair leaves
  > `machine-config-controller` and `cluster-upgrade-controller` on their old
  > versions, including an outdated `ClusterUpgrade` CRD. The
  > `cluster-upgrade-controller` manifest sets no `metadata.namespace`, so it
  > needs `--namespace` explicitly or it lands in `default` (compare
  > `ansible/tasks/cluster-upgrade-controller-tasks.yml`):
  > ```sh
  > kubectl apply -f system-upgrade-controller-crd.yaml
  > kubectl apply -f system-upgrade-controller.yaml
  > kubectl apply -f machine-config-controller-manifest.yaml
  > kubectl apply --namespace mke -f cluster-upgrade-controller-manifest.yaml
  > ```
  > Applying `cluster-upgrade-controller`'s own manifest replaces the
  > controller performing the upgrade; do it last, as the step itself does.

  This step runs **last**, after `mke3-upgrade` — every node has already
  booted the target image by then, including the final act of the chain:
  `cluster-upgrade-controller` replacing its own CRD/Deployment/RBAC via a
  plain Kubernetes Job (deliberately not a SUC Plan, to avoid SUC watching
  the very Job that replaces SUC's own CRD out from under it). It has **no
  rollback counterpart** — a failure here is recorded as condition
  `MKE3ControllersUpgradedRollbackUnsupported` rather than reverted; see
  [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md).
- Apply with `kubectl apply -f <file>.yaml`.

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

`.status.phase` moves through `Upgrading` (with `.status.activeStep` naming
the current step, e.g. `mke3-backup`, `bootc-os`, `mke3-verify-environment`,
`mke3-upgrade`, `mke3-controllers-upgrade`) to a terminal `Completed` or
`Failed`. `mke3-controllers-upgrade` only appears when
`controllersUpgrade.enabled` was set.

## Expected Results

- `.status.phase` reaches `Completed`.
- `kubectl get nodes` shows every node `Ready`.
- The MKE UI/API and `docker version` report the target product version; if
  an OS image was specified, `bootc status` on each node shows it as booted.
- **If `controllersUpgrade.enabled` was set**: `.status.conditions` includes
  `MKE3ControllersUpgraded: "True"`, and the running images match what the
  node now carries at `/usr/share/mke-controllers/versions.txt`:
  ```sh
  kubectl -n system-upgrade get deploy system-upgrade-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  kubectl -n system-upgrade get deploy machine-config-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  kubectl -n mke get deploy cluster-upgrade-controller \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
  ```
  `.status.phase: Completed` alone does not prove any of this — with the
  field unset there is no such condition and the Deployments are simply
  untouched, and `Completed` is reached either way.

## System Upgrade Controller v0.14.0 → v0.20.2

Images that pin System Upgrade Controller (SUC) v0.20.2 cannot have that
manifest applied over a cluster still running v0.14.0 by a
`cluster-upgrade-controller` older than the fix described below. The
`mke3-controllers-upgrade` step fails and the whole `ClusterUpgrade`
reaches `Failed`:

```
applying /manifests/system-upgrade-controller.yaml
(Deployment system-upgrade/system-upgrade-controller):
Deployment.apps "system-upgrade-controller" is invalid:
spec.strategy.rollingUpdate: Forbidden: may not be specified
when strategy `type` is 'Recreate'
```

Cause: the v0.14.0 manifest sets no `spec.strategy`, so the API server
defaults the live Deployment to `RollingUpdate` with a populated
`rollingUpdate` block. The v0.20.2 manifest sets `type: Recreate` and no
`rollingUpdate` key. Server-Side Apply changes the type but cannot remove
the defaulted block, which is owned by whichever client applied v0.14.0,
so the merged object is rejected. Fresh installs of v0.20.2 are
unaffected — there is no pre-existing Deployment to merge against.

**Upgrade order.** Upgrade to a release carrying the fixed
`cluster-upgrade-controller` *before* upgrading to a release that pins SUC
v0.20.2. The `mke3-controllers-upgrade` Job runs the
`cluster-upgrade-controller` image already running on the cluster, not the
one staged in the target image, so a cluster that jumps straight to the
SUC v0.20.2 release performs the apply with the old controller and hits
the failure above. Shipping both in one image does not avoid it.

**Recovery for a cluster that hit the failure.** Set the strategy type and
remove the orphaned field in a *single* patch, then re-apply the
`ClusterUpgrade`:

```sh
kubectl patch deploy -n system-upgrade system-upgrade-controller --type=json \
  -p '[{"op":"remove","path":"/spec/strategy/rollingUpdate"},
       {"op":"replace","path":"/spec/strategy/type","value":"Recreate"}]'
```

Both operations are required, and in one patch. Removing `rollingUpdate`
while leaving `type: RollingUpdate` does not help: `rollingUpdate` is
defaulted whenever the type is `RollingUpdate`, so the API server
repopulates the block — which is how it came to exist in the first place,
from v0.14.0's strategy-less manifest — and the next apply fails
identically. A JSON patch applies as a unit, so the object never passes
through that state. Setting `type: Recreate` leaves nothing to default,
because `rollingUpdate` is only defaulted for `RollingUpdate`.

Confirm the result before re-applying anything:

```sh
kubectl -n system-upgrade get deploy system-upgrade-controller \
  -o jsonpath='{.spec.strategy}'   # must print: {"type":"Recreate"}
```

`kubectl apply` is not a workaround on its own: client-side apply also
retains the defaulted field.

This recovery procedure has **not been exercised on a live cluster**. The
upgrade path itself has — see the verification recorded on PRODENG-3820 —
but that run used a controller already carrying the fix and never needed
this patch.

## Rollback

If `.status.phase` reaches `Failed` instead, the same CR can revert the
steps it already applied — OS, MCR, and MKE together — via
`spec.rollback.requested`. See
[Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) for the
prerequisites, the per-step undo table (what is and isn't reverted), and
the procedure.

## Where this is documented upstream

Full step-by-step behavior of each upgrade step (`mke3-docker-config`,
`mke3-backup`, `bootc-os`, `mke3-verify-environment`, `mke3-upgrade`,
`mke3-controllers-upgrade`), additional
scenarios (product-only upgrade, Docker daemon config distribution), and the
`cluster-upgrade-controller` install procedure itself live in the
[`cluster-upgrade-controller`](https://github.com/Mirantis/cluster-upgrade-controller)
repository's own docs — this runbook intentionally does not duplicate them.
