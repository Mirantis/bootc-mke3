# Run privileged support containers on MKE

Support tooling for a `bootc-mke3` node runs as a privileged container on that
node: it needs the host root filesystem, the host PID namespace, and
`nsenter --target 1` to reach host binaries such as `journalctl`, `docker`, and
`bootc`. MKE 3 refuses such pods **when the identity creating them is not an
MKE admin**. This runbook grants one ServiceAccount the privilege attributes
those pods request.

Whether you need it depends on who runs the support runbooks:

| Creating identity | Grant needed? |
|---|---|
| MKE admin client bundle (what `mke-install-playbook.yml` fetches) | No — admins bypass the attribute check. |
| Any non-admin MKE user, even with Kubernetes RBAC to create pods | **Yes** — creation is refused without it. |

Run the grant if support work is ever done by non-admin operators;
skip it if every operator uses an admin bundle.

It applies to both support runbooks, which create exactly these pods:

- [Open a debug shell on a node](node-debug-shell.md)
- [Collect support bundles from nodes](collect-support-bundles.md)

## Security

**A grant made here is root-equivalent on every node the granted pods land
on.** A privileged pod with the host root filesystem mounted can read every
secret on disk, write every file, and enter every host namespace. Any user with
RBAC `create` on pods in the granted namespace inherits that reach, so treat
that permission like `cluster-admin` on the cluster's nodes, not like a
namespaced resource grant.

Consequences to accept before running the procedure:

- Grant the narrowest ServiceAccount you can, in a namespace created for this
  purpose, and keep `create pods` in it restricted to cluster administrators.
