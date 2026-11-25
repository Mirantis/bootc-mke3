# Machine configuration changes (machine-config-controller)

Apply host-level configuration — DNS, NTP, kernel sysctls/modules, and
structured cluster-wide reboots — via the baked-in `machine-config-controller`,
using the `MachineConfigChange` custom resource. See the
[controllers runbook](../installation-guide/install-controllers.md) for what deploys this
controller, the `mke`/`system-upgrade` namespace note, and how to verify its
version; this runbook only covers using it once it's confirmed healthy.

## Requirements

1. `machine-config-controller` deployed and verified per the
   [controllers runbook](../installation-guide/install-controllers.md).
2. Cluster access per the [access runbook](access-cluster.md) — no SSH is
   needed for anything below.
3. The CRD's actual schema, read from the cluster you're operating on, not
   from this doc or an old sample:

   ```sh
   kubectl get crd -o name | grep machineconfigchanges
   kubectl get crd <the name above> -o yaml
   ```

   The manifest baked into a given image build (and therefore its CRD's exact
   `apiVersion` and `status` field names) can differ across builds — always
   confirm against the live CRD before writing a `MachineConfigChange`.
   Baked sample manifests for reference are also on any cluster node under
   `/usr/share/mke-controllers/manifests/machine-config-controller-samples/`.

## Procedure

### Non-reboot changes: network, ntp, kernel

These `spec` areas can be combined freely in a single `MachineConfigChange`
and are safely re-appliable — changing the values and re-applying
reconfigures the node, this is not a one-shot apply:

```yaml
apiVersion: <from the installed CRD, see Requirements>
kind: MachineConfigChange
metadata:
  name: mcc-example
spec:
  network:
    nameservers: ["1.1.1.1", "9.9.9.9"]
    searchDomains: ["example.com"]
  ntp:
    servers: ["<primary-ntp-host-or-ip>"]
    fallbackServers: ["<fallback-ntp-host-or-ip>"]
  kernel:
    sysctl:
      vm.swappiness: "10"
  rollout:
    concurrency: <N>
    drain: true
```

Apply it, then watch the resource's `Applied` condition reach `True`:

```sh
kubectl apply -f mcc-example.yaml
kubectl get machineconfigchange mcc-example -o jsonpath='{.status.conditions}'
```

#### MachineConfigChange resources and the pre-upgrade check

For each `MachineConfigChange` that sets a module, the controller creates a
SUC `Plan` with the same name in `system-upgrade`. The resource owns the Plan.
The Plan has the label `app.kubernetes.io/managed-by=machine-config-controller`.
The Plan stays while the resource exists. If you delete only the Plan, the
controller creates it again. A new node that joins the cluster runs the job of
the Plan. This is the intended behavior for network, ntp and kernel resources.

The readiness check in the
[upgrade runbook](upgrade-with-controller.md#1-confirm-the-cluster-is-ready-to-upgrade)
leaves out these Plans, so a kept network, ntp or kernel resource does not fail
the check. You do not need to delete these resources before an upgrade. The
effect of a kept Plan during the upgrade itself was not checked.

To stop a Plan for good, delete its resource. This does not revert the
configuration on the nodes. It stops future applications of the resource.
Nodes that join later do not get the configuration until you apply the
resource again.

### Reboot: always a dedicated resource

The same CRD's `reboot` module drives a structured, cluster-wide rolling
reboot — but with two hard rules that are load-bearing enough to repeat
here. For the full operational picture (quorum-safe splitting across roles,
stuck-node diagnosis and recovery, and reconvergence behavior for nodes that
join later), see the machine-config-controller project's own
[structured reboot runbook](https://github.com/Mirantis/machine-config-controller/blob/main/docs/structured-reboot.md)
— it is not duplicated here:

- `reboot` must be the **only** module in its `MachineConfigChange`. Never
  combine it with `network`/`ntp`/`kernel` in the same resource — modules
  apply sequentially and the reboot kills the node mid-run, so anything
  ordered after it may never execute on that pass.
- `rollout.concurrency` must stay `1`. Any higher value reboots that many
  nodes at once, which can break control-plane quorum or workload
  availability.

```yaml
apiVersion: <from the installed CRD, see Requirements>
kind: MachineConfigChange
metadata:
  name: mcc-reboot
spec:
  reboot:
    token: "<opaque token, e.g. a date or change-ticket id>"
  rollout:
    concurrency: 1
    drain: true
```

Delete the resource once the rollout completes. It's a trigger, not a
desired state — leaving it applied re-arms a reboot for any node that joins
the cluster afterwards (see the upstream runbook's reconvergence section).

## Expected Results

- `kubectl get machineconfigchange <name> -o jsonpath='{.status.conditions}'`
  shows the `Applied` condition `True`.
- The change is visible on affected nodes — e.g. `sysctl <key>`,
  `chronyc -N sources`, `/etc/resolv.conf`, or, for a reboot, a fresh
  `uptime` on each node in turn.
- With the network, ntp and kernel modules, all targeted nodes stay `Ready` in
  `kubectl get nodes` throughout and after the rollout.
- With the reboot module, a node goes `NotReady` while it reboots. This is not
  a fault. The `reboot` module restarts each node with `systemctl reboot`, and
  this runbook requires `rollout.concurrency: 1`, so at most one node at a time
  is not `Ready`. All targeted nodes are `Ready` after the rollout.

## Troubleshooting

| Symptom | Likely cause | Remediation |
|---|---|---|
| `kubectl apply` fails `strict decoding error: unknown field "spec.reboot"` (or any other module) | The cluster's CRD is older than the CR you're submitting — a stale or overridden controller manifest | See the [controllers runbook troubleshooting](../installation-guide/install-controllers.md#troubleshooting) — re-apply a manifest whose CRD matches, or drop the `machine_config_controller_manifest` override to fall back to the node-fetched default |
| `Applied=False/Applying` stuck for a long time | A targeted node isn't converging (reboot never returned, drain stuck) | See the upstream [structured reboot runbook](https://github.com/Mirantis/machine-config-controller/blob/main/docs/structured-reboot.md#stuck-node-diagnosis-and-recovery) — the same Plan/job inspection it describes applies to non-reboot modules too |
| A `mcc-reboot` resource is still applied well after its rollout finished | Not deleted post-rollout | Delete it — a lingering reboot resource re-triggers once on any node that later joins the cluster |
