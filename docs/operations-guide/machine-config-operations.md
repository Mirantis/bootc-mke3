# Machine configuration changes (machine-config-controller)

Use the baked-in `machine-config-controller` to apply host-level
configuration. This includes DNS, NTP, kernel sysctls/modules, and
structured cluster-wide reboots. Use the `MachineConfigChange` custom
resource. See the
[controllers runbook](../installation-guide/install-controllers.md) for
these topics: what deploys this controller, the `mke`/`system-upgrade`
namespace note, and how to check its version. This runbook covers only
the use of the controller after you check that it is healthy.

## Requirements

1. `machine-config-controller` runs in the cluster, and you checked it
   as described in the
   [controllers runbook](../installation-guide/install-controllers.md).
2. Cluster access as described in the [access runbook](access-cluster.md).
   You do not need SSH for any step below.
3. The actual CRD schema. Read the schema from the cluster that you
   operate on. Do not read it from this document or from an old sample:
   ```sh
   kubectl get crd -o name | grep machineconfigchanges
   kubectl get crd <the name above> -o yaml
   ```

   The manifest baked into a given image build can differ across builds.
   Therefore the exact `apiVersion` and `status` field names of its CRD
   can also differ. Always check against the live CRD before you write a
   `MachineConfigChange`.
   You can also find baked sample manifests for reference on any cluster
   node in
   `/usr/share/mke-controllers/manifests/machine-config-controller-samples/`.

## Procedure

### Non-reboot changes: network, ntp, kernel

You can combine these `spec` areas in a single `MachineConfigChange`.
You can safely apply them again. To reconfigure the node, change the
values and apply again. The apply is not a one-time action:

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

Apply the resource. Then watch the `Applied` condition of the resource
until it is `True`:

```sh
kubectl apply -f mcc-example.yaml
kubectl get machineconfigchange mcc-example -o jsonpath='{.status.conditions}'
```

### Reboot: always a dedicated resource

The `reboot` module of the same CRD does a structured, cluster-wide rolling
reboot. Two hard rules apply, and they are important enough to repeat
here. For the full operational information, see the
[structured reboot runbook](https://github.com/Mirantis/machine-config-controller/blob/main/docs/structured-reboot.md)
of the machine-config-controller project. It covers quorum-safe splitting
across roles, diagnosis and recovery of stuck nodes, and reconvergence
behavior for nodes that join later. This document does not duplicate that
information.

- `reboot` must be the **only** module in its `MachineConfigChange`. Never
  combine it with `network`/`ntp`/`kernel` in the same resource. Modules
  apply in sequence and the reboot stops the node during the run. Anything
  that is after the reboot in the sequence can fail to run on that pass.
- `rollout.concurrency` must stay `1`. A higher value reboots that number
  of nodes at the same time. This can break control-plane quorum or
  workload availability.

```yaml
apiVersion: <from the installed CRD, see Requirements>
kind: MachineConfigChange
metadata:
  name: mcc-reboot
spec:
  reboot:
    token: "<opaque token, for example a date or change-ticket id>"
  rollout:
    concurrency: 1
    drain: true
```

Delete the resource after the rollout completes. The resource is a
trigger, not a desired state. If you leave it applied, it arms a reboot
again for any node that joins the cluster afterwards. See the
reconvergence section of the upstream runbook.

## Expected Results

- `kubectl get machineconfigchange <name> -o jsonpath='{.status.conditions}'`
  shows the `Applied` condition `True`.
- The change is visible on the affected nodes. For example, check
  `sysctl <key>`, `chronyc -N sources`, or `/etc/resolv.conf`. For a
  reboot, check for a fresh `uptime` on each node in turn.
- All targeted nodes stay `Ready` in `kubectl get nodes` during and after
  the rollout.

## Troubleshooting

| Symptom | Likely cause | Remediation |
|---|---|---|
| `kubectl apply` fails `strict decoding error: unknown field "spec.reboot"` (or any other module) | The CRD of the cluster is older than the CR that you submit. The controller manifest is stale or overridden. | See the [controllers runbook troubleshooting](../installation-guide/install-controllers.md#troubleshooting). Re-apply a manifest whose CRD matches, or delete the `machine_config_controller_manifest` override to use the default that the node fetches. |
| `Applied=False/Applying` stuck for a long time | A targeted node does not converge (the reboot never returned or the drain is stuck). | See the upstream [structured reboot runbook](https://github.com/Mirantis/machine-config-controller/blob/main/docs/structured-reboot.md#stuck-node-diagnosis-and-recovery). The same Plan/job inspection that it describes also applies to non-reboot modules. |
| A `mcc-reboot` resource is still applied long after its rollout finished | No one deleted the resource after the rollout. | Delete the resource. A remaining reboot resource triggers one more time on any node that later joins the cluster. |
