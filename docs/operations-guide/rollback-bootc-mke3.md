# Roll back a bootc-mke3 upgrade (via the `ClusterUpgrade` CR)

This is the canonical way to revert a **failed** `ClusterUpgrade` on an
MKE 3.x `bootc-mke3` cluster. Set `spec.rollback.requested` on the same CR.
The `cluster-upgrade-controller`, which is already installed, handles the
request. You do not need SSH.

> [!NOTE]
> This page describes the combined **OS + MCR + MKE** rollback that the
> `ClusterUpgrade` CR drives. For the manual OS/MCR-only path (`sudo bootc
> rollback` over SSH, no MKE restore), see
> [Upgrade rollback](upgrade-with-ansible.md#upgrade-rollback).

## When to use this

- After a `ClusterUpgrade` reaches `status.phase=Failed`
  (`kubectl get clusterupgrade <name>`).
- Or set `spec.rollback.requested: true` from the start, as an opt-in
  "roll back automatically if this upgrade fails."

The controller never starts a rollback automatically. Even when you set the
flag in advance, the rollback starts only after the upgrade reaches `Failed`.
If a mutating action (`bootc rollback`, `mirantis/ucp restore`) is tried again
on a cluster that is already degraded, it can make the original failure worse.
Therefore the decision to roll back is always explicit, and it is recorded on
the CR.

## Prerequisites

1. A `ClusterUpgrade` CR that reached `Failed` (or that you are about to apply
   with `spec.rollback.requested: true` set in advance).
2. The MKE backup that the `mke3-backup` step made during that **same**
   upgrade attempt must still exist at `spec.product.mke3.backupDir` on the
   manager nodes. `mke3-restore` reads from it directly. MKE has no in-place
   "downgrade". A restore from backup is the only way back.
3. Client bundle access (`kubectl`). See
   [Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)](upgrade-with-controller.md).

## What does and doesn't get reverted

| Step applied by the failed upgrade | Reverted? | How |
|---|---|---|
| `bootc-os` (OS + MCR, baked into one image) | Yes | `bootc rollback` through a SUC Plan, restricted to exactly the nodes that this attempt switched. Workers first, then control-plane, which is the reverse of the forward order. |
| `mke3-upgrade` | Yes | `mirantis/ucp restore` with the `mke3-backup` tar from earlier in the same attempt. |
| `mke3-backup`, `mke3-verify-environment` | N/A | These steps do not change the cluster. There is nothing to undo. |
| `mke3-docker-config` | Yes | `mke3-docker-config-rollback` runs `revert-docker-config.sh` through a SUC Plan. The script restores the existing `/etc/docker/daemon.json` of each configured node from the `daemon.json.bak` backup (or removes the file if none existed before). It is restricted to exactly the nodes that the forward Plan changed. Workers first, then control-plane, in the same order as the `bootc-os` rollback. |
| `machine-config-controller`-managed changes (`MachineConfigChange`: DNS/NTP/kernel/etc.) | **No** | This is a separate controller, and the `ClusterUpgrade` rollback does not change it. Revert manually only, from the `<file>.mcc-orig` backup on each node. See [R8](controller-security-analysis.md#5-consolidated-risk-register). |
| `mke3-controllers-upgrade` (SUC / `machine-config-controller` / `cluster-upgrade-controller` manifests, when `controllersUpgrade.enabled` was set) | **No** | Recorded as condition `MKE3ControllersUpgradedRollbackUnsupported`. `ClusterUpgrade` does not revert it. A revert of an applied CRD/RBAC/Deployment is not meaningfully safer than leaving the forward apply in place. This step also replaces `cluster-upgrade-controller` itself, which is the process that would have to do the undo. Revert manually only, if truly needed. To do this, apply the manifests of the previous version by hand. |
| CNI / CSI | N/A | Not a separate upgrade surface today. CNI is either baked into the bootc OS image (and reverted with it) or fully unmanaged, with no independent version or rollback path. |

If your upgrade attempt changed anything in a "No" row above, the rollback is
**partial**. Before you treat the cluster as fully reverted, run
`kubectl describe clusterupgrade <name>` and check for `*RollbackUnsupported`
conditions.

## Procedure

1. Request the rollback:
   ```sh
   kubectl patch clusterupgrade <name> --type=merge \
     -p '{"spec":{"rollback":{"requested":true}}}'
   ```
2. Monitor the rollback:
   ```sh
   kubectl get clusterupgrade <name> -w
   kubectl describe clusterupgrade <name>
   ```
   `.status.phase` changes from `Failed` to `RollingBack` (`.status.activeStep`
   names the undo step in progress). Then it changes to the terminal phase
   `RolledBack` or `RollbackFailed`.
3. If the phase is `RolledBack`, check `status.conditions` for
   `*RollbackUnsupported` entries. Handle them manually as the table above
   describes.
4. If the phase is `RollbackFailed`, an undo step failed. Investigate manually.
   This terminal phase is different from `Failed`. Therefore you cannot
   mistake a rollback failure for a recurrence of the original failure.

## Expected results

- `.status.phase` reaches `RolledBack`.
- `bootc status` on the affected nodes shows that the previous OS image is
  booted.
- `docker version` and the MKE UI show the previous MKE version.
- `kubectl get nodes` shows every node as `Ready`.
- Workloads recover normally.
- There are no `*RollbackUnsupported` conditions, or you handled them manually.

## Out of scope

- **Swarm/etcd quorum loss.** This recovery needs `systemctl stop docker`
  on the whole cluster. A pod cannot run this command on the cluster that it
  would stop, and post-install hardening can already disable SSH. Use manual,
  console-access recovery only.
- **MKE4.** The `k0rdent`/`mke`/`etcd-maintenance` steps have no implemented
  rollback today. They are not relevant to MKE 3.x clusters.

## Where this is documented upstream

The full `RollingBack` mechanics, the undo table for each step, and the
internals of the reconciler are in
[`cluster-upgrade-controller`](https://github.com/Mirantis/cluster-upgrade-controller),
in its `docs/architecture.md` ("Rollback" section) and `docs/reference.md`.
This runbook intentionally does not duplicate them.
