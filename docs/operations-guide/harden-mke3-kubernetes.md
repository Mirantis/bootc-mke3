# Harden MKE3 / Kubernetes

This guide walks a system engineer through configuring a `bootc-mke3` cluster for a secure baseline, covering host hardening already built into this repo's Ansible tooling, and the additional MKE/Kubernetes-level controls needed once `cluster-upgrade-controller` and/or `machine-config-controller` are installed. It implements the mitigations from the [controller security analysis](controller-security-analysis.md) — read that document first for the *why* behind each step here.

## Prerequisites

1. A working `bootc-mke3` cluster (see [installation runbook](../installation-guide/install-bootc-mke3.md)).
2. MKE3 admin credentials and/or a Kubernetes client bundle with `cluster-admin` (client bundle from `ansible/mke-client-bundle-playbook.yml`).
3. `kubectl` and, for policy steps, [Kyverno](https://kyverno.io/) or [OPA Gatekeeper](https://open-policy-agent.github.io/gatekeeper/) installed if you intend to enforce admission policies (steps 5–6 are optional but recommended).
4. If `cluster-upgrade-controller` and/or `machine-config-controller` are deployed, know which namespace(s) they and `system-upgrade` run in (`mke` and `system-upgrade` by default per `ansible/vars/common-vars.yml`).

## Procedure

### 1. Host hardening at install time

These controls exist in the Ansible tooling already; confirm they are enabled for production clusters in `ansible/vars/common-vars.yml`:

| Variable | Recommended | Effect |
|---|---|---|
| `revoke_sudo_after_install` | `true` | Removes the Ansible connecting user from `wheel`/`sudo` and scrubs `/etc/sudoers.d/` after install — no standing sudo path remains. |
| `disable_sshd_after_install` | `true` | Stops and masks `sshd` on every node — closes remote shell access once provisioning is done, and survives reboots (a merely-disabled unit is restarted by `cloud-init.service`'s `Wants=sshd.service`). |
| `disable_firewalld` | `false` | Keeps per-service firewalld rules (`tasks/mke-open-ports-tasks.yml`) instead of opening the host to all traffic; only disable if a perimeter firewall already restricts equivalent ports. |

If SSH/console access is needed later (e.g. to run `bootc rollback` manually per the [upgrade runbook](upgrade-with-ansible.md#upgrade-rollback)), re-enable it deliberately and revoke it again afterward — do not leave it disabled from install-time policy alone as the only control.

Private registry credentials are written to `/etc/ostree/auth.json` with mode `0600`, root:root (`ansible/tasks/private-reg-creds-tasks.yml`) — verify this after install; do not widen the mode.

### 2. Re-scope MKE scheduling/privilege grants after SUC install

`ansible/tasks/suc-priv-grant-tasks.yml` runs automatically when `deploy_suc: true` (default) and, alongside the correctly-scoped `system-upgrade:system-upgrade` privileged grant, also sets two cluster-wide MKE policies broader than SUC strictly needs:

- `enable_admin_ucp_scheduling = true` — lets **all** authenticated users/service accounts schedule on manager and MSR nodes.
- `Scheduler` role granted to the `authenticated` alias on the root Swarm collection.

After confirming SUC and the controllers are healthy, review whether your MKE version supports scoping these to the SUC/controller service accounts specifically instead of "all authenticated principals," and narrow them if so:

```bash
# Inspect current grants
curl -sk -H "Authorization: Bearer $TOKEN" https://<mke_url>/api/ucp/config-toml | grep -A2 scheduling_configuration

# Review/collection grants for the authenticated alias
curl -sk -H "Authorization: Bearer $TOKEN" https://<mke_url>/collectionGrants
```

If your compliance posture requires the narrowest possible grant and MKE cannot scope `enable_admin_ucp_scheduling` per-SA, compensate with Kubernetes-level controls in steps 3–4 below, since the MKE-level toggle then becomes a secondary rather than sole control.

### 3. Restrict RBAC on the controller CRDs and `system-upgrade` namespace

Creating or editing a `ClusterUpgrade` or `MachineConfigChange`, or directly editing a `Plan` in `system-upgrade`, is root-equivalent on every node it targets (see [security analysis §1](controller-security-analysis.md#1-shared-architecture-and-trust-model)). Grant these narrowly:

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

Everyone else should only get `get`/`list`/`watch` on these resources (read-only status visibility). Grant nobody outside the two controllers' own ServiceAccounts direct write access to `plans.upgrade.cattle.io` or `secrets` in `system-upgrade`:

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

Bind `system-upgrade-viewer` to operators who need visibility; do not bind broader roles into the `system-upgrade` namespace.

### 4. Apply Pod Security Admission labels per namespace

SUC's per-node Jobs require `privileged` — confine that requirement to the `system-upgrade` namespace only; every other namespace should run at `restricted` or `baseline`:

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

Apply `restricted` cluster-wide as the default (e.g. via a `PodSecurity` admission configuration or namespace labels at creation time) and only relax `system-upgrade`.

### 5. Restrict controller metrics/health endpoints

Both controllers expose unauthenticated `:8080` (metrics) and `:8081` (health) with no `NetworkPolicy` by default. Restrict scrape access to your monitoring namespace:

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

`spec.os.image`, `spec.product.mke3.image`, `spec.product.mke4.etcdMaintenance{Image,ArtifactRef}` (cluster-upgrade-controller) accept arbitrary OCI references beyond basic pattern validation. Add an admission policy restricting them to your trusted registries, e.g. with Kyverno:

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

Similarly restrict `MachineConfigChange` `spec.kernel.sysctl` keys to a known-safe set if your compliance posture requires it (the CRD only validates key *syntax*, not semantics — see [security analysis §3.3](controller-security-analysis.md#33-what-the-generated-plans-actually-do-on-nodes)).

### 7. Enable etcd encryption at rest

Both controllers store full config payloads — including anything embedded in `dockerDaemonConfig` or `MachineConfigChange` — as plaintext CRD specs or `Secret` objects. Configure API server encryption at rest so this data is not plaintext on disk:

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

Consult [MKE's own encryption-at-rest guidance](https://docs.mirantis.com/mke/3.9/) for the supported mechanism on your MKE version before hand-editing control-plane manifests.

### 8. Enable audit logging for the escalation paths

Capture `create`/`update`/`delete`/`patch` on the two CRDs, `plans.upgrade.cattle.io`, and `secrets` in `system-upgrade` so any use of the root-equivalent path is attributable:

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

- Nodes have no standing SSH/sudo path once install-time hardening runs (step 1).
- MKE scheduling/privilege grants are scoped to what SUC actually needs, not "all authenticated principals" (step 2).
- Only an audited admin group/SA can create or edit `ClusterUpgrade`/`MachineConfigChange`/`Plan` objects; everyone else has read-only visibility (step 3).
- `system-upgrade` is the only namespace permitted to run privileged pods; all others enforce `restricted` (step 4).
- Controller metrics/health endpoints are reachable only from the monitoring namespace (step 5).
- Attacker-controlled image/artifact references are constrained to approved registries (step 6).
- Controller-managed secrets/config are encrypted at rest (step 7).
- Any create/update/delete on the escalation-capable resources is captured in the audit log (step 8).

## Ongoing operational hygiene

- Re-run the RBAC review in step 3 whenever a new team or CI/CD pipeline requests access to the cluster.
- Periodically diff the live MKE `UCPAuthorization`/scheduling config against step 2's intended scope — it can drift back to "authenticated" via unrelated MKE upgrades or config imports.
- Test the `MachineConfigChange` `.mcc-orig` manual-revert path in a non-production cluster before relying on it during an incident — there is no automatic rollback (see [security analysis R8](controller-security-analysis.md#5-consolidated-risk-register)).
- Scan both the controller and the `machine-config-controller` agent image (`Dockerfile.agent`) in your image-scanning pipeline; the agent image runs as root inside every privileged Job it drives.

## References

- [Security Analysis: Cluster Management Controllers](controller-security-analysis.md)
- [Install bootc-mke3](../installation-guide/install-bootc-mke3.md)
- [Upgrade bootc-mke3](upgrade-with-controller.md)
- [Kubernetes Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
- [Kubernetes Encrypting Secret Data at Rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/)
- [Kubernetes Auditing](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)
