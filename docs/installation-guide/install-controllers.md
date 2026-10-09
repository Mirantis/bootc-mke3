# Post-install controllers (SUC, cluster-upgrade-controller, machine-config-controller)

A default run of the [installation runbook](install-bootc-mke3.md) deploys
three additional controllers to the cluster, on top of MKE itself: the
System Upgrade Controller (SUC), `cluster-upgrade-controller`, and
`machine-config-controller`. This runbook covers what each one is, where
their versions come from, and how to verify the result. It does not cover
*using* the controllers day to day — see the
[machine configuration runbook](../operations-guide/machine-config-operations.md) for
`machine-config-controller`.

## Requirements

1. A cluster installed via the [installation runbook](install-bootc-mke3.md)
   with the default `deploy_suc`, `deploy_cluster_upgrade_controller`, and
   `deploy_machine_config_controller` flags (all `true` in
   `vars/common-vars.yml`).
2. Cluster access per the [access runbook](../operations-guide/access-cluster.md) — everything
   below uses the MKE client bundle's kubeconfig; no SSH to cluster machines
   is required.
3. `kubectl` on your workstation. No `helm` required — both controllers are
   installed from static, pre-rendered manifests.

## Procedure

### What gets deployed

| Controller | Namespace | Purpose |
|---|---|---|
| System Upgrade Controller (SUC) | `system-upgrade` | Runs the per-node `Plan` jobs that `cluster-upgrade-controller` and `machine-config-controller` both drive. Install also patches it with a control-plane-only node affinity, a longer job active-deadline, and a privileged pod-security grant for its service account. |
| `cluster-upgrade-controller` | `mke` | Reconciles `ClusterUpgrade` custom resources (whole-cluster OS + product upgrades). |
| `machine-config-controller` | `system-upgrade` (see note below) | Reconciles `MachineConfigChange` custom resources — see the [machine configuration runbook](../operations-guide/machine-config-operations.md). |

`machine-config-controller`'s manifest renders most resources into the
`mke` namespace (`vars/common-vars.yml:
machine_config_controller_namespace`), but its Deployment hardcodes
`targetNamespace: system-upgrade` internally — the deployed pod lands in
`system-upgrade` regardless. Look there, not in `mke`, when inspecting it.

### In-image sources are the source of truth

On any booted cluster node, `/usr/share/mke-controllers/` holds exactly what
that image build baked in:

- `versions.txt` — the exact image references/tags for every
  controller and upgrade-job image shipped in this build. Always read a
  controller's version from this file on a live node. Never hand-guess a
  tag, or copy one from a previous build, an example in this doc, or memory
  — a wrong reference typically doesn't fail fast, it fails only after
  burning through a long-running operation's timeout.
- `manifests/` — the literal SUC manifests, plus a static
  `cluster-upgrade-controller-manifest.yaml` and
  `machine-config-controller-manifest.yaml` for the other two controllers.
  Both are plain Kubernetes YAML — `helm template <chart> --namespace mke
  --include-crds` rendered once by bootc-mirantis at image-build time, CRDs
  included — not live Helm releases, and not templates evaluated at
  install time.

The install automation's defaults in `vars/common-vars.yml` already resolve
SUC's manifests (`suc_crd_manifest_src`, `suc_controller_manifest_src`) and
both controllers' manifests (`cluster_upgrade_controller_manifest`,
`machine_config_controller_manifest`) from a **node-fetched copy** of these
in-image sources — pulled onto the Ansible controller from a cluster node
before being applied with `kubectl apply -f`, with no separate version
pinned in Ansible that could drift from what the nodes actually have
cached.

Because each manifest was rendered with `--include-crds`, `kubectl apply`
keeps both controllers' CRDs in sync with the manifest automatically on
every run — no separate CRD-apply step, and no Helm caveat about an
already-installed release's CRDs never being touched on upgrade.

### Overriding a controller's manifest source

Both `cluster_upgrade_controller_manifest` and
`machine_config_controller_manifest` default to the node-fetched local
path above. Override either one to a URL or a different local/mirrored
path in two cases:

1. You deliberately want a controller version other than the one preloaded
   on this image build (accepts the tradeoff of an online pull, or air-gap
   it yourself).
2. `mke-post-install-playbook.yml` is being run standalone/disconnected
   from `mke-install-playbook.yml` on a different Ansible controller or
   `playbook_dir` than the one that fetched the manifest — the node-fetched
   defaults only exist under the `playbook_dir` that ran
   `mke-install-playbook.yml`.

To override, for example, `machine-config-controller`:

