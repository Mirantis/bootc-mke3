# Collect support bundles from nodes

This runbook shows how to collect diagnostic bundles from every `bootc-mke3`
node at the same time through the Kubernetes API, without SSH. One Job per node
runs a fixed set of collectors. The collectors gather the systemd journal, the
MCR state, the MKE 3 node support bundle, the `bootc` deployment status, and the
general host state. The Job writes a single
`<name>-<node>-<timestamp>.tar.gz` to each destination that you configure.

Use this bulk path for Day-2 diagnostics and to produce data that a support
case requests. To investigate one node interactively, use
[Open a debug shell on a node](node-debug-shell.md).

## Security

A capture is **root-equivalent on every node it runs on**. Each Pod is
privileged, joins the host PID namespace, and mounts the host root filesystem at
`/host`. Each Pod runs host commands with `nsenter --target 1`. Treat the
ability to create these Jobs as `cluster-admin` on the nodes of the cluster.

The bundles are sensitive. They contain journal output, daemon
configuration, and the MKE support bundle. Handle and transport them as
confidential data. Delete them from the nodes after you collect them.

## Requirements

1. `kubectl` configured from an MKE client bundle. See
   [Access the cluster](access-cluster.md).
2. The `cluster-support` namespace from
   [Run privileged support containers on MKE](privileged-support-containers.md).
   If non-admin MKE users do the support work, they also need the privilege
   grant from that runbook. An admin client bundle does not need the grant.
