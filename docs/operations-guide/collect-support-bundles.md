# Collect support bundles from nodes

How to collect diagnostic bundles from every `bootc-mke3` node at once through
the Kubernetes API, without SSH. One Job per node runs a fixed set of
collectors — systemd journal, MCR state, the MKE 3 node support bundle, `bootc`
deployment status, and general host state — and writes a single
`<name>-<node>-<timestamp>.tar.gz` to each destination you configure.

This is the bulk path for Day-2 diagnostics and for producing data a support
case asks for. For interactive investigation of one node, use
[Open a debug shell on a node](node-debug-shell.md).

## Security

A capture is **root-equivalent on every node it runs on**: each Pod is
privileged, joins the host PID namespace, mounts the host root filesystem at
`/host`, and runs host commands via `nsenter --target 1`. Treat the ability to
create these Jobs as `cluster-admin` on the cluster's nodes.

The bundles themselves are sensitive. They contain journal output, daemon
configuration, and the MKE support bundle; handle and transport them as
confidential data, and delete them from nodes once they are collected.

## Requirements

1. `kubectl` configured from an MKE client bundle — see
   [Access the cluster](access-cluster.md).
2. The `cluster-support` namespace from
   [Run privileged support containers on MKE](privileged-support-containers.md),
   plus that runbook's privilege grant if support work is done by non-admin MKE
   users (an admin client bundle does not need it).