```sh
ansible-playbook -i <path-to-your-inventory> ansible/mke-install-playbook.yml \
  -e machine_config_controller_manifest=https://internal-mirror.example.com/machine-config-controller-manifest.yaml
```

`kubectl apply -f` accepts a URL directly, so no separate download step is
needed — point the variable at wherever the manifest you want actually
lives.

### Verify controller pod images

For every controller, confirm the running pod image matches `versions.txt`
exactly:

```sh
kubectl get deploy cluster-upgrade-controller -n mke \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deploy machine-config-controller -n system-upgrade \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deploy system-upgrade-controller -n system-upgrade \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

A mismatch (stale manifest, or an override that didn't take) is
otherwise invisible until something depending on the newer image's behavior
fails.

## Expected Results

- `kubectl get deploy -n mke` and `kubectl get deploy -n system-upgrade` show
  every controller above `Running` with `1/1` ready.
- Each pod image from the verification step matches `versions.txt` on a
  cluster node exactly.
- The relevant CRDs are present (confirm the exact spelling with
  `kubectl get crd` on your cluster): SUC's own `plans.upgrade.cattle.io`,
  `cluster-upgrade-controller`'s `clusterupgrades.upgrade.mirantis.com`, and
  `machine-config-controller`'s
  `machineconfigchanges.config.machine-config-controller.io`.

## Troubleshooting

| Symptom | Likely cause | Remediation |
|---|---|---|
| `kubectl apply` on a `MachineConfigChange` (or `ClusterUpgrade`) fails `strict decoding error: unknown field ...` | The applied manifest's CRD is older than the CR you're submitting — you overrode `*_manifest` to a version whose CRD lags | Point the override at a manifest with a matching CRD, or drop the override to fall back to the node-fetched default |
| A controller's pod image doesn't match `versions.txt` | The manifest source was overridden to a URL/mirror whose rendered image tag lags the image build | Remove the override (or point it at a manifest with the desired tag) and re-run; re-verify |
| `machine-config-controller` deployment not found in namespace `mke` | Its manifest hardcodes `targetNamespace: system-upgrade` for the Deployment; look there instead | Not a fault — expected behavior |
| Locked out of SSH and sudo on every node | `disable_sshd_after_install`/`revoke_sudo_after_install` ran during install, before the controller installs (see [install runbook](install-bootc-mke3.md#post-install-automation)) | Break-glass recovery below |

### Break-glass recovery: locked out of SSH and sudo

If a default install already ran `disable_sshd_after_install` /
`revoke_sudo_after_install`, recover access entirely through the MKE client
bundle's kubeconfig — no SSH to the node required:

```sh
export KUBECONFIG=<bundle>/kube.yml
kubectl debug node/<node-name> --image=busybox -- chroot /host /bin/sh -c '
  systemctl unmask sshd
  systemctl enable --now sshd
  usermod -aG wheel <ansible-user>
  install -d -m 0700 /etc/sudoers.d
  echo "<ansible-user> ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-cloud-init-users
  chmod 440 /etc/sudoers.d/90-cloud-init-users
'
```

`kubectl debug node/<node>` schedules a privileged pod on the target node
and tolerates the node's own readiness taints automatically, so it works
even against a node `kubectl` doesn't consider healthy. `chroot /host` gives
the debug pod's shell the node's real root filesystem. `unmask` is required
first: the hardening play masks `sshd` (links the unit to `/dev/null`), and
`enable`/`start` on a masked unit fails. Restoring wheel-group
membership alone is not sufficient — Rocky's default `%wheel` sudoers line
still prompts for a password — so the NOPASSWD drop-in above is required to
get non-interactive sudo back. Repeat for each locked-out node.

This restores the access a run with `disable_sshd_after_install: false` /
`revoke_sudo_after_install: false` would have left in place; it does not
change the `vars/common-vars.yml` defaults themselves, so re-running the
install playbook without an override reapplies the lockout.

## F.A.Q

### Can I skip installing one of these controllers?

Yes — set the relevant `deploy_suc`, `deploy_cluster_upgrade_controller`, or
`deploy_machine_config_controller` flag to `false` in
`vars/common-vars.yml` before installing. Note `cluster-upgrade-controller`
depends on SUC being present.

### Where is this documented upstream?

`cluster-upgrade-controller` and `machine-config-controller` are both
Mirantis projects with their own docs (architecture, CRD reference,
operational runbooks) in their respective repositories; SUC is
[rancher/system-upgrade-controller](https://github.com/rancher/system-upgrade-controller).
