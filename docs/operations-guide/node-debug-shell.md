# Open a debug shell on a node

This runbook shows how to get a root shell on a `bootc-mke3` node through the
Kubernetes API, without SSH. A privileged container pinned to the node gives
access to the host's filesystem, process table, and namespaces. The immutable,
SSH-less design of a `bootc` node otherwise makes these operations difficult.

This runbook has two paths. Use `kubectl debug` for one node. Use a Pod
manifest for several nodes at once or for options that `kubectl debug` does not
show.

## Security

A debug shell created with this runbook is **root-equivalent on the node where
it starts**. The container is privileged and mounts the host root filesystem at
`/host`. It can read every secret on disk and enter every host namespace. Treat
the ability to create these pods as `cluster-admin` on the nodes of the
cluster. Delete the pods when the investigation is complete. Nothing removes
them automatically.

## Requirements

1. `kubectl` configured from an MKE client bundle. See
   [Access the cluster](access-cluster.md).
2. If non-admin MKE users do the support work: the privilege grant from
   [Run privileged support containers on MKE](privileged-support-containers.md).
   An MKE admin client bundle does not need the grant. MKE refuses the pod of a
   non-admin user without the grant. In both cases, the `cluster-support`
   namespace that the runbook creates must exist.
3. `envsubst` (package `gettext`/`gettext-base`) on your workstation, for the
   multi-node path.
