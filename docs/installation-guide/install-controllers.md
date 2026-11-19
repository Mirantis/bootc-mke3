# Post-install controllers (SUC, cluster-upgrade-controller, machine-config-controller)

A default run of the [installation runbook](install-bootc-mke3.md) deploys
three more controllers to the cluster in addition to MKE: the
System Upgrade Controller (SUC), `cluster-upgrade-controller`, and
`machine-config-controller`. This runbook describes each controller and
where their versions come from. It also describes how to verify the
result. It does not describe how to use the controllers day to day. For
`machine-config-controller`, see the
[machine configuration runbook](../operations-guide/machine-config-operations.md).

## Requirements

1. A cluster that you installed with the [installation runbook](install-bootc-mke3.md)
   and the default `deploy_suc`, `deploy_cluster_upgrade_controller`, and
   `deploy_machine_config_controller` flags (all `true` in
   `vars/common-vars.yml`).
2. Cluster access as described in the [access runbook](../operations-guide/access-cluster.md).
   All commands below use the kubeconfig of the MKE client bundle. SSH to
   the cluster machines is not necessary.
3. `kubectl` on your workstation. `helm` is not necessary, because the install
   deploys both controllers from static, pre-rendered manifests.

## Procedure

### What gets deployed

| Controller | Namespace | Purpose |
|---|---|---|
| System Upgrade Controller (SUC) | `system-upgrade` | Runs the per-node `Plan` jobs that `cluster-upgrade-controller` and `machine-config-controller` both drive. The install also patches it with a control-plane-only node affinity, a longer job active-deadline, and a privileged pod-security grant for its service account. |
| `cluster-upgrade-controller` | `mke` | Reconciles `ClusterUpgrade` custom resources (whole-cluster OS and product upgrades). When you set `spec.product.mke3.controllersUpgrade.enabled` on that CR, it applies the manifests of all three controllers again from the newer image that the upgrade switched to. See [`mke3-controllers-upgrade`](../operations-guide/upgrade-with-controller.md#2-apply-the-clusterupgrade-cr). |
| `machine-config-controller` | `system-upgrade` (see note below) | Reconciles `MachineConfigChange` custom resources. See the [machine configuration runbook](../operations-guide/machine-config-operations.md). |

The manifest of `machine-config-controller` renders most resources into
the `mke` namespace (`vars/common-vars.yml:
machine_config_controller_namespace`). Its Deployment sets
`targetNamespace: system-upgrade` internally. Therefore the deployed pod
is in `system-upgrade`. To inspect it, look there and not in `mke`.

### In-image sources are the source of truth

On any booted cluster node, `/usr/share/mke-controllers/` contains exactly
what that image build put in the image:

- `versions.txt` contains the exact image references and tags for each
  controller and upgrade-job image in this build. Always read the version
  of a controller from this file on a live node. Do not guess a tag. Do not
  copy a tag from a previous build, from an example in this document, or
  from memory. A wrong reference does not usually fail fast. It fails only
  after the timeout of a long-running operation.
- `manifests/` contains the literal SUC manifests. It also contains a
  static `cluster-upgrade-controller-manifest.yaml` and
  `machine-config-controller-manifest.yaml` for the other two controllers.
  Both are plain Kubernetes YAML. bootc-mirantis rendered them one time at
  image-build time with `helm template <chart> --namespace mke
  --include-crds`, and they include the CRDs. They are not live Helm
  releases, and they are not templates that Ansible evaluates at install time.

The defaults of the install automation in `vars/common-vars.yml` resolve
the SUC manifests (`suc_crd_manifest_src`, `suc_controller_manifest_src`)
and the manifests of both controllers
(`cluster_upgrade_controller_manifest`,
`machine_config_controller_manifest`) from a **node-fetched copy** of
these in-image sources. The automation pulls the copy from a cluster node
onto the Ansible controller before it applies the copy with
`kubectl apply -f`. Ansible does not pin a separate version that can
differ from the version that is actually cached on the nodes.

bootc-mirantis rendered each manifest with `--include-crds`. Therefore `kubectl apply`
keeps the CRDs of both controllers in sync with the manifest
automatically on each run. A separate CRD-apply step is not necessary.
The Helm caveat does not apply. That caveat is that Helm never touches the
CRDs of an already-installed release on upgrade.

### Overriding a controller's manifest source

The defaults of `cluster_upgrade_controller_manifest` and
`machine_config_controller_manifest` are the node-fetched local path
above. Override either variable with a URL or a different local or
mirrored path in these two cases:

1. You intentionally want a controller version that is different from the
   version preloaded on this image build. You accept an online pull, or
   you make the version available in the air-gapped environment yourself.
2. You run `mke-post-install-playbook.yml` standalone or disconnected
   from `mke-install-playbook.yml`, on a different Ansible controller or
   `playbook_dir` than the one that fetched the manifest. The
   node-fetched defaults exist only under the `playbook_dir` that ran
   `mke-install-playbook.yml`.

For example, to override `machine-config-controller`:

```sh
ansible-playbook -i <path-to-your-inventory> ansible/mke-install-playbook.yml \
  -e machine_config_controller_manifest=https://internal-mirror.example.com/machine-config-controller-manifest.yaml
```

`kubectl apply -f` accepts a URL directly, so a separate download step is
not necessary. Set the variable to the location of the manifest that you
want.

### Verify controller pod images

For each controller, verify that the running pod image is exactly the
same as in `versions.txt`:

```sh
kubectl get deploy cluster-upgrade-controller -n mke \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deploy machine-config-controller -n system-upgrade \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deploy system-upgrade-controller -n system-upgrade \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

A mismatch (a stale manifest, or an override that did not take effect) is
otherwise not visible. It stays hidden until something that depends on the
behavior of the newer image fails.

## Expected Results

- `kubectl get deploy -n mke` and `kubectl get deploy -n system-upgrade` show
  that each controller above is `Running` with `1/1` ready.
- Each pod image from the verification step is exactly the same as in
  `versions.txt` on a cluster node.
- The relevant CRDs are present (use `kubectl get crd` on your cluster to
  verify the exact spelling): `plans.upgrade.cattle.io` of SUC,
  `clusterupgrades.upgrade.mirantis.com` of `cluster-upgrade-controller`,
  and `machineconfigchanges.config.machine-config-controller.io` of
  `machine-config-controller`.

## Troubleshooting

| Symptom | Likely cause | Remediation |
|---|---|---|
| `kubectl apply` on a `MachineConfigChange` (or `ClusterUpgrade`) fails with `strict decoding error: unknown field ...` | The CRD in the applied manifest is older than the CR that you submit. You overrode `*_manifest` with a version that has an older CRD | Set the override to a manifest with a matching CRD, or remove the override to use the node-fetched default |
| You applied a `ClusterUpgrade` CR with `spec.product.mke3.controllersUpgrade` **with no error**, but the `mke3-controllers-upgrade` step never runs | The CRD of the installed `cluster-upgrade-controller` is older than the field. The field first exists in `v0.1.9-tp1`/`v0.2.0` | Immediately after you apply, verify with `kubectl get clusterupgrade <name> -o jsonpath='{.spec.product.mke3.controllersUpgrade.enabled}'`. Empty output means that the CRD did not accept the field. Upgrade `cluster-upgrade-controller` first. Or, after the upgrade, apply all four baked controller manifests by hand, with `cluster-upgrade-controller` last and with `--namespace mke` (see [upgrade runbook](../operations-guide/upgrade-with-controller.md#2-apply-the-clusterupgrade-cr)) |
| The pod image of a controller is different from `versions.txt` | You overrode the manifest source with a URL or mirror whose rendered image tag is older than the image build | Remove the override (or set it to a manifest with the tag that you want). Run again. Verify again |
| `machine-config-controller` deployment not found in namespace `mke` | Its manifest sets `targetNamespace: system-upgrade` for the Deployment. Look there instead | This is not a fault. This is normal behavior |
| A `ClusterUpgrade` step (for example `mke3-backup`) stays `Upgrading` on an air-gapped cluster. Its pod in `system-upgrade` is `ErrImagePull` / `ImagePullBackOff` when it pulls `registry.mirantis.com/cluster-upgrade-controller/...`, although the image is already on the nodes | `system-upgrade/default-controller-env` has `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY: Always` (in images built before 2026-10-29), so SUC creates each Job with `imagePullPolicy: Always` | Patch the ConfigMap to `IfNotPresent` and restart SUC. See [Older images: SUC Job pull policy](airgap-bootc-mke3.md#older-images-suc-job-pull-policy) |
| Locked out of SSH and sudo on every node | `disable_sshd_after_install`/`revoke_sudo_after_install` ran during the install, before the controller installs (see [install runbook](install-bootc-mke3.md#post-install-automation)) | Do the break-glass recovery below |

### Break-glass recovery: locked out of SSH and sudo

If a default install already ran `disable_sshd_after_install` /
`revoke_sudo_after_install`, recover access only with the kubeconfig of
the MKE client bundle. SSH to the node is not necessary:

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

`kubectl debug node/<node>` schedules a privileged pod on the target node.
It automatically tolerates the readiness taints of the node. Therefore it
works even against a node that `kubectl` does not consider healthy.
`chroot /host` gives the shell of the debug pod the real root filesystem
of the node. You must do `unmask` first. The hardening play masks `sshd`
(it links the unit to `/dev/null`), and `enable`/`start` on a masked unit
fails. It is not sufficient to restore the wheel-group membership alone,
because the default `%wheel` sudoers line of Rocky still prompts for a
password. Therefore you must use the NOPASSWD drop-in above to restore
non-interactive sudo. Do this procedure again for each locked-out
node.

This procedure restores the access that a run with
`disable_sshd_after_install: false` / `revoke_sudo_after_install: false`
leaves in place. It does not change the defaults in
`vars/common-vars.yml`. If you run the install playbook again without an
override, it applies the lockout again.

## F.A.Q

### Can I skip installing one of these controllers?

Yes. Before you install, set the relevant `deploy_suc`,
`deploy_cluster_upgrade_controller`, or `deploy_machine_config_controller`
flag to `false` in `vars/common-vars.yml`. `cluster-upgrade-controller`
needs SUC to be present.

### Where is this documented upstream?

`cluster-upgrade-controller` and `machine-config-controller` are both
Mirantis projects. Each has its own documentation (architecture, CRD
reference, and operational runbooks) in its repository. SUC is
[rancher/system-upgrade-controller](https://github.com/rancher/system-upgrade-controller).
