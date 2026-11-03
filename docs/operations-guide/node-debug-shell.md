# Open a debug shell on a node

How to get a root shell on a `bootc-mke3` node through the Kubernetes API,
without SSH. A privileged container pinned to the node gives access to the
host's filesystem, process table, and namespaces — the operations a `bootc`
node's immutable, SSH-less design otherwise makes awkward.

Two paths are documented: `kubectl debug` for one node, and a Pod manifest for
several nodes at once or for options `kubectl debug` does not expose.

## Security

A debug shell created here is **root-equivalent on the node it lands on**. The
container is privileged and mounts the host root filesystem at `/host`, so it
can read every secret on disk and enter every host namespace. Treat the ability
to create these pods as `cluster-admin` on the cluster's nodes, and delete the
pods when the investigation is over — nothing expires them.

## Requirements

1. `kubectl` configured from an MKE client bundle — see
   [Access the cluster](access-cluster.md).
2. If support work is done by non-admin MKE users: the privilege grant from
   [Run privileged support containers on MKE](privileged-support-containers.md).
   An MKE admin client bundle does not need it, but a
   non-admin user is refused without it. Either way you need the
   `cluster-support` namespace that runbook creates.
3. `envsubst` (package `gettext`/`gettext-base`) on your workstation, for the
   multi-node path.
