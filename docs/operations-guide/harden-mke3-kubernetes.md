# Harden MKE3 / Kubernetes

This guide shows a system engineer how to configure a `bootc-mke3` cluster for a secure baseline. It covers the host hardening that is already built into the Ansible tooling of this repository. It also covers the additional MKE and Kubernetes controls that are necessary after `cluster-upgrade-controller` and/or `machine-config-controller` are installed. It implements the mitigations from the [controller security analysis](controller-security-analysis.md). Read that document first to understand the *why* behind each step here.

## Prerequisites

1. A working `bootc-mke3` cluster (see [installation runbook](../installation-guide/install-bootc-mke3.md)).
2. MKE3 admin credentials and/or a Kubernetes client bundle with `cluster-admin` (the client bundle is from `ansible/mke-client-bundle-playbook.yml`).
3. `kubectl` and, for the policy steps, [Kyverno](https://kyverno.io/) or [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/) installed, if you want to enforce admission policies (steps 5–6 are optional, but we recommend them).
4. If `cluster-upgrade-controller` and/or `machine-config-controller` are deployed, find the namespaces in which they and `system-upgrade` run (`mke` and `system-upgrade` by default, per `ansible/vars/common-vars.yml`).

## Procedure

### 1. Host hardening at install time

These controls already exist in the Ansible tooling. Make sure that they are enabled for production clusters in `ansible/vars/common-vars.yml`:

| Variable | Recommended | Effect |
|---|---|---|
| `revoke_sudo_after_install` | `true` | Removes the Ansible connecting user from `wheel`/`sudo` and scrubs `/etc/sudoers.d/` after install. No standing sudo path remains. |
| `disable_sshd_after_install` | `true` | Stops and masks `sshd` on every node. This closes remote shell access after provisioning, and it survives reboots (`cloud-init.service` has `Wants=sshd.service` and restarts a unit that is only disabled). |
| `disable_firewalld` | `false` | Keeps per-service firewalld rules (`tasks/mke-open-ports-tasks.yml`) instead of opening the host to all traffic. Disable it only if a perimeter firewall already restricts the equivalent ports. |

If you need SSH or console access later (for example, to run `bootc rollback` manually, as the [upgrade runbook](upgrade-with-ansible.md#upgrade-rollback) describes), re-enable it deliberately. Revoke it again afterward. Do not depend on the install-time policy as the only control.

Private registry credentials are written to `/etc/ostree/auth.json` with mode `0600`, root:root (`ansible/tasks/private-reg-creds-tasks.yml`). Verify this after the install. Do not widen the mode.

### 2. Re-scope MKE scheduling/privilege grants after SUC install

`ansible/tasks/suc-priv-grant-tasks.yml` runs automatically when `deploy_suc: true` (default). It sets the correctly-scoped `system-upgrade:system-upgrade` privileged grant. It also sets two cluster-wide MKE policies that are broader than SUC needs:

- `enable_admin_ucp_scheduling = true`. This lets **all** authenticated users and service accounts schedule on manager and MSR nodes.
- The `Scheduler` role is granted to the `authenticated` alias on the root Swarm collection.

Check if your MKE version can scope these grants to the SUC and controller service accounts instead of "all authenticated principals". Do this after you confirm that SUC and the controllers are healthy. If it can, narrow them:

```bash
# Inspect current grants
curl -sk -H "Authorization: Bearer $TOKEN" https://<mke_url>/api/ucp/config-toml | grep -A2 scheduling_configuration

# Review/collection grants for the authenticated alias
curl -sk -H "Authorization: Bearer $TOKEN" https://<mke_url>/collectionGrants
```

If your compliance posture requires the narrowest possible grant and MKE cannot scope `enable_admin_ucp_scheduling` for each SA, compensate with the controls in steps 3–4 below. These Kubernetes-level controls make the MKE-level toggle a secondary control and not the only control.

### 3. Restrict RBAC on the controller CRDs and `system-upgrade` namespace

Any user who can create or edit a `ClusterUpgrade` or `MachineConfigChange` has root-equivalent access on every node that the object targets. A direct edit of a `Plan` in `system-upgrade` gives the same access (see [security analysis §1](controller-security-analysis.md#1-shared-architecture-and-trust-model)). Grant these permissions narrowly:

```yaml
# cluster-upgrade-admin.yaml — grant only to a small, audited group/SA
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cluster-upgrade-admin
rules:
  - apiGroups: ["upgrade.mirantis.com"]
    resources: ["clusterupgrades", "clusterupgrades/status"]
    verbs: ["create", "update", "patch", "delete"]
  - apiGroups: ["config.machine-config-controller.io"]
    resources: ["machineconfigchanges", "machineconfigchanges/status"]
    verbs: ["create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cluster-upgrade-admin-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-upgrade-admin
subjects:
  - kind: Group          # or ServiceAccount, for GitOps controllers
    name: <your-cluster-admins-group>
    apiGroup: rbac.authorization.k8s.io
```

We recommend that everyone else gets only `get`, `list` and `watch` on these resources (read-only status visibility). Give nobody outside the ServiceAccounts of the two controllers direct write access to `plans.upgrade.cattle.io` or `secrets` in `system-upgrade`:

```yaml
# system-upgrade-lockdown.yaml — deny-by-default via scoped Role, no cluster-admin bindings into this namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: system-upgrade-viewer
  namespace: system-upgrade
rules:
  - apiGroups: ["upgrade.cattle.io"]
    resources: ["plans"]
    verbs: ["get", "list", "watch"]
```

Bind `system-upgrade-viewer` to operators who need visibility. Do not bind broader roles into the `system-upgrade` namespace.

### 4. Apply Pod Security Admission labels per namespace

The per-node Jobs of SUC require `privileged`. Confine that requirement to the `system-upgrade` namespace only. We recommend that every other namespace runs at `restricted` or `baseline`:

```bash
kubectl label ns system-upgrade \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged --overwrite

# controller namespace(s) — the controllers themselves need no elevated PSA level
kubectl label ns mke \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted --overwrite
```

Apply `restricted` cluster-wide as the default (for example, with a `PodSecurity` admission configuration or namespace labels at creation time). Relax only `system-upgrade`.

### 5. Restrict controller metrics/health endpoints

Both controllers expose unauthenticated `:8080` (metrics) and `:8081` (health) and have no `NetworkPolicy` by default. Restrict scrape access to your monitoring namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-controller-metrics
  namespace: mke
spec:
  podSelector:
    matchExpressions:
      - key: app.kubernetes.io/name
        operator: In
        values: ["cluster-upgrade-controller", "machine-config-controller"]
  policyTypes: ["Ingress"]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 8080
        - port: 8081
```

### 6. Enforce an image/content allowlist on attacker-influenced fields

The fields `spec.os.image`, `spec.product.mke3.image`, and `spec.product.mke4.etcdMaintenance{Image,ArtifactRef}` (cluster-upgrade-controller) accept arbitrary OCI references beyond basic pattern validation. Add an admission policy that restricts them to your trusted registries, for example with Kyverno:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-clusterupgrade-images
spec:
  validationFailureAction: Enforce
  rules:
    - name: allowed-registries
      match:
        resources:
          kinds: ["ClusterUpgrade"]
      validate:
        message: "os/mke3 image refs must come from an approved registry"
        pattern:
          spec:
            =(os):
              image: "registry.mirantis.com/* | registry.ci.mirantis.com/*"
            =(product):
              =(mke3):
                image: "registry.mirantis.com/* | registry.ci.mirantis.com/*"
```

In the same way, restrict the `MachineConfigChange` `spec.kernel.sysctl` keys to a known-safe set if your compliance posture requires it. The CRD validates only the key *syntax* and not the semantics (see [security analysis §3.3](controller-security-analysis.md#33-what-the-generated-plans-actually-do-on-nodes)).

### 7. Enable etcd encryption at rest

Both controllers store full config payloads as plaintext CRD specs or `Secret` objects. This includes anything embedded in `dockerDaemonConfig` or `MachineConfigChange`. Configure API server encryption at rest so that this data is not plaintext on disk:

```yaml
# /etc/kubernetes/encryption-config.yaml (path depends on your control-plane setup)
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-32-byte-key>
      - identity: {}
```

Before you edit the control-plane manifests by hand, read [MKE's own encryption-at-rest guidance](https://docs.mirantis.com/mke/3.9/) for the supported mechanism on your MKE version.

### 8. Enable audit logging for the escalation paths

Capture `create`, `update`, `delete` and `patch` on the two CRDs, `plans.upgrade.cattle.io`, and `secrets` in `system-upgrade`, so that any use of the root-equivalent path is attributable:

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: RequestResponse
    namespaces: ["system-upgrade"]
    resources:
      - group: "upgrade.cattle.io"
        resources: ["plans"]
      - group: ""
        resources: ["secrets"]
  - level: RequestResponse
    resources:
      - group: "upgrade.mirantis.com"
        resources: ["clusterupgrades"]
      - group: "config.machine-config-controller.io"
        resources: ["machineconfigchanges"]
```

## Expected Results

- Nodes have no standing SSH/sudo path after install-time hardening runs (step 1).
- MKE scheduling and privilege grants are scoped to what SUC needs, and not to "all authenticated principals" (step 2).
- Only an audited admin group or SA can create or edit `ClusterUpgrade`, `MachineConfigChange` and `Plan` objects. Everyone else gets read-only visibility (step 3).
- `system-upgrade` is the only namespace that is permitted to run privileged pods. All other namespaces enforce `restricted` (step 4).
- Controller metrics/health endpoints are reachable only from the monitoring namespace (step 5).
- Attacker-controlled image and artifact references are limited to approved registries (step 6).
- Secrets and config that the controllers manage are encrypted at rest (step 7).
- Any create, update or delete on the resources that can escalate privilege is captured in the audit log (step 8).

## Ongoing operational hygiene

- Do the RBAC review in step 3 again when a new team or CI/CD pipeline requests access to the cluster.
- Periodically compare the live MKE `UCPAuthorization` and scheduling config with the intended scope of step 2. It can drift back to "authenticated" through unrelated MKE upgrades or config imports.
- Test the manual-revert path of `MachineConfigChange` (`.mcc-orig`) in a non-production cluster before you rely on it during an incident. There is no automatic rollback (see [security analysis R8](controller-security-analysis.md#5-consolidated-risk-register)).
- Scan both the controller image and the `machine-config-controller` agent image (`Dockerfile.agent`) in your image-scanning pipeline. The agent image runs as root inside every privileged Job that it drives.

## References

- [Security Analysis: Cluster Management Controllers](controller-security-analysis.md)
- [Install bootc-mke3](../installation-guide/install-bootc-mke3.md)
- [Upgrade bootc-mke3](upgrade-with-controller.md)
- [Kubernetes Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
- [Kubernetes Encrypting Secret Data at Rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
- [Kubernetes Auditing](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)
