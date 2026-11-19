# Run privileged support containers on MKE

Support tooling for a `bootc-mke3` node runs as a privileged container on that
node. The container needs the host root filesystem, the host PID namespace,
and `nsenter --target 1` to reach host binaries such as `journalctl`,
`docker`, and `bootc`. MKE 3 refuses such pods **when the identity that creates
them is not an MKE admin**. This runbook gives one ServiceAccount the privilege
attributes that those pods request.

The identity that runs the support runbooks decides if you need the grant:

| Creating identity | Grant needed? |
|---|---|
| MKE admin client bundle (what `mke-install-playbook.yml` fetches) | No. Admins bypass the attribute restriction. |
| Any non-admin MKE user, even with Kubernetes RBAC to create pods | **Yes**. MKE refuses the creation without the grant. |

Apply the grant if non-admin operators do support work. Skip it if every
operator uses an admin bundle.

The grant applies to both support runbooks. These runbooks create exactly these
pods:

- [Open a debug shell on a node](node-debug-shell.md)
- [Collect support bundles from nodes](collect-support-bundles.md)

## Security

**A grant made with this runbook is root-equivalent on every node where the
granted pods start.** A privileged pod with the host root filesystem mounted
can read every secret on disk, write every file, and enter every host
namespace. Any user with RBAC `create` on pods in the granted namespace has the
same reach. Treat that permission as `cluster-admin` on the nodes of the
cluster, not as a namespaced resource grant.

Accept these consequences before you do the procedure:

- Grant the narrowest ServiceAccount possible, in a namespace created for this
  purpose. Restrict `create pods` in that namespace to cluster administrators.
