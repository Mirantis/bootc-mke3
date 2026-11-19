# Air-gapped bootc-mke3

Instructions and prerequisites to install and upgrade bootc-mke3 correctly in an air-gapped environment.

See also: [Install bootc-mke3](install-bootc-mke3.md), [Upgrade bootc-mke3](../operations-guide/upgrade-with-controller.md) (or the [Ansible exception path](../operations-guide/upgrade-with-ansible.md)).

## Prerequisites

- The `kubectl` binary must be installed on the machine where you run ansible.

## What must be mirrored to your internal registry

Normally, public hosts (`registry.mirantis.com`, `docker.io`, `github.com`)
supply each artifact below. In an air-gapped environment, each artifact
needs a mirrored copy. The controller or the targets must be able to reach
the copy (noted for each row). You must also change the corresponding Ansible
variable to point to the copy.

| Artifact | Pulled by | Reachable from | Default source | Mirror via variable |
|---|---|---|---|---|
| bootc OS image for upgrades | `bootc switch` / `bootc upgrade` (`tasks/bootc-upgrade-tasks.yml`) | targets | `registry.mirantis.com` | `vars/upgrade-vars.yml: bootc_image_ref` |
| `cluster-upgrade-controller` manifest | `kubectl apply -f` | controller | **already air-gap-safe by default.** `tasks/fetch-cluster-upgrade-controller-manifest-tasks.yml` copies the exact static manifest that bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/cluster-upgrade-controller-manifest.yaml`) from a node to the controller before it applies the manifest. No mirroring is necessary unless you override it | `vars/common-vars.yml: cluster_upgrade_controller_manifest` |
| Container image referenced inside that manifest (controller pod image) | Kubernetes, after the controller applies the manifest | cluster nodes (through kubelet) | **already air-gap-safe by default.** The image tag in the node-fetched manifest is the tag that `mke-images.service` preloaded into the local image store of the node at boot | not applicable, unless you override `cluster_upgrade_controller_manifest` with a different manifest. Then mirror each tag that *that* manifest references |
| `machine-config-controller` manifest | `kubectl apply -f` | controller | **already air-gap-safe by default.** `tasks/fetch-machine-config-controller-manifest-tasks.yml` copies the exact static manifest that bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/machine-config-controller-manifest.yaml`) from a node to the controller before it applies the manifest. No mirroring is necessary unless you override it | `vars/common-vars.yml: machine_config_controller_manifest` |
| Container images referenced inside that manifest (controller + node agent pods) | Kubernetes, after the controller applies the manifest | cluster nodes (through kubelet) | **already air-gap-safe by default.** The image tags in the node-fetched manifest are the tags that `mke-images.service` preloaded into the local image store of the node at boot | not applicable, unless you override `machine_config_controller_manifest` with a different manifest. Then mirror each tag that *that* manifest references |
| System Upgrade Controller CRDs/manifest | `kubectl apply -f` | controller | **already air-gap-safe by default.** `tasks/fetch-controller-manifests-tasks.yml` copies the exact manifests that bootc-mirantis staged into the image (`/usr/share/mke-controllers/manifests/`) from a node to the controller before it applies them. No mirroring is necessary unless you override it | `vars/common-vars.yml: suc_crd_manifest_src`, `suc_controller_manifest_src`. Override them only if you deliberately want a different SUC version from the version that the image preloads |
| `rancher/system-upgrade-controller` container image (referenced *inside* the fetched manifest) | Kubernetes, after the controller applies that manifest | cluster nodes (through kubelet) | **already air-gap-safe by default.** The exact tag in the fetched manifest is the tag that `mke-images.service` preloaded into the local image store of the node at boot. Kubelet therefore does not need to pull it | not applicable, unless you override `suc_controller_manifest_src` with a different manifest. Then mirror each tag that *that* manifest references |
| Container images run by the Jobs that SUC creates during a `ClusterUpgrade` (for the `ClusterUpgrade` steps, the `cluster-upgrade-controller` image itself) | Kubernetes, when SUC creates the Job of each step | cluster nodes (through kubelet) | **air-gap-safe only when `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` is `IfNotPresent`.** `mke-images.service` preloads the images. But SUC sets this pull policy on each container of each Job that it creates, and upstream ships it as `Always`. The kubelet then tries to reach the registry at each step, although the image is already on the node. Images built on or after 2026-10-29 have `IfNotPresent` in the staged SUC manifest. Images built before that date need the one-time patch in [Older images: SUC Job pull policy](#older-images-suc-job-pull-policy) | not applicable when the policy is `IfNotPresent`. Mirror the images only if you keep `Always` on purpose |

For a fully air-gapped run, you must mirror at minimum the
`bootc_image_ref` OS image. For a default install on an image built on or
after 2026-10-29, SUC, `cluster-upgrade-controller`, and
`machine-config-controller` need no further action. Their manifests and
container images come from what bootc-mirantis already staged into the image.
Ansible fetches them from a node and not from the network. On older images, you
must also do one manual step before the first upgrade: [patch the SUC Job pull
policy](#older-images-suc-job-pull-policy).

## Older images: SUC Job pull policy

On images built before 2026-10-29, the SUC manifest staged in
`/usr/share/mke-controllers/manifests/` (identical to upstream SUC v0.14.0)
sets `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY: Always` in the
`system-upgrade/default-controller-env` ConfigMap. The install patches only
`SYSTEM_UPGRADE_JOB_ACTIVE_DEADLINE_SECONDS` in that ConfigMap, so the value
stays in the cluster. On an air-gapped cluster, every
`ClusterUpgrade` step then stays at `ErrImagePull` / `ImagePullBackOff` (for example
`mke3-backup`, `Failed to pull image
"registry.mirantis.com/cluster-upgrade-controller/cluster-upgrade-controller:<tag>"
... i/o timeout`). This continues until the registry is reachable or you
change the setting.

Verify the live value:

```sh
kubectl -n system-upgrade get configmap default-controller-env \
  -o jsonpath='{.data.SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY}{"\n"}'
```

If the value is `IfNotPresent`, or empty (the SUC default is `IfNotPresent`), no action is necessary. If
the command prints `Always`, patch the value and restart SUC. You must restart SUC. SUC reads
the ConfigMap through `envFrom`, and Kubernetes never reloads it live.

```sh
kubectl -n system-upgrade patch configmap default-controller-env \
  --type merge \
  --patch '{"data":{"SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY":"IfNotPresent"}}'
kubectl -n system-upgrade rollout restart deployment system-upgrade-controller
kubectl -n system-upgrade rollout status deployment system-upgrade-controller
```

Do this **before** you apply a `ClusterUpgrade`. A Job takes its pull policy
when SUC creates it, and you cannot edit the pod template of a Job afterwards.
Jobs that already exist keep `Always`. After the change, verify that the pod of
the active step reports `IfNotPresent`:

```sh
kubectl -n system-upgrade get pods \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].imagePullPolicy}{"\n"}{end}'
```

## Verify the mirrored image's signature

`bootc-mirantis` signs the `bootc_image_ref` OS image with cosign when it
pushes the image to `registry.mirantis.com`. Verify that signature against
the source registry before you mirror. Verify it again against your internal
registry afterwards, if your mirroring tool is not known to copy signature
artifacts. See
[Verify bootc-mke3 image signatures](../operations-guide/verify-image-signatures.md).

## Ansible variables to set

### `vars/reg-creds` (copy from `vars/reg-creds.example`, gitignored)

Use one line for each registry: `registry username password`. The playbook to set registry credentials ([`reg-creds-playbook.yml`](../../ansible/reg-creds-playbook.yml)) uses this file to do these actions:

1. Run `docker login` for each registry on every target host.
2. Write `/etc/ostree/auth.json` on every target host. The
   `bootc switch`/`bootc upgrade` pulls need this file.

List **every** registry host that you pull from in the air-gap. Typically,
these are your internal mirror hosts that replace `registry.mirantis.com`. Run
`reg-creds-playbook.yml` before `mke-install-playbook.yml`.

### `vars/common-vars.yml`

| Variable | Default | Air-gap action |
|---|---|---|
| `cluster_upgrade_controller_manifest` | `{{ playbook_dir }}/mke-bundle/controller-manifests/cluster-upgrade-controller-manifest.yaml` (node-fetched) | Override it if you deploy a different controller version from the version that the image preloads. Override it also if you run `mke-post-install-playbook.yml` standalone from a different controller or directory than the one that ran the install. The node-fetched default does not exist there. Point it to a local path or an internal mirror URL |
| `machine_config_controller_manifest` | `{{ playbook_dir }}/mke-bundle/controller-manifests/machine-config-controller-manifest.yaml` (node-fetched) | Same as above |
| `suc_crd_manifest_src` | `{{ playbook_dir }}/mke-bundle/controller-manifests/system-upgrade-controller-crd.yaml` (node-fetched) | Override it if you deploy a different SUC version from the version that the image preloads. Override it also if you run `mke-post-install-playbook.yml` standalone from a different controller or directory than the one that ran the install. The node-fetched default does not exist there. Point it to a local path or an internal mirror URL |
| `suc_controller_manifest_src` | `{{ playbook_dir }}/mke-bundle/controller-manifests/system-upgrade-controller.yaml` (node-fetched) | Same as above. Also, the cluster nodes must be able to reach the image reference *inside* the manifest that you select |
| `deploy_suc` | `true` | Set it to `false` if you do not need scheduled OS/MKE upgrades and you want to skip the whole SUC dependency chain |
| `deploy_cluster_upgrade_controller` | `true` | Set it to `false` to skip the install if it is not necessary |
| `deploy_machine_config_controller` | `true` | Set it to `false` to skip the install if it is not necessary |
| `docker_daemon_config_src` | `""` | Set it to a `daemon.json` with `registry-mirrors` populated. Do this if you want your targets to redirect `docker.io` pulls to your mirror transparently, and not use fully-qualified mirror hostnames everywhere |

## Checklist

1. Mirror the artifacts in the table above. Record the internal hostnames and paths.
2. Create `vars/reg-creds` with every mirror registry host and its credentials.
3. For a default install, none of SUC, `cluster-upgrade-controller`, or
   `machine-config-controller` needs an override. If you do not need one of
   them, set `deploy_suc: false` /
   `deploy_cluster_upgrade_controller: false` / `deploy_machine_config_controller: false`.
   Override `suc_crd_manifest_src`/
   `suc_controller_manifest_src`/`cluster_upgrade_controller_manifest`/
   `machine_config_controller_manifest` only if you deliberately want a
   different version from the version that the image preloads.
4. Run `reg-creds-playbook.yml`, then `mke-install-playbook.yml`.
5. On an image built before 2026-10-29, set
   `SYSTEM_UPGRADE_JOB_IMAGE_PULL_POLICY` to `IfNotPresent` after the install and
   before the first `ClusterUpgrade`. See
   [Older images: SUC Job pull policy](#older-images-suc-job-pull-policy).
