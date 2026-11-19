# Access the cluster (kubectl and Docker Swarm)

This runbook shows how to connect to a running `bootc-mke3`
MKE 3 cluster from the command line. It covers the Kubernetes API (`kubectl`) and the Docker Swarm
socket (`docker`). Use the **MKE client bundle**. Several other runbooks, for
example the [mixed cluster runbook](mixed-cluster.md), list this access as a
prerequisite.

The client bundle is a zip file that MKE issues. It contains TLS certificates
for one user and ready-made configuration: `kube.yml` (a kubeconfig) and
`env.sh` (environment setup that points `docker` at the cluster). The cluster
authenticates and authorizes access as the MKE user that downloaded the bundle.

## Requirements

1. A running MKE 3 cluster and its URL (`mke_url` in the ansible inventory).
2. MKE user credentials. You set admin credentials at install time in
   `ansible/vars/mke-creds.yml`, or you pass them with `-e admin_user=... -e admin_pass=...`
   (there is no default). See the
   [installation runbook](../installation-guide/install-bootc-mke3.md).
3. On your workstation: `kubectl` or the `docker` CLI, or both. For the API
   download path, you also need `curl`, `jq`, and `unzip`.

## Procedure

### Option 1 — Fetch the bundle with the provided Ansible playbook

If you still have the Ansible inventory that you used to install the cluster,
this playbook automates option 2 below (retries, correct headers, cleanup).
Other playbooks in this repository use the same path internally
(`cluster-upgrade-controller`/`machine-config-controller` install tasks):

```sh
cd ansible
ansible-playbook -i <path-to-your-inventory> mke-client-bundle-playbook.yml
# bundle extracted to ansible/mke-bundle/ by default; override with -e bundle_dest=<path>
```
### Option 2 — Download the bundle from the MKE UI

1. Log in to the MKE web UI (`https://<mke_url>`).
2. Navigate to **My Profile** → **Client Bundles** → **New Client Bundle**.
3. Save and unzip the bundle.

### Option 3 — Download the bundle via the API

```sh
export MKE_URL=<mke-host-or-ip>          # no scheme
export MKE_USER=admin
export MKE_PASS=<password>

# 1. Authenticate — returns a bearer token
export TOKEN=$(curl -sk -X POST "https://${MKE_URL}/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${MKE_USER}\",\"password\":\"${MKE_PASS}\"}" | jq -r .auth_token)

# 2. Download and extract the bundle
curl -sk -H "Authorization: Bearer ${TOKEN}" \
  -o bundle.zip "https://${MKE_URL}/api/clientbundle"
mkdir -p mke-bundle && unzip -q bundle.zip -d mke-bundle && cd mke-bundle
```

> Use `-k`/`--insecure` only while MKE uses its self-signed
> certificate. Remove it when MKE has a trusted certificate installed.


### Use kubectl (Kubernetes API)

The bundle contains a complete kubeconfig (`kube.yml`):

```sh
export KUBECONFIG=$PWD/kube.yml
kubectl config current-context     # context name starts with ucp_
kubectl get nodes
```

### Use docker (Swarm socket)

The bundle contains `env.sh`. This script points the `docker` CLI at the cluster
with the TLS client certificates of the bundle. It sets `DOCKER_HOST` and
`DOCKER_CERT_PATH`, and it also configures kubectl:

```sh
eval "$(<env.sh)"
docker version --format '{{.Server.Version}}'        # starts with ucp/
docker node ls          # swarm-level view of the cluster
```

To return the `docker` CLI to your local daemon, do this:

```sh
unset DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH
```

## Expected Results

- `kubectl get nodes` lists every cluster machine as `Ready`.
- `docker node ls` lists all machines with their swarm roles. Use this view to
  verify [no-touch joins](join-machines-no-touch.md).

## F.A.Q

### Does the bundle expire?

Since MKE 3.9.0, you can configure the expiration of the client bundle. An
admin can set a maximum lifetime. After this time, the certificates of the
bundle stop working. See
[client bundle expiration](https://docs.mirantis.com/mke/3.9/ops/access-cluster/client-bundle/client-bundle-expiration.html).
Expiration is a separate control. A bundle stays tied to its MKE user, and you
can revoke it at any time (My Profile → Client Bundles). A cluster CA rotation
also makes the bundle invalid. Revoke the bundles of users that leave.

### Do I need SSH to any cluster machine?

No. All access goes through the MKE endpoint over TLS. This is consistent with
clusters that disable SSH after install (see
[no-touch join](no-touch-join.md)).

### Where is this documented upstream?

This is the MKE client bundle reference:
https://docs.mirantis.com/mke/3.9/ops/access-cluster/download-configure-client-bundle.html
