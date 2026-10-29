# Air-gapped bootc-mke3

Instructions and prerequisites on how to properly install and upgrade bootc-mke3 in an air-gapped environment.

See also: [Install bootc-mke3](install-bootc-mke3.md), [Upgrade bootc-mke3](../operations-guide/upgrade-with-controller.md) (or the [Ansible exception path](../operations-guide/upgrade-with-ansible.md)).

## Prerequisites

- `kubectl` binary should be installed on the machine where ansible will be executed.

## What must be mirrored to your internal registry

Everything below is normally resolved against public hosts
(`registry.mirantis.com`, `docker.io`, `github.com`). In an air-gapped
environment each of these needs a mirrored copy reachable from either the
controller or the targets (noted per row), and the corresponding Ansible
variable repointed at it.

| Artifact | Pulled by | Reachable from | Default source | Mirror via variable |
|---|---|---|---|---|
| bootc OS image for upgrades | `bootc switch` / `bootc upgrade` (`tasks/bootc-upgrade-tasks.yml`) | targets | `registry.mirantis.com` | `vars/upgrade-vars.yml: bootc_image_ref` |
| `cluster-upgrade-controller` manifest | `kubectl apply -f` | controller | **already air-gap-safe by default** — `tasks/fetch-cluster-upgrade-controller-manifest-tasks.yml` copies the exact static manifest bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/cluster-upgrade-controller-manifest.yaml`) from a node to the controller before applying it; no mirroring needed unless overridden | `vars/common-vars.yml: cluster_upgrade_controller_manifest` |
| Container image referenced inside that manifest (controller pod image) | Kubernetes, once the manifest is applied | cluster nodes (via kubelet) | **already air-gap-safe by default** — the image tag baked into the node-fetched manifest is the one `mke-images.service` preloaded into the node's local image store at boot | not applicable unless `cluster_upgrade_controller_manifest` is overridden to a different manifest — then mirror whatever tag *that* manifest references |
| `machine-config-controller` manifest | `kubectl apply -f` | controller | **already air-gap-safe by default** — `tasks/fetch-machine-config-controller-manifest-tasks.yml` copies the exact static manifest bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/machine-config-controller-manifest.yaml`) from a node to the controller before applying it; no mirroring needed unless overridden | `vars/common-vars.yml: machine_config_controller_manifest` |
| Container images referenced inside that manifest (controller + node agent pods) | Kubernetes, once the manifest is applied | cluster nodes (via kubelet) | **already air-gap-safe by default** — the image tags baked into the node-fetched manifest are the ones `mke-images.service` preloaded into the node's local image store at boot | not applicable unless `machine_config_controller_manifest` is overridden to a different manifest — then mirror whatever tags *that* manifest references |
| System Upgrade Controller CRDs/manifest | `kubectl apply -f` | controller | **already air-gap-safe by default** — `tasks/fetch-controller-manifests-tasks.yml` copies the exact manifests bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/`) from a node to the controller before applying them; no mirroring needed unless overridden | `vars/common-vars.yml: suc_crd_manifest_src`, `suc_controller_manifest_src` — only override if you deliberately want a different SUC version than the one preloaded on this image |
| `rancher/system-upgrade-controller` container image (referenced *inside* the fetched manifest) | Kubernetes, once that manifest is applied | cluster nodes (via kubelet) | **already air-gap-safe by default** — the exact tag baked into the fetched manifest is the one `mke-images.service` preloaded into the node's local image store at boot, so kubelet never needs to pull it | not applicable unless `suc_controller_manifest_src` is overridden to a different manifest — then mirror whatever tag *that* manifest references |
| Container images run by the Jobs SUC creates during a `ClusterUpgrade` (for the `ClusterUpgrade` steps, the `cluster-upgrade-controller` image itself) | Kubernetes, when SUC creates each step's Job | cluster nodes (via kubelet) | **air-gap-safe only when `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` is `IfNotPresent`.** The images are preloaded, but SUC stamps this pull policy on every container of every Job it creates, and upstream ships it as `Always` — the kubelet then tries to reach the registry on every step even though the image is already on the node. Images built on or after 2026-10-29 bake `IfNotPresent` into the staged SUC manifest; images built before that need the one-time patch in [Older images: SUC Job pull policy](#older-images-suc-job-pull-policy) | not applicable once the policy is `IfNotPresent` — mirror only if you deliberately keep `Always` |

Practically: for a fully air-gapped run you need, at minimum, the
`bootc_image_ref` OS image mirrored. SUC, `cluster-upgrade-controller`, and
`machine-config-controller` need no further action for a default install on
an image built on or after 2026-10-29 — their manifests and container
images come from what bootc-mirantis already staged into the image, fetched
from a node rather than the network. On older images, one manual step is also
required before the first upgrade: [patch the SUC Job pull
policy](#older-images-suc-job-pull-policy).

## Older images: SUC Job pull policy

On images built before 2026-10-29, the SUC manifest staged in
`/usr/share/mke-controllers/manifests/` (identical to upstream SUC v0.14.0)
sets `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY: Always` in the
`system-upgrade/default-controller-env` ConfigMap. Install only patches
`SYSTEM_UPGRADE_JOB_ACTIVE_DEADLINE_SECONDS` in that ConfigMap, so the value
survives into the cluster. On an air-gapped cluster this leaves every
`ClusterUpgrade` step at `ErrImagePull` / `ImagePullBackOff` (for example
`mke3-backup`, `Failed to pull image
"registry.mirantis.com/cluster-upgrade-controller/cluster-upgrade-controller:<tag>"
... i/o timeout`) until the registry becomes reachable or the setting is
changed.

Check the live value:

```sh
kubectl -n system-upgrade get configmap default-controller-env \
  -o jsonpath='{.data.SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY}{"\n"}'