4. The MKE version of the cluster, for the image tag. Source the `env.sh` of
   the client bundle (see
   [Access the cluster](access-cluster.md#use-docker-swarm-socket)).
   Then the Swarm socket shows the version:

   ```sh
   docker version --format '{{.Server.Version}}'    # e.g. ucp/3.9.7 → tag 3.9.7
   ```

   The MKE UI also shows the version (**Admin Settings**). On a node, the
   `ucp-proxy` container carries the version as the label
   `com.docker.ucp.version`.

   The image that this runbook uses, `mirantis/ucp-dsinfo`, is the MKE
   troubleshooting image on Docker Hub. It has a tag for each MKE version. It
   already contains `bash`, `nsenter`, `curl`, `jq`, `tar`, and the `docker`
   CLI. In an air-gapped cluster, first mirror
   `mirantis/ucp-dsinfo:<MKE version>` into the local registry. Then use that
   reference.

## Procedure

### Option 1 — One node, with `kubectl debug`

`kubectl debug` builds the same kind of pod. The `sysadmin` profile makes the
container privileged. The node debugger always pins the pod to the target
node, shares the host namespaces, and mounts the host root filesystem at
`/host`:

```sh
kubectl debug node/<node-name> -it -n cluster-support \
  --profile=sysadmin \
  --image=mirantis/ucp-dsinfo:3.9.7 \
  -- bash
```

- `-n cluster-support` is required. The pod runs as the `default`
  ServiceAccount of that namespace, and the privilege grant covers this
  identity. Without the option, the pod starts in the `default` namespace,
  which has no grant.
- When the node name is an FQDN, as on AWS, kubectl prints a warning that the
  generated pod name is not a DNS label
  (`must be no more than 63 characters must not contain dots`). The warning
  comes from the naming in kubectl. It is not a failure, and the pod runs.
- kubectl does **not** delete the pod when you exit. Remove the pod:

  ```sh
  kubectl -n cluster-support get pods            # find node-debugger-<node>-xxxxx
  kubectl -n cluster-support delete pod node-debugger-<node>-xxxxx
  ```

Upstream reference:
[debugging a node with kubectl debug](https://kubernetes.io/docs/tasks/debug/debug-cluster/kubectl-node-debug/).

With an admin bundle, the generated pod reaches `Running`. Inside the pod,
`cat /host/etc/redhat-release` prints the Rocky Linux release of the node. If
your MKE version refuses the pod that `kubectl debug` generates, use option 2.
The manifest states every attribute that it requests.

### Option 2 — One or many nodes, with a manifest

The template
[`debug-shell-pod.yaml.tmpl`](../examples/cluster-support/debug-shell-pod.yaml.tmpl)
takes two `envsubst` variables. `${NODE_NAME}` is the node to pin to.
`${NODE_SLUG}` is the same name with dots replaced by dashes, and it is used
for the pod name. A pod name that contains dots becomes the hostname of the pod,
and kubectl shows a warning. AWS node names are FQDNs. Edit the image tag in
the template one time to match your MKE version. Then use any node selector to
create the pods on many nodes:

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

Wait for the pods, then attach to one of them:

```sh
kubectl -n cluster-support wait --for=condition=ready pod -l app=node-debug-shell --timeout=120s
kubectl -n cluster-support get pods -l app=node-debug-shell -o wide
kubectl -n cluster-support exec -it debug-shell-<node-slug> -- bash
```

When you are done, delete all the pods. The pods run `sleep infinity` and stay
until you remove them:

```sh
kubectl -n cluster-support delete pod -l app=node-debug-shell
```

## Expected Results

- `kubectl -n cluster-support get pods -l app=node-debug-shell -o wide` shows
  one `Running` pod for each target node, each on its own node.
- `kubectl -n cluster-support exec -it debug-shell-<node> -- cat /host/etc/os-release`
  prints the Rocky Linux release of the node. This shows that the mount is the
  real host filesystem and not the filesystem of the container image.
- `nsenter --target 1 --mount --uts --ipc --net --pid -- docker ps` lists the
  MKE containers of the node.

## Using the shell

Inside the container, three levels of host access are available.

### Read host files directly

The root filesystem of the node is mounted at `/host`:

```sh
cat /host/etc/os-release            # Rocky Linux release of the bootc image
ls /host/var/log/                   # host logs, including support bundles
cat /host/etc/docker/daemon.json
```

### Run host binaries with `chroot`

Use this method for host-native tools that need the libraries and paths of the
host:

```sh
chroot /host bootc status
chroot /host rpm-ostree status
chroot /host systemctl list-units --failed
```

### Enter the host namespaces with `nsenter`

This method gives the most access. It runs a command as if the command started
on the host. The command uses the mount, UTS, IPC, network, and PID namespaces
of the host. Therefore it also uses the cgroups, sockets (`docker.sock`,
journald), and process tree of the host:

```sh
nsenter --target 1 --mount --uts --ipc --net --pid -- journalctl -u kubelet --no-pager
nsenter --target 1 --mount --uts --ipc --net --pid -- docker ps -a
nsenter --target 1 --mount --uts --ipc --net --pid -- systemctl status docker
nsenter --target 1 --mount --uts --ipc --net --pid -- bash    # interactive host shell
```

`--target 1` is PID 1 on the *host* because the pod sets `hostPID: true`. The
support-bundle collectors use the same method to reach host tools. See
[Collect support bundles from nodes](collect-support-bundles.md).

### Retrieve a file from the node

`kubectl cp` works with the debug pod. You can copy a file from the node to
your workstation without SSH:

```sh
kubectl -n cluster-support cp \
  debug-shell-<node-slug>:/host/var/log/cluster-support/<bundle>.tar.gz \
  ./<bundle>.tar.gz
```

## F.A.Q

### Why not just SSH to the node?

`bootc-mke3` clusters are built to run with SSH disabled after installation
(see [no-touch join](no-touch-join.md)). This path uses only the MKE endpoint.
MKE RBAC authorizes the path, and the Kubernetes API server audits it.

### The pod stays `Pending`. Why?

The scheduler never schedules a pinned pod (`spec.nodeName`). Therefore
`Pending` means that the kubelet did not accept the pod. Run
`kubectl -n cluster-support describe pod <name>`. The usual causes are a taint
that the toleration does not cover, a misspelled node name, or a kubelet that
is down. If the kubelet is down, the node needs console access, not a debug
shell.

### The pod is rejected at creation.

Admission denied the pod. The message names the attributes
(`privileged hostpid hostbindmounts`) and the ServiceAccount. Check
[the privilege grant](privileged-support-containers.md) again. Make sure that
you create the pod in `cluster-support`.

### Can I use a different image?

Yes. Any image that has a shell works. Change only `--image` or the `image` of
the manifest. This runbook uses `mirantis/ucp-dsinfo` because MKE environments
already mirror it and it contains the MKE troubleshooting tools. Nothing in
this runbook depends on the entrypoint of the image.

### Does anything clean these pods up automatically?

No. Both paths leave the pod running until you delete it. Put the delete
command in your investigation notes. A privileged pod that you forget is a
standing root shell on a node.
