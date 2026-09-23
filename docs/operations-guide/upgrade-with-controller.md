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
`mke3-upgrade`) to a terminal `Completed` or `Failed`.

## Expected Results

- `.status.phase` reaches `Completed`.
- `kubectl get nodes` shows every node `Ready`.
- The MKE UI/API and `docker version` report the target product version; if
  an OS image was specified, `bootc status` on each node shows it as booted.

## Rollback

If `.status.phase` reaches `Failed` instead, the same CR can revert the
steps it already applied — OS, MCR, and MKE together — via
`spec.rollback.requested`. See
[Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) for the
prerequisites, the per-step undo table (what is and isn't reverted), and
the procedure.

## Where this is documented upstream

Full step-by-step behavior of each upgrade step (`mke3-docker-config`,
`mke3-backup`, `bootc-os`, `mke3-verify-environment`, `mke3-upgrade`), additional
scenarios (product-only upgrade, Docker daemon config distribution), and the
`cluster-upgrade-controller` install procedure itself live in the
[`cluster-upgrade-controller`](https://github.com/Mirantis/cluster-upgrade-controller)
repository's own docs — this runbook intentionally does not duplicate them.
