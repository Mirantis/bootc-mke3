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
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v <backup-dir>:/backup \
     mirantis/ucp:<current-version> backup --no-passphrase --file <name>.tar
   ```

   The container writes as a non-root uid, hence the `chmod o+w` on the host
   backup directory. This is required regardless of which upgrade mechanism
   you use.
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

### 1. Verify target image access

Before applying the CR, confirm the target `mirantis/ucp:<version>` upgrade
image and (if `spec.os.image` is set) the target bootc OS image are both
pullable from wherever the cluster's nodes read images from — see
[registry requirements](../installation-guide/provisioning.md#registry).
`cluster-upgrade-controller` reuses its own image to run the `mke3-upgrade`
step; there is no separate `spec.product.mke3.image` field to configure.

If `spec.os.image` is set, verify its cosign signature before applying the
CR — see
[Verify bootc-mke3 image signatures](verify-image-signatures.md#at-installswitch-time).

### 2. Apply the `ClusterUpgrade` CR

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
  baked into the target OS image. **The CRD defaults this to `false`.**

  > [!WARNING]
  > **Leaving this unset silently skips upgrading your platform controllers.**
  > `.status.phase` still reaches `Completed` with no error, mention, or
  > degraded condition — there is nothing in a normal run's output that
  > tells you the three controllers were left behind. Concretely: the OS
  > image you just switched to stages newer SUC/`machine-config-controller`/
  > `cluster-upgrade-controller` manifests on disk
  > (`/usr/share/mke-controllers/manifests`), but without this field none of
  > them are ever applied — the cluster keeps running whatever it was
  > *installed* with, indefinitely, across any number of future OS/product
  > upgrades, until some run finally sets it. Set it explicitly on every
  > upgrade unless you manage these three controllers out-of-band (e.g. a
  > separate Helm release process you control) and have deliberately decided
  > this step should not touch them.
  >
  > It is also only visible to CRD versions new enough to know about it:
  > the field first exists in `cluster-upgrade-controller` `v0.1.9-tp1`/
  > `v0.2.0`. Applying it against an **older** pre-upgrade
  > `cluster-upgrade-controller` does not error either — Kubernetes
  > structural-schema pruning silently drops the whole block, `kubectl
  > apply` succeeds, and the step still never runs. Confirm it was accepted
  > immediately after applying, not after waiting out the whole upgrade:
  > ```sh
  > kubectl get clusterupgrade <name> \
  >   -o jsonpath='{.spec.product.mke3.controllersUpgrade.enabled}'   # must print: true
  > ```
  > If it prints nothing, the pre-upgrade `cluster-upgrade-controller` is too
  > old for this field — apply the baked SUC CRD/Deployment manifests by
  > hand after the upgrade instead:
  > ```sh
  > kubectl apply -f /usr/share/mke-controllers/manifests/system-upgrade-controller-crd.yaml
  > kubectl apply -f /usr/share/mke-controllers/manifests/system-upgrade-controller.yaml
  > ```

  This step runs **last**, after `mke3-upgrade` — every node has already
  booted the target image by then, including the final act of the chain:
  `cluster-upgrade-controller` replacing its own CRD/Deployment/RBAC via a
  plain Kubernetes Job (deliberately not a SUC Plan, to avoid SUC watching
  the very Job that replaces SUC's own CRD out from under it). It has **no
  rollback counterpart** — a failure here is recorded as condition
  `MKE3ControllersUpgradedRollbackUnsupported` rather than reverted; see
  [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md).
- Apply with `kubectl apply -f <file>.yaml`.

### 3. Monitor progress

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