- The grant is persistent cluster configuration. It stays in effect until you
  delete it (see [Revoke the grant](#revoke-the-grant)).

## Requirements

1. An MKE 3 cluster and its URL (`mke_url` in the Ansible inventory).
2. MKE **admin** credentials. The config-toml API is only for admins.
3. A workstation with `kubectl` configured from an MKE client bundle (see
   [Access the cluster](access-cluster.md)), plus `curl`.

## What MKE refuses without the grant

The authorization layer of MKE 3 refuses pods from non-admin identities that
request privilege attributes. The exception is a pod whose ServiceAccount is on
a cluster-level allowlist. The refusal names the identity and the attributes:

```text
Error from server (Forbidden): error when creating "STDIN": pods "nonadmin-probe" is
forbidden: non-admin user "7258aa56-4af3-4910-a86b-e25e5d2b24f9" [service account
"cluster-support:default"]. The configured privileged attributes access for non-admin
users ("[]")("[]") and for service accounts ("[hostbindmounts hostipc hostnetwork
hostpid kernelcapabilities privileged]")("[system-upgrade:system-upgrade]") lack
required permissions to use attributes [hostbindmounts hostpid privileged] for
resource nonadmin-probe
```

Description of the message:

- `non-admin user "<uuid>"`: Kubernetes identifies an MKE user by the account
  UUID, not by the username.
- The two bracketed pairs are the current allowlists. The first pair gives the
  attributes permitted for non-admin users and their subjects. The second pair
  gives the attributes permitted for service accounts and the subjects that
  hold them. In this example, only `system-upgrade:system-upgrade` has a grant.
  The installation adds that entry for the System Upgrade Controller.
- `attributes [hostbindmounts hostpid privileged]` is what the pod requested:
  a `hostPath` volume, `spec.hostPID: true`, and a privileged container.

Upstream reference:
[admission controllers for access control](https://docs.mirantis.com/mke/3.9/ops/deploy-apps-k8s/admission-controllers-for-access.html).

## Procedure

### 1. Create the namespace

Both support runbooks use the namespace `cluster-support` and its default
ServiceAccount. Therefore the grant covers exactly one identity:

```sh
kubectl create namespace cluster-support
```

### 2. Grant the privilege attributes

The allowlist is in the MKE cluster configuration TOML. You can reach it only
through the `/api/ucp/config-toml` API. Download the TOML, add the
ServiceAccount, and upload the TOML again.

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

Edit `mke-config.toml`. In the `[cluster_config]` section, make sure that both
keys below exist and contain the listed values. Create a key if it is absent.
**Keep all entries that are already present**:

```toml
[cluster_config]
  priv_attributes_allowed_for_service_accounts = ["hostIPC", "hostNetwork", "hostPID", "hostBindMounts", "privileged", "kernelCapabilities"]
  priv_attributes_service_accounts = ["system-upgrade:system-upgrade", "cluster-support:default"]
```

- `priv_attributes_allowed_for_service_accounts`: the attributes that you can
  grant. These six attributes are all the attributes that the admission
  controller supports. A default `bootc-mke3` installation already sets all
  six.
- `priv_attributes_service_accounts`: the `<namespace>:<serviceaccount>`
  entries that can use the attributes. **Append** `cluster-support:default`.
  A default installation already contains `system-upgrade:system-upgrade` for
  the System Upgrade Controller. If you overwrite the array, you revoke that
  grant. The example above shows the merged result.

Upload the edited file:

```sh
# 3. Upload the modified cluster config
curl -sk -X PUT -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/toml" \
  --data-binary @mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"

rm -f mke-config.toml     # the file is cluster configuration, not a secret, but do not keep stale copies
```

> Use `-k`/`--insecure` only while MKE uses its self-signed certificate.
> Delete the option when MKE has a trusted certificate.

The change takes effect at the next admission decision. You do not need to
restart MKE. A creation that MKE refused seconds before succeeds at the first
retry after the `PUT` returns 200. The existing `system-upgrade:system-upgrade`
entry stays after the edit.

### 3. Verify the grant

Create a pod that requests all three attributes on a real node. Verify that
admission accepts the pod. Use any node name from `kubectl get nodes`:

```sh
kubectl -n cluster-support run grant-check --image=mirantis/ucp-dsinfo:3.9.7 --restart=Never \
  --overrides='{"spec":{"nodeName":"<any-node-name>","hostPID":true,"containers":[{"name":"grant-check","image":"mirantis/ucp-dsinfo:3.9.7","command":["true"],"securityContext":{"privileged":true},"volumeMounts":[{"name":"h","mountPath":"/host"}]}],"volumes":[{"name":"h","hostPath":{"path":"/"}}]}}'
kubectl -n cluster-support delete pod grant-check
```

A successful creation proves the grant. MKE does not refuse the pod with the
error above. The pod runs `true` and exits.

## Expected Results

- MKE creates the `grant-check` pod in step 3 and does not deny it.
- The support pods in [node-debug-shell.md](node-debug-shell.md) and
  [collect-support-bundles.md](collect-support-bundles.md) start on their
  target nodes.

## Automated alternative

This repository already automates the same two API calls for the System Upgrade
Controller. `ansible/tasks/suc-priv-grant-tasks.yml` fetches the config TOML,
runs `ansible/tasks/helpers/suc_priv_grant.py <config.toml> <namespace:sa>`,
and sends the result with PUT. The helper is idempotent and it merges the
arrays instead of overwriting them. Therefore it is also the safer way to edit
the arrays outside the playbook:

```sh
curl -sk -H "Authorization: Bearer ${TOKEN}" \
  -o mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"
python3 ansible/tasks/helpers/suc_priv_grant.py mke-config.toml cluster-support:default
curl -sk -X PUT -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/toml" \
  --data-binary @mke-config.toml "https://${MKE_URL}/api/ucp/config-toml"
```

The helper differs from the playbook in two ways:

- The playbook grants `suc_service_account` (from
  `ansible/vars/common-vars.yml`), not `cluster-support:default`. Give the
  ServiceAccount that you want as the second argument of the helper.
- The helper also sets `enable_admin_ucp_scheduling = true` in
  `[scheduling_configuration]`. The support pods in these runbooks do not need
  this key. They set `spec.nodeName` directly. This bypasses the Kubernetes
  scheduler and therefore the scheduling restrictions of MKE on manager nodes.
  The key is harmless, but it is a real cluster-wide change. If you do not want
  it, edit the TOML by hand as in step 2.

## Revoke the grant

Delete `cluster-support:default` from `priv_attributes_service_accounts`. Send
the TOML back with PUT. Then delete the namespace:

```sh
kubectl delete namespace cluster-support
```

It is harmless to keep `priv_attributes_allowed_for_service_accounts`
populated. It lists what you *can* grant. Without an entry in
`priv_attributes_service_accounts`, no ServiceAccount can use the attributes.

## F.A.Q

### I am an MKE admin — do I need this at all?

No. With an admin client bundle, both support runbooks create and run their
debug shell Pods and capture Jobs. The allowlist needs only
`system-upgrade:system-upgrade`. Capture Jobs are not an exception. The
non-admin restriction does not apply to the pods that the Job controller creates.

Apply the grant when non-admin MKE users do support work. MKE refuses those
operators without the grant, even when Kubernetes RBAC lets them create pods in
the namespace.

### Does this need the MKE Scheduler grant too?

No. Every support pod in these runbooks pins itself with `spec.nodeName`.
Therefore the scheduler is not involved. A `NoSchedule` taint cannot keep a
pinned pod off its node. MKE 3 taints managers with
`com.docker.ucp.manager:NoSchedule`. The manifests also have a key-less
`operator: Exists` toleration. It covers every taint, including `NoExecute`,
which is the one effect that can evict a pinned pod.

### Why not a Kubernetes PSA label or a PodSecurityPolicy?

The admission controller of MKE 3 runs in addition to the Kubernetes pod
security admission. You configure it only through the cluster config TOML. A
relaxed PSA on the namespace does not satisfy the MKE admission controller.