- The grant is persistent cluster configuration. It stays in effect until it is
  removed (see [Revoke the grant](#revoke-the-grant)).

## Requirements

1. An MKE 3 cluster and its URL (`mke_url` in the Ansible inventory).
2. MKE **admin** credentials — the config-toml API is admin-only.
3. A workstation with `kubectl` configured from an MKE client bundle (see
   [Access the cluster](access-cluster.md)), plus `curl`.

## What MKE refuses without the grant

MKE 3's authorization layer refuses pods from non-admin identities that request
privilege attributes unless the pod's ServiceAccount is on a cluster-level
allowlist. The refusal names both the identity and the attributes:

```text
Error from server (Forbidden): error when creating "STDIN": pods "nonadmin-probe" is
forbidden: non-admin user "7258aa56-4af3-4910-a86b-e25e5d2b24f9" [service account
"cluster-support:default"]. The configured privileged attributes access for non-admin
users ("[]")("[]") and for service accounts ("[hostbindmounts hostipc hostnetwork
hostpid kernelcapabilities privileged]")("[system-upgrade:system-upgrade]") lack
required permissions to use attributes [hostbindmounts hostpid privileged] for
resource nonadmin-probe
```

Reading it:

- `non-admin user "<uuid>"` — Kubernetes sees an MKE user as their account UUID,
  not their username.
- The two bracketed pairs are the current allowlists: attributes permitted for
  non-admin users and their subjects, then attributes permitted for service
  accounts and the subjects holding them. Here only
  `system-upgrade:system-upgrade` is granted — that entry is added by the
  install for the System Upgrade Controller.
- `attributes [hostbindmounts hostpid privileged]` is what the pod asked for:
  a `hostPath` volume, `spec.hostPID: true`, and a privileged container.

Upstream reference:
[admission controllers for access control](https://docs.mirantis.com/mke/3.9/ops/deploy-apps-k8s/admission-controllers-for-access.html).

## Procedure

### 1. Create the namespace

Both support runbooks use the namespace `cluster-support` and its default
ServiceAccount, so the grant covers exactly one identity:

```sh
kubectl create namespace cluster-support
```

### 2. Grant the privilege attributes

The allowlist lives in the MKE cluster configuration TOML, reachable only
through the `/api/ucp/config-toml` API. Download it, add the ServiceAccount,
and upload it back.

```sh
export MKE_URL=<mke-host-or-ip>          # no scheme
export MKE_USER=admin
export MKE_PASS=<password>
export SA_ENTRY=cluster-support:default   # <namespace>:<serviceaccount>

# 1. Authenticate — returns a bearer token
export TOKEN=$(curl -sk -X POST "https://${MKE_URL}/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${MKE_USER}\",\"password\":\"${MKE_PASS}\"}" | jq -r .auth_token)

# 2. Download the current cluster config
curl -sk -H "Authorization: Bearer ${TOKEN}" \
  -o mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"
```

Edit `mke-config.toml`. In the `[cluster_config]` section, ensure both keys
below exist and contain the listed values, creating either key if it is absent
and **preserving any entries already present**:

```toml
[cluster_config]
  priv_attributes_allowed_for_service_accounts = ["hostIPC", "hostNetwork", "hostPID", "hostBindMounts", "privileged", "kernelCapabilities"]
  priv_attributes_service_accounts = ["system-upgrade:system-upgrade", "cluster-support:default"]
```

- `priv_attributes_allowed_for_service_accounts` — the attributes that may be
  granted at all. These six are every attribute the admission controller
  supports, and a default `bootc-mke3` install already sets all six.
- `priv_attributes_service_accounts` — the `<namespace>:<serviceaccount>`
  entries that may use them. **Append** `cluster-support:default`; a default
  install already contains `system-upgrade:system-upgrade` for the System
  Upgrade Controller, and overwriting the array revokes that grant. The example
  above shows the merged result.

Upload the edited file:

```sh
# 3. Upload the modified cluster config
curl -sk -X PUT -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/toml" \
  --data-binary @mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"

rm -f mke-config.toml     # the file is cluster configuration, not a secret, but do not keep stale copies
```

> Use `-k`/`--insecure` only while MKE still serves its self-signed
> certificate; drop it once MKE has a trusted certificate installed.

The change takes effect on the next admission decision; no MKE restart is
required: a creation refused seconds earlier succeeds on the first retry after
the `PUT` returns 200, and the pre-existing `system-upgrade:system-upgrade`
entry survives the edit.

### 3. Verify the grant

Create a pod that requests all three attributes on a real node and check that
admission accepts it. Substitute any node name from `kubectl get nodes`:

```sh
kubectl -n cluster-support run grant-check --image=mirantis/ucp-dsinfo:3.9.7 --restart=Never \
  --overrides='{"spec":{"nodeName":"<any-node-name>","hostPID":true,"containers":[{"name":"grant-check","image":"mirantis/ucp-dsinfo:3.9.7","command":["true"],"securityContext":{"privileged":true},"volumeMounts":[{"name":"h","mountPath":"/host"}]}],"volumes":[{"name":"h","hostPath":{"path":"/"}}]}}'
kubectl -n cluster-support delete pod grant-check
```

Creation succeeding — rather than being refused with the error above — proves the
grant. The pod runs `true` and exits.

## Expected Results

- The `grant-check` pod in step 3 is created instead of denied.
- The support pods in [node-debug-shell.md](node-debug-shell.md) and
  [collect-support-bundles.md](collect-support-bundles.md) start on their
  target nodes.

## Automated alternative

This repository already automates the same two API calls for the System Upgrade
Controller: `ansible/tasks/suc-priv-grant-tasks.yml` fetches the config TOML,
runs `ansible/tasks/helpers/suc_priv_grant.py <config.toml> <namespace:sa>`,
and PUTs the result. The helper is idempotent and merges rather than
overwrites, so it is the safer way to edit the arrays by hand as well:

```sh
curl -sk -H "Authorization: Bearer ${TOKEN}" \
  -o mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"
python3 ansible/tasks/helpers/suc_priv_grant.py mke-config.toml cluster-support:default
curl -sk -X PUT -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/toml" \
  --data-binary @mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"
```

Two differences from running the playbook:

- The playbook grants `suc_service_account` (from
  `ansible/vars/common-vars.yml`), not `cluster-support:default`. Pass the
  ServiceAccount you want as the helper's second argument.
- The helper also sets `enable_admin_ucp_scheduling = true` in
  `[scheduling_configuration]`. The support pods in these runbooks do not need
  it: they set `spec.nodeName` directly, which bypasses the Kubernetes
  scheduler and therefore MKE's scheduling restrictions on manager nodes. The
  key is harmless but is a real cluster-wide change — if you do not want it,
  edit the TOML by hand as in step 2 instead.

## Revoke the grant

Remove `cluster-support:default` from `priv_attributes_service_accounts` and
PUT the TOML back, then delete the namespace:

```sh
kubectl delete namespace cluster-support
```

Leaving `priv_attributes_allowed_for_service_accounts` populated is harmless on
its own — it lists what *may* be granted; without an entry in
`priv_attributes_service_accounts` no ServiceAccount can use it.

## F.A.Q

### I am an MKE admin — do I need this at all?

No. With an admin client bundle, the debug shell Pods and the capture Jobs of
both support runbooks are created and run with only
`system-upgrade:system-upgrade` on the allowlist. Capture Jobs are no exception
— the pods the Job controller creates are not subject to the non-admin check
either.

Apply the grant when support work is done by non-admin MKE users. Those
operators are refused without it even when Kubernetes RBAC already lets them
create pods in the namespace.

### Does this need the MKE Scheduler grant too?

No. Every support pod in these runbooks pins itself with `spec.nodeName`, so the
scheduler is not involved, and a `NoSchedule` taint — MKE 3 taints managers with
`com.docker.ucp.manager:NoSchedule` — cannot keep a pinned pod off its node.
The manifests still carry a key-less `operator: Exists` toleration, which covers
every taint including `NoExecute`, the one effect that would evict a pinned pod.

### Why not a Kubernetes PSA label or a PodSecurityPolicy?

MKE 3's own admission controller runs in addition to Kubernetes pod security
admission and is configured only through the cluster config TOML. Relaxing PSA
on the namespace does not satisfy it.