4. The cluster's MKE version, for the image tag. With the client bundle's
   `env.sh` sourced (see [Access the cluster](access-cluster.md#use-docker-swarm-socket)),
   the Swarm socket reports it:

   ```sh
   docker version --format '{{.Server.Version}}'    # e.g. ucp/3.9.7 → tag 3.9.7
   ```

   The MKE UI also shows it (**Admin Settings**), and on a node itself the
   `ucp-proxy` container carries it as the label
   `com.docker.ucp.version`.

   The image used below, `mirantis/ucp-dsinfo`, is MKE's own troubleshooting
   image on Docker Hub, tagged by MKE version; it already contains `bash`,
   `nsenter`, `curl`, `jq`, `tar`, and the `docker` CLI. In an air-gapped
   cluster, mirror `mirantis/ucp-dsinfo:<MKE version>` into the local registry
   first and use that reference instead.

## Procedure

### Option 1 — One node, with `kubectl debug`

`kubectl debug` builds the same kind of pod itself. The `sysadmin` profile
makes the container privileged, and the node debugger always pins the pod to
the target node, shares the host namespaces, and mounts the host root
filesystem at `/host`:

```sh
kubectl debug node/<node-name> -it -n cluster-support \
  --profile=sysadmin \
  --image=mirantis/ucp-dsinfo:3.9.7 \
  -- bash
```

- `-n cluster-support` is required, not cosmetic: the pod runs as that
  namespace's `default` ServiceAccount, which is the identity the privilege
  grant covers. Without it the pod lands in `default`, which is not granted.
- kubectl prints a warning that the generated pod name is not a DNS label
  (`must be no more than 63 characters must not contain dots`) whenever the node
  name is an FQDN, as it is on AWS. It is noise from kubectl's own naming, not a
  failure; the pod runs.
- The pod is **not** deleted when you exit. Remove it explicitly:

  ```sh
  kubectl -n cluster-support get pods            # find node-debugger-<node>-xxxxx
  kubectl -n cluster-support delete pod node-debugger-<node>-xxxxx
  ```

Upstream reference:
[debugging a node with kubectl debug](https://kubernetes.io/docs/tasks/debug/debug-cluster/kubectl-node-debug/).

With an admin bundle the generated pod reaches `Running`, and
`cat /host/etc/redhat-release` inside it prints the node's Rocky Linux release. If your MKE version refuses the pod `kubectl debug` generates, use
option 2 — the manifest is explicit about every attribute it requests.

### Option 2 — One or many nodes, with a manifest

The template
[`debug-shell-pod.yaml.tmpl`](../examples/cluster-support/debug-shell-pod.yaml.tmpl)
takes two `envsubst` variables: `${NODE_NAME}` (the node to pin to) and
`${NODE_SLUG}` (the same name with dots replaced by dashes, used for the pod
name — a pod name containing dots becomes the pod's hostname and kubectl warns
about it, and AWS node names are FQDNs). Edit the image tag in the template once
to match your MKE version, then fan out over any node selector:

```sh
cd docs/examples/cluster-support

render() {   # $1 = node name
  NODE_NAME="$1" NODE_SLUG="$(printf '%s' "$1" | tr '.' '-')" \
    envsubst < debug-shell-pod.yaml.tmpl
}

# One node
render <node-name> | kubectl apply -f -

# Every manager node.
# MKE 3 labels managers node-role.kubernetes.io/master, not
# .../control-plane — check with: kubectl get nodes --show-labels
for node in $(kubectl get nodes -l node-role.kubernetes.io/master -o jsonpath='{.items[*].metadata.name}'); do
  render "$node" | kubectl apply -f -
done

# Every node
for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  render "$node" | kubectl apply -f -
done
```

Wait for them and attach to one:

```sh
kubectl -n cluster-support wait --for=condition=ready pod -l app=node-debug-shell --timeout=120s
kubectl -n cluster-support get pods -l app=node-debug-shell -o wide
kubectl -n cluster-support exec -it debug-shell-<node-slug> -- bash
```

Delete all of them when finished — the pods run `sleep infinity` and persist
until removed:

```sh
kubectl -n cluster-support delete pod -l app=node-debug-shell
```

## Expected Results

- `kubectl -n cluster-support get pods -l app=node-debug-shell -o wide` shows
  one `Running` pod per targeted node, each on its own node.
- `kubectl -n cluster-support exec -it debug-shell-<node> -- cat /host/etc/os-release`
  prints the node's Rocky Linux release — proof the mount is the real host
  filesystem, not the container image's.
- `nsenter --target 1 --mount --uts --ipc --net --pid -- docker ps` lists the
  node's MKE containers.

## Using the shell

Inside the container, three levels of host access are available.

### Read host files directly

The node's root filesystem is mounted at `/host`:

```sh
cat /host/etc/os-release            # Rocky Linux release of the bootc image
ls /host/var/log/                   # host logs, including support bundles
cat /host/etc/docker/daemon.json
```

### Run host binaries with `chroot`

For host-native tooling that expects the host's own libraries and paths:

```sh
chroot /host bootc status
chroot /host rpm-ostree status
chroot /host systemctl list-units --failed
```

### Enter the host namespaces with `nsenter`

Fullest access: run a command as if it were started on the host itself — the
host's mount, UTS, IPC, network, and PID namespaces, and therefore its
cgroups, sockets (`docker.sock`, journald), and process tree:

```sh
nsenter --target 1 --mount --uts --ipc --net --pid -- journalctl -u kubelet --no-pager
nsenter --target 1 --mount --uts --ipc --net --pid -- docker ps -a
nsenter --target 1 --mount --uts --ipc --net --pid -- systemctl status docker
nsenter --target 1 --mount --uts --ipc --net --pid -- bash    # interactive host shell
```

`--target 1` is PID 1 on the *host* because the pod sets `hostPID: true`. This
is how the support-bundle collectors reach host tooling; see
[Collect support bundles from nodes](collect-support-bundles.md).

### Retrieve a file from the node

`kubectl cp` works against the debug pod, so a file on the node can be pulled
to your workstation without SSH:

```sh
kubectl -n cluster-support cp \
  debug-shell-<node-slug>:/host/var/log/cluster-support/<bundle>.tar.gz \
  ./<bundle>.tar.gz
```

## F.A.Q

### Why not just SSH to the node?

`bootc-mke3` clusters are built to run with SSH disabled after install (see
[no-touch join](no-touch-join.md)). This path uses only the MKE endpoint, is
authorized by MKE RBAC, and is audited by the Kubernetes API server.

### The pod stays `Pending`. Why?

A pinned pod (`spec.nodeName`) is never scheduled, so `Pending` means the
kubelet has not accepted it. Check `kubectl -n cluster-support describe pod
<name>`: the usual causes are a taint the toleration does not cover, a
misspelled node name, or the kubelet being down — in which case the node needs
console access, not a debug shell.

### The pod is rejected at creation.

Admission denied it. The message names the attributes
(`privileged hostpid hostbindmounts`) and the ServiceAccount. Re-check
[the privilege grant](privileged-support-containers.md), especially that the
pod is being created in `cluster-support`.

### Can I use a different image?

Yes — any image with a shell works, and `--image` / the manifest's `image` is
the only change needed. `mirantis/ucp-dsinfo` is documented because it is
already mirrored in MKE environments and carries the MKE troubleshooting
tooling. Nothing in this runbook depends on its entrypoint.

### Does anything clean these pods up automatically?

No. Both paths leave the pod running until it is deleted. Include the delete
command in your investigation notes; a forgotten privileged pod is a standing
root shell on a node.
