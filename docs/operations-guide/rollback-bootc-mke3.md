# Roll back a bootc-mke3 upgrade (via the `ClusterUpgrade` CR)

This is the canonical way to revert a **failed** `ClusterUpgrade` on an
MKE 3.x `bootc-mke3` cluster: setting `spec.rollback.requested` on the same
CR, handled by the already-installed `cluster-upgrade-controller`. No SSH
required.

> [!NOTE]
> This page covers the combined **OS + MCR + MKE** rollback driven by the
> `ClusterUpgrade` CR. For the OS/MCR-only manual path (`sudo bootc
> rollback` over SSH, no MKE restore), see
> [Upgrade rollback](upgrade-with-ansible.md#upgrade-rollback).

## When to use this

- After a `ClusterUpgrade` reaches `status.phase=Failed`
  (`kubectl get clusterupgrade <name>`).
- Or set `spec.rollback.requested: true` from the start, as an opt-in
  "roll back automatically if this upgrade fails."

Rollback is never triggered automatically by the controller itself — even
with the flag pre-set, it only engages once the upgrade has actually
reached `Failed`. Retrying a mutating action (`bootc rollback`,
`mirantis/ucp restore`) against an already-degraded cluster can compound
the original failure, so this is always an explicit decision recorded on
the CR.

## Prerequisites

1. A `ClusterUpgrade` CR that reached `Failed` (or is about to be applied
   with `spec.rollback.requested: true` set up front).
2. The MKE backup taken by the `mke3-backup` step during that **same**
   upgrade attempt must still exist at `spec.product.mke3.backupDir` on the
   manager nodes — `mke3-restore` reads from it directly. MKE has no
   in-place "downgrade"; restore-from-backup is the only way back.
3. Client bundle access (`kubectl`) — see
   [Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)](upgrade-with-controller.md).

## What does and doesn't get reverted

| Step applied by the failed upgrade | Reverted? | How |
|---|---|---|
| `bootc-os` (OS + MCR, baked into one image) | Yes | `bootc rollback` via a SUC Plan, restricted to exactly the nodes this attempt switched. Workers first, then control-plane — the reverse of the forward order. |
| `mke3-upgrade` | Yes | `mirantis/ucp restore` against the `mke3-backup` tar taken earlier in the same attempt. |
| `mke3-backup`, `mke3-verify-environment` | N/A | Non-mutating; nothing to undo. |
| `mke3-docker-config` | Yes | `mke3-docker-config-rollback` runs `revert-docker-config.sh` via a SUC Plan, restoring each configured node's pre-existing `/etc/docker/daemon.json` from the `daemon.json.bak` backup (or removing the file if none existed before). Restricted to exactly the nodes the forward Plan touched. Workers first, then control-plane — same order as `bootc-os` rollback. |
| `machine-config-controller`-managed changes (`MachineConfigChange`: DNS/NTP/kernel/etc.) | **No** | Separate controller, not touched by `ClusterUpgrade` rollback at all. Manual revert only, from each node's `<file>.mcc-orig` backup — see [R8](controller-security-analysis.md#5-consolidated-risk-register). |
| `mke3-controllers-upgrade` (SUC / `machine-config-controller` / `cluster-upgrade-controller` manifests, when `controllersUpgrade.enabled` was set) | **No** | Recorded as condition `MKE3ControllersUpgradedRollbackUnsupported`, not reverted by `ClusterUpgrade` at all — reverting a live CRD/RBAC/Deployment apply is not meaningfully safer than leaving the forward apply in place, and this step also replaces `cluster-upgrade-controller` itself, the very process that would have to drive the undo. Manual revert (re-applying the previous version's manifests by hand) only, if truly needed. |
| CNI / CSI | N/A | Not a separate upgrade surface today — CNI is either baked into the bootc OS image (reverted with it) or fully unmanaged, with no independent version/rollback path. |

If your upgrade attempt touched any "No" row above, the rollback is
**partial** — check `kubectl describe clusterupgrade <name>` for
`*RollbackUnsupported` conditions before treating the cluster as fully
reverted.

## Procedure

1. Request rollback:
   ```sh
   kubectl patch clusterupgrade <name> --type=merge \
     -p '{"spec":{"rollback":{"requested":true}}}'
   ```
2. Monitor:
   ```sh
   kubectl get clusterupgrade <name> -w
   kubectl describe clusterupgrade <name>
   ```
   `.status.phase` moves `Failed` → `RollingBack` (`.status.activeStep`
   names the undo step in progress) → terminal `RolledBack` or
   `RollbackFailed`.
3. On `RolledBack`, check `status.conditions` for `*RollbackUnsupported`
   entries and handle those manually per the table above.
4. On `RollbackFailed`, an undo step itself failed — this needs manual
   investigation. It's a distinct terminal phase from `Failed` so a
   rollback failure is never mistaken for the original failure recurring.

## Expected results

- `.status.phase` reaches `RolledBack`.
- `bootc status` on affected nodes shows the previous OS image booted.
- `docker version` / the MKE UI show the previous MKE version.
- `kubectl get nodes` shows every node `Ready`.
- Workloads recover normally.
- No `*RollbackUnsupported` conditions — or, if present, handled manually.

## Out of scope

- **Swarm/etcd quorum loss.** Requires `systemctl stop docker`
  cluster-wide, which can't run from a pod on the cluster it would be
  stopping, and SSH may already be disabled by post-install hardening.
  Manual, console-access recovery only.
- **MKE4.** The `k0rdent`/`mke`/`etcd-maintenance` steps have no
  implemented rollback today. Not relevant to MKE 3.x clusters.

## Where this is documented upstream

Full `RollingBack` mechanics, the per-step undo table, and reconciler
internals live in
[`cluster-upgrade-controller`](https://github.com/Mirantis/cluster-upgrade-controller)'s
own `docs/architecture.md` ("Rollback" section) and `docs/reference.md` —
this runbook intentionally does not duplicate them.