```

`IfNotPresent`, or empty (SUC's default is `IfNotPresent`), needs nothing. If
it prints `Always`, patch it and restart SUC. The restart is required: SUC reads
the ConfigMap through `envFrom`, which Kubernetes never live-reloads.

```sh
kubectl -n system-upgrade patch configmap default-controller-env \
  --type merge \
  --patch '{"data":{"SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY":"IfNotPresent"}}'
kubectl -n system-upgrade rollout restart deployment system-upgrade-controller
kubectl -n system-upgrade rollout status deployment system-upgrade-controller
```

Do this **before** applying a `ClusterUpgrade`. A Job takes its pull policy
when SUC creates it and a Job's pod template cannot be edited afterwards, so
Jobs that already exist keep `Always`. After the change, confirm the pod of
the active step reports `IfNotPresent`:

```sh
kubectl -n system-upgrade get pods \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].imagePullPolicy}{"\n"}{end}'
```

## Verify the mirrored image's signature

`bootc-mirantis` cosign-signs the `bootc_image_ref` OS image it pushes to
`registry.mirantis.com`. Verify that signature against the source registry
before mirroring, and again against your internal registry afterwards if
your mirroring tool is not known to copy signature artifacts — see
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

## Ansible variables to set

### `vars/reg-creds` (copy from `vars/reg-creds.example`, gitignored)

One line per registry, `registry username password`. The playbook for setting registry credentials ([`reg-creds-playbook.yml`](../../ansible/reg-creds-playbook.yml)) uses this to:

1. `docker login` each registry on every target host.
2. Write `/etc/ostree/auth.json` on every target host — needed for
   `bootc switch`/`bootc upgrade` pulls.

List **every** registry host you actually pull from in air-gap — typically
your internal mirror host(s) standing in for `registry.mirantis.com`. Run
`reg-creds-playbook.yml` before `mke-install-playbook.yml`.

### `vars/common-vars.yml`

| Variable | Default | Air-gap action |
|---|---|---|
| `cluster_upgrade_controller_manifest` | `{{ playbook_dir }}/mke-bundle/controller-manifests/cluster-upgrade-controller-manifest.yaml` (node-fetched) | Override if deploying a different controller version than the one preloaded on this image, **or** if running `mke-post-install-playbook.yml` standalone from a different controller/directory than the one that ran install (the node-fetched default will not exist there) — point at a local path or internal mirror URL |
| `machine_config_controller_manifest` | `{{ playbook_dir }}/mke-bundle/controller-manifests/machine-config-controller-manifest.yaml` (node-fetched) | Same as above |
| `suc_crd_manifest_src` | `{{ playbook_dir }}/mke-bundle/controller-manifests/system-upgrade-controller-crd.yaml` (node-fetched) | Override if deploying a different SUC version than the one preloaded on this image, **or** if running `mke-post-install-playbook.yml` standalone from a different controller/directory than the one that ran install (the node-fetched default will not exist there) — point at a local path or internal mirror URL |
| `suc_controller_manifest_src` | `{{ playbook_dir }}/mke-bundle/controller-manifests/system-upgrade-controller.yaml` (node-fetched) | Same as above — and the image reference *inside* whatever manifest you point at must be reachable from cluster nodes |
| `deploy_suc` | `true` | Set `false` if you don't need scheduled OS/MKE upgrades and want to skip the whole SUC dependency chain |
| `deploy_cluster_upgrade_controller` | `true` | Set `false` to skip the install if not needed |
| `deploy_machine_config_controller` | `true` | Set `false` to skip the install if not needed |
| `docker_daemon_config_src` | `""` | Set to a `daemon.json` with `registry-mirrors` populated if your targets should transparently redirect `docker.io` pulls to your mirror instead of using fully-qualified mirror hostnames everywhere |

## Checklist

1. Mirror the artifacts in the table above; note down the internal hostnames/paths.
2. Create `vars/reg-creds` with every mirror registry host + credentials.
3. None of SUC, `cluster-upgrade-controller`, or `machine-config-controller`
   needs an override for a default install; set `deploy_suc: false` /
   `deploy_cluster_upgrade_controller: false` / `deploy_machine_config_controller: false`
   if you don't need one of them, or override `suc_crd_manifest_src`/
   `suc_controller_manifest_src`/`cluster_upgrade_controller_manifest`/
   `machine_config_controller_manifest` only if you deliberately want a
   different version than the one preloaded on this image.
4. Run `reg-creds-playbook.yml`, then `mke-install-playbook.yml`.
5. On an image built before 2026-10-29, set
   `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` to `IfNotPresent` after install and
   before the first `ClusterUpgrade` — see
   [Older images: SUC Job pull policy](#older-images-suc-job-pull-policy).