3. `envsubst` (package `gettext`/`gettext-base`) on your workstation.
4. The cluster's MKE version for the image tag, as in
   [the debug shell runbook](node-debug-shell.md#requirements). The collector
   image is `mirantis/ucp-dsinfo:<MKE version>`; in an air-gapped cluster,
   mirror it and use the local reference in the Job template.

## Files

All three live in [`docs/examples/cluster-support/`](../examples/cluster-support):

| File | Purpose |
|---|---|
| [`capture-scripts-configmap.yaml`](../examples/cluster-support/capture-scripts-configmap.yaml) | The collector scripts, mounted at `/scripts`. Applied once per cluster. |
| [`capture-job.yaml.tmpl`](../examples/cluster-support/capture-job.yaml.tmpl) | One Job per node. `${NODE_NAME}` is its only template variable. |
| [`s3-credentials-secret.yaml.example`](../examples/cluster-support/s3-credentials-secret.yaml.example) | Credentials skeleton, only for the S3 destination. |
| [`pvc-hostpath-dev-test.yaml`](../examples/cluster-support/pvc-hostpath-dev-test.yaml) | Dev/test node-local claim, only for exercising the PVC destination. |

## Procedure

### 1. Install the collector scripts

Once per cluster (re-apply after editing the scripts):

```sh
cd docs/examples/cluster-support
kubectl apply -f capture-scripts-configmap.yaml
```

### 2. Start a capture

Edit the image tag in `capture-job.yaml.tmpl` to match your MKE version, then
fan out over the nodes you want. Note `kubectl create`, not `kubectl apply`:
the Job uses `generateName`, which `apply` rejects.

```sh
# Every node
for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  NODE_NAME=$node envsubst < capture-job.yaml.tmpl | kubectl create -f -
done

# Only managers.
# MKE 3 labels managers node-role.kubernetes.io/master, not
# .../control-plane — check with: kubectl get nodes --show-labels
for node in $(kubectl get nodes -l node-role.kubernetes.io/master -o jsonpath='{.items[*].metadata.name}'); do
  NODE_NAME=$node envsubst < capture-job.yaml.tmpl | kubectl create -f -
done

# One node
NODE_NAME=<node-name> envsubst < capture-job.yaml.tmpl | kubectl create -f -
```

### 3. Monitor to completion

```sh
kubectl -n cluster-support get jobs -l app=log-capture -w
```

How long a capture takes is dominated by the `mke3` collector, which runs MKE's
own support command with a 20-minute timeout. Measured on a 3-manager MKE 3.9.5
cluster: 25-26 seconds per node for all five collectors, producing a 1.9 MB
bundle of which 1.75 MB is the MKE support tarball. A loaded or larger node can
take considerably longer, so bound the wait generously rather than tightly:

```sh
kubectl -n cluster-support wait --for=condition=complete job -l app=log-capture --timeout=45m
```

That command only returns successfully if *all* Jobs succeed. If it times out,
list the outcome per node instead of waiting further:

```sh
kubectl -n cluster-support get jobs -l app=log-capture \
  -o custom-columns='JOB:.metadata.name,NODE:.metadata.annotations.support\.mirantis\.com/node,STATUS:.status.conditions[-1].type'
kubectl -n cluster-support logs job/<job-name>
```

### 4. Retrieve the bundles

With the default `hostPath` destination the bundle stays on the node it came
from, at `/var/log/cluster-support/<name>-<node>-<timestamp>.tar.gz`. Open a
[debug shell](node-debug-shell.md) on that node and copy it out — no SSH
involved:

```sh
node=<node-name>
NODE_NAME=$node NODE_SLUG=$(printf '%s' "$node" | tr '.' '-') \
  envsubst < debug-shell-pod.yaml.tmpl | kubectl apply -f -
slug=$(printf '%s' "$node" | tr '.' '-')
kubectl -n cluster-support exec debug-shell-$slug -- ls -lh /host/var/log/cluster-support/
kubectl -n cluster-support cp \
  debug-shell-$slug:/host/var/log/cluster-support/<bundle>.tar.gz ./<bundle>.tar.gz
kubectl -n cluster-support delete pod debug-shell-$slug
```

The S3 destination avoids this step entirely. The PVC destination only does so
if the claim is backed by genuinely shared storage — see
[PVC](#pvc).

### 5. Clean up

```sh
kubectl -n cluster-support delete job -l app=log-capture
```

Finished Jobs also delete themselves an hour after completion
(`ttlSecondsAfterFinished: 3600`). Bundles written to a node's
`/var/log/cluster-support` are **not** cleaned up — delete them from the debug
shell once collected.

## Expected Results

- One Job per targeted node, each reaching `Complete`:
  `kubectl -n cluster-support get jobs -l app=log-capture`.
- On each node, `/var/log/cluster-support/<name>-<node>-<timestamp>.tar.gz`
  exists (visible from a [debug shell](node-debug-shell.md) at
  `/host/var/log/cluster-support/`).
- Inside a bundle: `collectors.txt` listing each collector with exit code `0`,
  and — on an MKE node — a non-empty `mke3-support.tgz`.

## What is collected

Every collector writes its command output into the bundle, one file per
command. `collectors.txt` in the bundle records each collector's exit code.

| Collector | Collects |
|---|---|
| `journal` | `journalctl` for the current boot (bounded by `JOURNAL_SINCE`), the previous boot, error-priority entries, `--list-boots`, and per-unit logs for `docker`, `swarm-join`, `mke-images`, and `kubelet`. |
| `mcr` | `docker version`/`info`/`ps -a`, `/var/lib/docker` disk usage, `/etc/docker/daemon.json`, and `docker logs` for `ucp-proxy`, `ucp-reconcile`, `ucp-controller`, `ucp-auth-api`, `ucp-auth-store`. |
| `mke3` | The MKE 3 node support bundle (`mirantis/ucp … support`, 20m timeout) plus the local `/_ping` health probe. Skips with `mke3-skipped.txt` on nodes without `ucp-proxy`. |
| `bootc` | `bootc status --format json` and `rpm-ostree status --json`. |
| `system` | `uname -a`, failed systemd units, `df`, `free`, `ip addr`/`route`, `dmesg`, `sysctl -a`, `getenforce`, `/etc/os-release`. |

Two environment variables in the Job tune the run; both are present but
commented in the template:

| Variable | Effect |
|---|---|
| `COLLECTORS` | Space-separated collector names, e.g. `"journal system"`. Unset runs all five. |
| `JOURNAL_SINCE` | Passed verbatim to `journalctl --since`. Default `24 hours ago`. |

The `mke3` collector is the expensive one and the only collector that can run for
many minutes. Dropping it (`COLLECTORS: "journal mcr bootc system"`) leaves a
capture that finishes in seconds, at the cost of the MKE-level bundle a support
case usually wants.

## Destinations

A destination is enabled by mounting it or by setting its bucket — the Job
manifest is the only place that decides. Any combination works, and every
enabled destination receives the same tarball.

| Destination | Enabled by | Behaviour |
|---|---|---|
| hostPath | `/out` mounted (default: `hostPath: /var/log/cluster-support`, `DirectoryOrCreate`) | Writes the bundle onto the node itself. Retrieve it with a debug shell, as in step 4. |
| PVC | `/pvc` mounted | Copies the bundle into an existing claim. Whether that collects bundles from several nodes into one place depends entirely on the storage backing the claim — see below. |
| S3 | `S3_BUCKET` set | Uploads to an S3-compatible endpoint. |

### PVC

Uncomment the `bundles` volume and its `/pvc` mount in the Job template and set
`claimName` to a claim that already exists in `cluster-support` — nothing here
creates or deletes claims. A default `bootc-mke3` cluster ships **no**
StorageClass (`kubectl get storageclass` is empty), so this destination requires
storage you have provisioned yourself.

[`pvc-hostpath-dev-test.yaml`](../examples/cluster-support/pvc-hostpath-dev-test.yaml)
is a two-object, node-local claim for exercising this destination on a cluster
with no storage. It is labelled dev/test because it is not a shared destination
— read the next paragraph before using it for anything real.

> [!IMPORTANT]
> Only genuinely shared storage collects bundles into one place, and the claim's
> access mode will not tell you whether yours does.

Access modes are metadata, not enforcement. For a node-local volume (`hostPath`,
`local`) nothing enforces them: such volumes have no attach step, and these pods
bypass the scheduler by setting `spec.nodeName`. Measured on MKE 3.9.5, one
claim, three nodes captured concurrently:

| Claim declares | Result |
|---|---|
| `ReadWriteMany`, backed by `hostPath` | All three Jobs `Complete`, no error — and each node's `/pvc` holds **only its own bundle**. Three separate directories, silently. |
| `ReadWriteOnce`, backed by `hostPath` | Also all three `Complete`. No `Pending`, no multi-attach error: `ReadWriteOnce` blocked nothing. |

So declaring `ReadWriteMany` on node-local storage buys nothing but a false
impression. For one collection point, back the claim with storage that is really
shared — NFS, CephFS, an EFS-class service, or any CSI driver offering a true
`ReadWriteMany` volume. With such storage this destination does exactly what it
promises: measured with a `ReadWriteMany` claim, three nodes captured
concurrently and all three bundles landed side by side in the one claim.
Otherwise prefer the hostPath destination, which is at least honest about being
per-node, and retrieve with a debug shell.

On **attachable** storage (CSI block volumes such as EBS) a `ReadWriteOnce`
volume genuinely cannot attach to more than one node, so pods on the other nodes
would fail to mount and their Jobs would fail at `activeDeadlineSeconds`. That
path is reasoned, not tested — a default cluster has no CSI driver to test it
with.

> [!WARNING]
> Do not back this claim with a StorageClass that uses
> `volumeBindingMode: WaitForFirstConsumer`.

That mode defers binding until the scheduler places a consuming pod, and these
pods are never scheduled — they set `spec.nodeName`. Verified: the claim stays
`Pending` indefinitely even with a consuming pod, and the pod sits `Pending` with
`FailedMount ... PVC is not bound`. Bind the claim statically (name its
`volumeName`, set `storageClassName: ""`) or use an `Immediate`-binding class.

Verified working on MKE 3.9.5: with a statically bound claim, a capture logs
`wrote <bundle>.tar.gz to the PersistentVolumeClaim` and reports
`delivered to 2 destination(s)` alongside the default hostPath destination.

#### How this was tested, and the one bootc-specific trap

The shared-storage result above was produced with an in-cluster NFS server,
chosen only because it is the cheapest way to get a real `ReadWriteMany` volume
onto a cluster that ships no storage. **NFS is not part of the expected
deployment** — an operator using this destination is expected to point it at
whatever storage the cluster already has. It is recorded here because the setup
surfaced one fact about `bootc-mke3` nodes that applies to any NFS-backed claim.

A stock node could not mount NFS at all when this was recorded, despite the
image shipping `nfs-utils`, `mount.nfs`, `rpcbind`, and the modules on disk:
it set `kernel.modules_disabled=1` and booted with only `sunrpc` loaded, so
the NFS modules could not be loaded on demand. Current images ship
`kernel.modules_disabled = 0`, which should allow on-demand loading; that
has not been re-tested for NFS. The mount error names what is missing:

| Modules loaded at boot | `mount.nfs` says |
|---|---|
| none (stock node) | `No such device` |
| `nfs` only | `Protocol not supported` — the version modules are separate |
| `nfs nfsv4 nfsv3 lockd nfs_acl` | mounts |

The remedy is the ordinary one and the lockdown does not prevent it: list the
modules in a `/etc/modules-load.d/*.conf` file and reboot, since
`systemd-modules-load.service` is ordered `Before=systemd-sysctl.service` and so
runs while loading is still permitted. The trap is the middle row — preloading
`nfs` alone looks sufficient and is not. Across a cluster, have
`machine-config-controller` maintain that drop-in (`spec.kernel.modules.load`,
then a separate `reboot` resource) rather than editing nodes by hand; see
[machine configuration changes](machine-config-operations.md).

Two smaller observations from the same setup, for anyone reproducing it: a
userspace NFS server (nfs-ganesha) needs no kernel module of its own and runs on
a stock node — only the client side needs the preload — and kubelet mounts NFS in
the host network namespace, where cluster DNS does not resolve, so the PV must
name the Service's ClusterIP rather than its DNS name.

### S3

Create the Secret (keys `accessKeyID` and `secretAccessKey`), then uncomment
the six S3 environment entries in the Job template:

```sh
kubectl -n cluster-support create secret generic s3-credentials \
  --from-literal=accessKeyID=<key-id> \
  --from-literal=secretAccessKey=<secret>
```

The object is written to
`<S3_ENDPOINT>/<S3_BUCKET>/<S3_PREFIX><name>-<node>-<timestamp>.tar.gz`.
`S3_PREFIX` is a literal prefix — include the trailing `/` if you want a
folder. `S3_REGION` defaults to `us-east-1` when unset, which matters because it
is part of the request signature.

> [!IMPORTANT]
> The S3 destination needs a collector image with curl 8 or newer, which
> `mirantis/ucp-dsinfo` is not.

That image (Ubuntu 22.04) ships curl 7.81.0, which advertises `--aws-sigv4` but
computes an upload signature the server rejects. Verified against an
S3-compatible endpoint: curl 7.81.0 returns `SignatureDoesNotMatch` while curl
8.14.1 and 8.15.0 accept the identical request, credentials, region, and URL.
`capture.sh` checks the version and logs `signs sigv4 uploads incorrectly`
rather than producing a silent 403.

For the S3 destination, swap the collector container's image and command:

```yaml
          image: alpine:3.21
          command: ["sh","-c","apk add --no-cache bash util-linux tar gzip curl >/dev/null && exec bash /scripts/capture.sh"]
```

This is verified working end to end (curl 8.14.1). The collectors themselves are
unaffected by the image: every host command runs through `nsenter --target 1`
against the node's own binaries, so the container only needs `bash`, `nsenter`,
`tar`, `gzip`, and `curl`. In an air-gapped cluster, mirror an image that
already contains those rather than relying on `apk`.

Uploads are bounded (`--connect-timeout 30 --max-time 300 --retry 3`) so an
unreachable endpoint fails the destination instead of holding a privileged Pod on
the node.

## Failure semantics

A capture is deliberately fault-tolerant — the node needing a bundle is often
already broken:

- A collector command that fails writes its stderr to `<file>.err` beside the
  output file and does not abort the bundle. Empty `.err` files are removed.
- **An `.err` file does not by itself mean failure.** Several host commands write
  to stderr on success, so the bundle routinely contains large `.err` files next
  to a healthy capture:
  - `docker logs <container>` sends a container's own stderr stream to stderr, so
    for MKE containers that log there, `docker-logs-<name>.log` is empty and
    `docker-logs-<name>.log.err` holds the actual logs. Read the `.err` file.
  - `mke3-support.err` is progress output from MKE's support command; the
    `mke3-support.tgz` beside it is still valid.
  - `daemon.json.err` and `journal-previous-boot.log.err` appear on a healthy
    node that has no `/etc/docker/daemon.json` and no prior boot.
  Use `collectors.txt` for pass/fail, and `.err` files as context.
- `collectors.txt` records `<collector> <exit-code>` per collector, so the
  bundle states what ran.
- A Job **fails only when no destination received the tarball**. Partial
  collection is a success.
- `backoffLimit: 0` means a failed Job is not retried. Read
  `kubectl -n cluster-support logs job/<job-name>`, fix the cause, and create
  the Job again for that node.

## Concurrency

The loop in step 2 starts one privileged Job per matched node simultaneously.
That is intended for a handful of nodes, but on a large cluster it means a
concurrent `mirantis/ucp support` run on every node at once. Capture in slices
instead:

```sh
# Ten nodes at a time
kubectl get nodes -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' > nodes.txt
split -l 10 nodes.txt batch-

for node in $(cat batch-aa); do
  NODE_NAME=$node envsubst < capture-job.yaml.tmpl | kubectl create -f -
done
kubectl -n cluster-support wait --for=condition=complete job -l app=log-capture --timeout=45m
# retrieve, delete the Jobs, then repeat with batch-ab
```

## F.A.Q

### Can I add my own collector?

Yes. Add a `<name>.sh` key to the ConfigMap that sources `common.sh` and uses
its `collect` helper, re-apply the ConfigMap, and name it in `COLLECTORS`. The
helper handles the host namespace entry, output capture, and never aborting the
bundle.

### Why one Job per node instead of a DaemonSet?

A capture is a task that finishes. Jobs give per-node success/failure,
`backoffLimit: 0` semantics, and self-reaping via `ttlSecondsAfterFinished`; a
DaemonSet would restart the collectors forever and gives no per-node outcome.

### Why is the Pod `Pending`?

A pinned Pod (`spec.nodeName`) is never scheduled, so `Pending` means the
kubelet has not accepted it — a taint the toleration does not cover, a bad node
name, a `ReadWriteOnce` PVC already mounted elsewhere, or a down kubelet. See
`kubectl -n cluster-support describe pod <name>`.

### The Job was rejected at creation.

Admission denied it; the message names the requested attributes and the
ServiceAccount. Re-check [the privilege grant](privileged-support-containers.md)
and that you are creating in `cluster-support`.

### Do the bundles include the MKE cluster-wide support dump?

No. Each Job collects the node it runs on, including that node's
`mirantis/ucp … support` output. For a cluster-level dump, use MKE's own
support bundle from the MKE UI or API.