3. `envsubst` (package `gettext`/`gettext-base`) on your workstation.
4. The MKE version of the cluster for the image tag, as in
   [the debug shell runbook](node-debug-shell.md#requirements). The collector
   image is `mirantis/ucp-dsinfo:<MKE version>`. In an air-gapped cluster,
   mirror the image and use the local reference in the Job template.

## Files

These files are in [`docs/examples/cluster-support/`](../examples/cluster-support):

| File | Purpose |
|---|---|
| [`capture-scripts-configmap.yaml`](../examples/cluster-support/capture-scripts-configmap.yaml) | The collector scripts, mounted at `/scripts`. Applied once per cluster. |
| [`capture-job.yaml.tmpl`](../examples/cluster-support/capture-job.yaml.tmpl) | One Job per node. `${NODE_NAME}` is its only template variable. |
| [`s3-credentials-secret.yaml.example`](../examples/cluster-support/s3-credentials-secret.yaml.example) | Credentials skeleton, only for the S3 destination. |
| [`pvc-hostpath-dev-test.yaml`](../examples/cluster-support/pvc-hostpath-dev-test.yaml) | Dev/test node-local claim, only for exercising the PVC destination. |

## Procedure

### 1. Install the collector scripts

Do this step one time for each cluster. Apply the ConfigMap again after you
edit the scripts:

```sh
cd docs/examples/cluster-support
kubectl apply -f capture-scripts-configmap.yaml
```

### 2. Start a capture

Edit the image tag in `capture-job.yaml.tmpl` to match your MKE version. Then
start a Job on each node that you want. Use `kubectl create`, not
`kubectl apply`. The Job uses `generateName`, and `apply` rejects it.

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

The `mke3` collector takes most of the time. It runs the MKE support command
with a 20-minute timeout. Set a generous wait time:

```sh
kubectl -n cluster-support wait --for=condition=complete job -l app=log-capture --timeout=45m
```

This command returns successfully only if *all* Jobs succeed. If the command
times out, list the result for each node instead of you waiting longer:

```sh
kubectl -n cluster-support get jobs -l app=log-capture \
  -o custom-columns='JOB:.metadata.name,NODE:.metadata.annotations.support\.mirantis\.com/node,STATUS:.status.conditions[-1].type'
kubectl -n cluster-support logs job/<job-name>
```

### 4. Retrieve the bundles

With the default `hostPath` destination, the bundle stays on the node that
created it, at `/var/log/cluster-support/<name>-<node>-<timestamp>.tar.gz`.
Open a [debug shell](node-debug-shell.md) on that node and copy the bundle out.
SSH is not necessary:

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

The S3 destination avoids this step. The PVC destination avoids it only if
shared storage backs the claim. See
[PVC](#pvc).

### 5. Clean up

```sh
kubectl -n cluster-support delete job -l app=log-capture
```

Finished Jobs delete themselves one hour after they complete
(`ttlSecondsAfterFinished: 3600`). Bundles that are written to
`/var/log/cluster-support` on a node are **not** deleted automatically. Delete
them from the debug shell after you collect them.

## Expected Results

- One Job per targeted node, each reaching `Complete`:
  `kubectl -n cluster-support get jobs -l app=log-capture`.
- On each node, `/var/log/cluster-support/<name>-<node>-<timestamp>.tar.gz`
  exists (visible from a [debug shell](node-debug-shell.md) at
  `/host/var/log/cluster-support/`).
- Inside a bundle: `collectors.txt` lists each collector with exit code `0`.
  On an MKE node, the bundle also contains a non-empty `mke3-support.tgz`.

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

Two environment variables in the Job tune the run. Both are in the template as
comments:

| Variable | Effect |
|---|---|
| `COLLECTORS` | Space-separated collector names, for example `"journal system"`. If it is not set, all five collectors run. |
| `JOURNAL_SINCE` | Passed without change to `journalctl --since`. The default is `24 hours ago`. |

The `mke3` collector is the expensive collector. It is the only collector that can
run for many minutes. If you remove it (`COLLECTORS: "journal mcr bootc system"`),
the capture finishes in seconds. The capture then does not contain the MKE-level
bundle that a support case usually needs.

## Destinations

A destination is enabled when you mount it or set its bucket. Only the Job
manifest makes this decision. You can use any combination of destinations. Every
enabled destination receives the same tarball.

| Destination | Enabled by | Behaviour |
|---|---|---|
| hostPath | `/out` mounted (default: `hostPath: /var/log/cluster-support`, `DirectoryOrCreate`) | Writes the bundle onto the node itself. Retrieve it with a debug shell, as in step 4. |
| PVC | `/pvc` mounted | Copies the bundle into an existing claim. The storage that backs the claim decides if the bundles from several nodes go to one place. See below. |
| S3 | `S3_BUCKET` set | Uploads the bundle to an S3-compatible endpoint. |

### PVC

Uncomment the `bundles` volume and its `/pvc` mount in the Job template. Set
`claimName` to a claim that already exists in `cluster-support`. Nothing in this
procedure creates or deletes claims. A default `bootc-mke3` cluster has **no**
StorageClass (`kubectl get storageclass` is empty). Because of this, this
destination needs storage that you provision yourself.

[`pvc-hostpath-dev-test.yaml`](../examples/cluster-support/pvc-hostpath-dev-test.yaml)
is a node-local claim with two objects. Use it to test this destination on a
cluster that has no storage. It is labelled dev/test because it is not a shared
destination. Read the next paragraph before you use it for real work.

> [!IMPORTANT]
> Only shared storage collects bundles into one place. The access mode of the
> claim does not show if your storage is shared.

Access modes are metadata. They are not enforced. Nothing enforces them for a
node-local volume (`hostPath`, `local`). Such volumes have no attach step, and
these pods bypass the scheduler because they set `spec.nodeName`. The next table
shows the result with one claim and three nodes that are captured at the same
time:

| Claim declares | Result |
|---|---|
| `ReadWriteMany`, backed by `hostPath` | All three Jobs are `Complete` with no error. Each `/pvc` on a node holds **only the bundle of that node**. The result is three separate directories, with no warning. |
| `ReadWriteOnce`, backed by `hostPath` | All three Jobs are also `Complete`. There is no `Pending` state and no multi-attach error. `ReadWriteOnce` blocked nothing. |

Node-local storage with `ReadWriteMany` gives only a false impression of
shared storage. For one collection point, back the claim with storage that is
shared. Examples are NFS, CephFS, an EFS-class service, or a CSI driver that
offers a true `ReadWriteMany` volume. With such storage, this destination does
what it promises. In a test with a `ReadWriteMany` claim, three nodes were
captured at the same time. All three bundles were put side by side in the one
claim. If shared storage is not available, we recommend the hostPath
destination. This destination is clear that it is per-node. Retrieve the
bundles with a debug shell.

On **attachable** storage (CSI block volumes such as EBS), a `ReadWriteOnce`
volume cannot attach to more than one node. The pods on the other nodes then
cannot mount the volume, and their Jobs fail at `activeDeadlineSeconds`. This
result comes from reasoning and was not tested, because a default cluster has
no CSI driver.

> [!WARNING]
> Do not back this claim with a StorageClass that uses
> `volumeBindingMode: WaitForFirstConsumer`.

This mode delays binding until the scheduler places a pod that uses the claim.
These pods are never scheduled, because they set `spec.nodeName`. Test result:
the claim stays `Pending` indefinitely, also when a pod uses it. The pod stays
`Pending` with `FailedMount ... PVC is not bound`. Bind the claim statically
(name its `volumeName` and set `storageClassName: ""`). Alternatively, use a
class with `Immediate` binding.

With a statically bound claim, a capture logs
`wrote <bundle>.tar.gz to the PersistentVolumeClaim`. It also reports
`delivered to 2 destination(s)` together with the default hostPath destination.

#### How this was tested, and the one bootc-specific trap

An in-cluster NFS server produced the shared-storage result above. It was used
only because it is the cheapest way to get a real `ReadWriteMany` volume on a
cluster that has no storage. **NFS is not part of the expected deployment.**
An operator who uses this destination must point it at the storage that the
cluster already has. This section records the NFS setup because it showed one
fact about `bootc-mke3` nodes. The fact applies to any claim that NFS backs.

When this was recorded, a stock node could not mount NFS. The image contained
`nfs-utils`, `mount.nfs`, `rpcbind`, and the modules on disk. But the node set
`kernel.modules_disabled=1` and booted with only `sunrpc` loaded. Because of
this, the NFS modules could not be loaded on demand. Current images set
`kernel.modules_disabled = 0`, which should permit loading on demand. This was
not tested again for NFS. The mount error shows which module is missing:

| Modules loaded at boot | `mount.nfs` says |
|---|---|
| none (stock node) | `No such device` |
| `nfs` only | `Protocol not supported`. The version modules are separate. |
| `nfs nfsv4 nfsv3 lockd nfs_acl` | mounts |

The remedy is the usual one, and the lockdown does not prevent it. List the
modules in a `/etc/modules-load.d/*.conf` file and reboot. This works because
`systemd-modules-load.service` is ordered `Before=systemd-sysctl.service`, so it
runs while loading is still permitted. The trap is the middle row: if you
preload only `nfs`, it looks sufficient but it is not. For a whole cluster, let
`machine-config-controller` maintain that drop-in (`spec.kernel.modules.load`,
then a separate `reboot` resource). Do not edit the nodes by hand. See
[machine configuration changes](machine-config-operations.md).

Two more observations come from the same setup. They help if you want to
reproduce it:

- A userspace NFS server (nfs-ganesha) needs no kernel module of its own and
  runs on a stock node. Only the client side needs the preload.
- Kubelet mounts NFS in the host network namespace, where cluster DNS does not
  resolve. The PV must name the ClusterIP of the Service, not its DNS name.

### S3

Create the Secret (keys `accessKeyID` and `secretAccessKey`). Then uncomment
the six S3 environment entries in the Job template:

```sh
kubectl -n cluster-support create secret generic s3-credentials \
  --from-literal=accessKeyID=<key-id> \
  --from-literal=secretAccessKey=<secret>
```

The object is written to
`<S3_ENDPOINT>/<S3_BUCKET>/<S3_PREFIX><name>-<node>-<timestamp>.tar.gz`.
`S3_PREFIX` is a literal prefix. Include the trailing `/` if you want a
folder. If `S3_REGION` is not set, it defaults to `us-east-1`. This matters
because the region is part of the request signature.

> [!IMPORTANT]
> The S3 destination needs a collector image with curl 8 or newer.
> `mirantis/ucp-dsinfo` does not have it.

That image (Ubuntu 22.04) has curl 7.81.0. This curl version advertises
`--aws-sigv4`, but it computes an upload signature that the server rejects. Test
result against an S3-compatible endpoint: curl 7.81.0 returns
`SignatureDoesNotMatch`. Curl 8.14.1 and 8.15.0 accept the same request,
credentials, region, and URL. `capture.sh` checks the version and logs
`signs sigv4 uploads incorrectly`. This prevents a silent 403.

For the S3 destination, replace the image and command of the collector container:

```yaml
          image: alpine:3.21
          command: ["sh","-c","apk add --no-cache bash util-linux tar gzip curl >/dev/null && exec bash /scripts/capture.sh"]
```

This was verified end to end (curl 8.14.1). The image does not change the
collectors. Every host command runs through `nsenter --target 1` against the
binaries of the node. Therefore the container needs only `bash`, `nsenter`,
`tar`, `gzip`, and `curl`. In an air-gapped cluster, mirror an image that
already contains these tools. Do not rely on `apk`.

Uploads have limits (`--connect-timeout 30 --max-time 300 --retry 3`). If the
endpoint is not reachable, the destination fails. The privileged Pod does not
stay on the node.

## Failure semantics

A capture is fault-tolerant by design, because the node that needs a bundle is
often already broken:

- If a collector command fails, it writes its stderr to `<file>.err` beside the
  output file. The bundle is not stopped. Empty `.err` files are removed.
- **An `.err` file does not by itself mean failure.** Several host commands write
  to stderr when they succeed. A bundle from a healthy capture therefore
  routinely contains large `.err` files:
  - `docker logs <container>` sends the stderr stream of a container to stderr.
    For MKE containers that log there, `docker-logs-<name>.log` is empty and
    `docker-logs-<name>.log.err` holds the actual logs. Read the `.err` file.
  - `mke3-support.err` is progress output from the MKE support command. The
    `mke3-support.tgz` beside it is valid.
  - `daemon.json.err` and `journal-previous-boot.log.err` appear on a healthy
    node that has no `/etc/docker/daemon.json` and no previous boot.
  Use `collectors.txt` for pass/fail. Use the `.err` files as context.
- `collectors.txt` records `<collector> <exit-code>` for each collector. The
  bundle thus shows what ran.
- A Job **fails only when no destination received the tarball**. A partial
  collection is a success.
- `backoffLimit: 0` means that a failed Job is not retried. Read
  `kubectl -n cluster-support logs job/<job-name>`, correct the cause, and create
  the Job again for that node.

## Concurrency

The loop in step 2 starts one privileged Job on each matched node at the same
time. This is intended for a small number of nodes. On a large cluster, it
starts a `mirantis/ucp support` run on every node at the same time. Capture in
slices instead:

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

Yes. Add a `<name>.sh` key to the ConfigMap. The script must source `common.sh`
and use its `collect` helper. Apply the ConfigMap again and name the collector
in `COLLECTORS`. The helper enters the host namespace, captures the output, and
never stops the bundle.

### Why one Job per node instead of a DaemonSet?

A capture is a task that finishes. Jobs give a success or failure result for
each node, `backoffLimit: 0` semantics, and self-deletion through
`ttlSecondsAfterFinished`. A DaemonSet would restart the collectors forever and
gives no result for each node.

### Why is the Pod `Pending`?

A pinned Pod (`spec.nodeName`) is never scheduled. `Pending` therefore means
that the kubelet has not accepted the Pod. The causes can be a taint that the
toleration does not cover, or a bad node name. They can also be a
`ReadWriteOnce` PVC that is already mounted elsewhere, or a kubelet that is down. See
`kubectl -n cluster-support describe pod <name>`.

### The Job was rejected at creation.

Admission denied it. The message names the requested attributes and the
ServiceAccount. Check [the privilege grant](privileged-support-containers.md)
again. Make sure that you create the Job in `cluster-support`.

### Do the bundles include the MKE cluster-wide support dump?

No. Each Job collects the node it runs on, including the
`mirantis/ucp … support` output of that node. For a cluster-level dump, use the
MKE support bundle from the MKE UI or API.
