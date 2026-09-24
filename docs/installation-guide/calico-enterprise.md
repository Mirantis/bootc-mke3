# Calico Enterprise

This document covers installing Tigera Calico Enterprise on top of a
`bootc-mke3` cluster: what has to be in place before a node ever boots,
what to check before running Tigera's installer, and the installer steps
themselves.

> [!IMPORTANT]
> **Verified live on 2026-09-24** against a 3-manager / 9-worker
> `bootc-mke3` cluster on AWS (image
> `r9.8-mcr29.6.1.1-mke3.9.6-cloud-20260922-83`, MKE 3.9.6 /
> Kubernetes `v1.34.9-mirantis-2`, Calico Enterprise `v3.23.2`, operator
> `v1.42.5`), installed as a **fresh** Calico Enterprise CNI with MKE
> deployed `--unmanaged-cni`. Every module and setting below was found by
> hitting the failure it prevents, and the whole procedure was then re-run
> in order on a second, freshly provisioned 12-node cluster with a real
> workload (see [Verification](#verification)). Tracked on
> [PRODENG-3783](https://mirantis.jira.com/browse/PRODENG-3783) (and
> [PRODENG-3366](https://mirantis.jira.com/browse/PRODENG-3366) for the
> earlier module set). The **migration** path from an MKE-managed Calico
> OSS install is still unverified — see [Before you begin](#before-you-begin).

## Scope

`bootc-mke3`'s responsibility is limited to **removing image-level
blockers** that prevent a Calico Enterprise install from succeeding —
kernel modules and NetworkManager interface ownership. It does not bundle
Calico Enterprise, does not install it, and does not sequence it into the
`ClusterUpgrade` upgrade flow. Installing, licensing, and upgrading Calico
Enterprise itself is the operator's own procedure with Tigera. This scope
was decided deliberately on PRODENG-3366: bundling Calico Enterprise into
the image was assessed and rejected, primarily because Tigera's image
distribution terms do not permit redistributing their images as part of a
published `bootc-mke3` build.

## Before you begin

- **A Tigera license key and registry pull credentials**, obtained from
  your Tigera account team or support representative.
- **A Kubernetes version compatible with your target Calico Enterprise
  release.** Confirm against Tigera's own compatibility matrix for the
  Kubernetes version MKE 3.9.x ships — this has not been confirmed for
  this stack and is an open item on PRODENG-3366.
- **Your encapsulation mode decided up front** (IPIP is Calico's default;
  VXLAN and WireGuard are the alternatives) — it changes which kernel
  modules actually matter at runtime, though the image preloads all three
  encapsulation module sets regardless.

> [!WARNING]
> **MKE3 installs Calico Open Source as its CNI by default, directly rather
> than via Tigera's operator.** The validated path is to install MKE with
> `--unmanaged-cni` so that no MKE-managed Calico exists and the Tigera
> operator owns the CNI from the first node — see
> [MKE installed with `--unmanaged-cni`](#mke-installed-with---unmanaged-cni).
> Converting an *existing* MKE-managed Calico OSS cluster to Calico
> Enterprise has not been tested; Tigera's documented "Calico → Calico
> Enterprise" upgrade assumes an operator-installed OSS baseline that MKE3
> does not use. Do not attempt that on a cluster with live workloads
> without Tigera support confirming a migration path for it.

## 1. Provisioning: preload the required kernel modules

The image loads a fixed kernel-module allowlist at boot and then sets
`kernel.modules_disabled=1`, a **one-way latch**: no module can be loaded
for the rest of that boot session by any means once it applies — not
`modprobe`, not on-demand autoload, not a sysctl or `MachineConfigChange`.
See [Image architecture](image-architecture.md#kernel-modules) for the
full mechanism.

As of the current `bootc-mirantis` `main`, the image's boot-time allowlist
already includes Calico Enterprise's `ipip`, IPv6 netfilter, IPVS/SCTP
match, logging, L7 proxy/TPROXY, and bandwidth-QoS modules (added
2026-09-08, [PRODENG-3366](https://mirantis.jira.com/browse/PRODENG-3366)).
Six further modules that Calico Enterprise needs are present in the image's
kernel package but **not on that allowlist**
([PRODENG-3783](https://mirantis.jira.com/browse/PRODENG-3783)); each was
found by hitting its failure on the validation cluster:

| Module | Failure without it |
|---|---|
| `nfnetlink_queue`, `nfnetlink_log` | Felix exits at startup (Tigera support case 00010382) |
| `xt_NFQUEUE`, `xt_NFLOG` | `iptables-nft-restore`: `Extension NFQUEUE/NFLOG ... missing kernel module?` |
| `ip_set_hash_ipport` | `Failed to complete ipset restore` for the per-service `hash:ip,port` ipsets |
| `nft_log` | `RULE_APPEND failed (No such file or directory)` on every `-j NFLOG` flow-log rule; Felix panics after ~10 retries and `calico-node` crash-loops, `calico-apiserver` with it. iptables-nft emits NFLOG as the native nftables `log` expression, so `xt_NFLOG` alone is not enough; flow logs are always-on in Calico Enterprise (`FELIX_FLOWLOGSFILEENABLED=true` is hard-coded by the operator) and cannot be turned off via `FelixConfiguration` |

Add them at provision time using the extension point below. Whether the
image's own allowlist should grow to include them is tracked on
PRODENG-3783; the recipes here work on today's images and stay correct if
it does.

Full list to preload (safe to preload all of it regardless of which
encapsulation mode or optional features you use — an unused loaded module
costs nothing, a missing one costs a rebuild-and-reboot):

```
ipip
ip6_tables
ip6table_filter
ip6table_mangle
ip6table_nat
ip6table_raw
ip6t_rpfilter
iptable_mangle
iptable_nat
iptable_raw
xt_sctp
xt_ipvs
ip_vs
xt_LOG
nf_log_syslog
nfnetlink_queue
nfnetlink_log
xt_NFQUEUE
xt_NFLOG
nft_log
ip_set_hash_ipport
xt_socket
xt_TPROXY
tun
sch_tbf
sch_ingress
cls_u32
act_mirred
ifb
sch_htb
```

> [!NOTE]
> Should a future image ship these six modules on its own allowlist, the two
> provision-time recipes below become a no-op — both are written to be safe
> to leave in place permanently rather than removed once the image catches
> up. Verify with `lsmod` either way (see [Verification](#verification)).

### Bare metal (kickstart)

Per [Preload additional kernel modules](iso-editions.md#preload-additional-kernel-modules),
a plain `%post` drop-in is effective on **first boot** — no reboot needed,
because the installed system has not booted yet when `%post` runs:

```
%post --erroronfail
cat > /etc/modules-load.d/calico-ee-modules.conf <<'EOF'
ipip
ip6_tables
ip6table_filter
ip6table_mangle
ip6table_nat
ip6table_raw
ip6t_rpfilter
iptable_mangle
iptable_nat
iptable_raw
xt_sctp
xt_ipvs
ip_vs
xt_LOG
nf_log_syslog
nfnetlink_queue
nfnetlink_log
xt_NFQUEUE
xt_NFLOG
nft_log
ip_set_hash_ipport
xt_socket
xt_TPROXY
tun
sch_tbf
sch_ingress
cls_u32
act_mirred
ifb
sch_htb
EOF
%end
```

### Cloud (cloud-init — AMI/QCOW2 builds only)

Unlike kickstart's `%post`, cloud-init's `write_files`/`runcmd` execute
against an **already-booted** node — `cloud-final.service` runs well after
`sysinit.target`, where the module latch has already been applied for that
boot. A file written here only takes effect starting the *next* boot, so
it needs a self-triggered reboot. This mirrors the worked `xt_statistic`
example in
[Join machines with no-touch join](../operations-guide/join-machines-no-touch.md#2-inject-the-credential-into-each-new-machine)
(its "Kernel module preload" requirement bullet), adapted here without
that example's swarm-join gate, since a Calico
Enterprise install is not part of the built-in join flow:

```yaml
#cloud-config
write_files:
  - path: /etc/modules-load.d/calico-ee-modules.conf
    permissions: '0644'
    content: |
      ipip
      ip6_tables
      ip6table_filter
      ip6table_mangle
      ip6table_nat
      ip6table_raw
      ip6t_rpfilter
      iptable_mangle
      iptable_nat
      iptable_raw
      xt_sctp
      xt_ipvs
      ip_vs
      xt_LOG
      nf_log_syslog
      nfnetlink_queue
      nfnetlink_log
      xt_NFQUEUE
      xt_NFLOG
      nft_log
      ip_set_hash_ipport
      xt_socket
      xt_TPROXY
      tun
      sch_tbf
      sch_ingress
      cls_u32
      act_mirred
      ifb
      sch_htb
  - path: /etc/systemd/system/calico-ee-modules-reboot.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Reboot once to activate Calico Enterprise module preload
      ConditionPathExists=!/var/lib/calico-ee-modules-reboot-done

      [Service]
      Type=oneshot
      ExecStart=/bin/sh -c 'touch /var/lib/calico-ee-modules-reboot-done; lsmod | grep -q "^nft_log " && exit 0; systemctl reboot'

      [Install]
      WantedBy=multi-user.target
runcmd:
  - systemctl enable --now calico-ee-modules-reboot.service
```

The `[Install]` section is required: without it `systemctl enable` fails
and the unit never runs (found while validating this recipe). The `lsmod`
check uses `nft_log` because it is the last module in the list to have
been added — if it is loaded the whole file was processed.

Run this **before** installing Calico Enterprise, not after, so Felix
never starts even once without the modules loaded.

> [!NOTE]
> **Terraform `terraform/aws` in this repo does not pass custom `user_data`
> through** — the MKE3 module (`is_bootc_based = true`) renders its own
> cloud-init and silently ignores anything else. On clusters provisioned
> that way, apply the drop-in over SSH before `disable_sshd_after_install`
> takes effect, then reboot each node; the validation cluster was prepared
> exactly this way. See
> [Provision with Terraform on AWS](provision-terraform-aws.md).

## 2. Quick installation points

Check these on a target node before running the Tigera installer.

### Kernel modules present and loaded

```sh
cat /usr/lib/modules-load.d/mke-modules.conf /etc/modules-load.d/*.conf 2>/dev/null
lsmod | grep -E '^(ipip|nfnetlink_queue|nfnetlink_log|xt_NFQUEUE|xt_NFLOG|nft_log|ip_set_hash_ipport|ip6_tables|xt_ipvs) '
sysctl kernel.modules_disabled   # expect 1 -- confirms the latch, not a problem
```

If any expected module is missing from `lsmod`, do not proceed —
`modprobe` cannot fix it on a running node; see
[Provisioning](#1-provisioning-preload-the-required-kernel-modules) above
and reprovision or reboot after adding the drop-in.

### MKE installed with `--unmanaged-cni`

Install MKE with `--unmanaged-cni` so it deploys no Calico OSS of its own
and the Tigera operator owns the CNI from the start. With the
`mke-install-playbook.yml` in this repo, append the flag to
`mke_install_flags` in an extra-vars file — keep the four default entries
from `vars/common-vars.yml`, since overriding the list replaces it:

```yaml
# calico-ee-overrides.yml
mke_install_flags:
  - '--san="{{ mke_url }}"'
  - '--default-node-orchestrator="kubernetes"'
  - '--nodeport-range="32768-35535"'
  - "--force-minimums"
  - "--unmanaged-cni"
disable_firewalld: true
```

```sh
ansible-playbook -i inventory.ini mke-install-playbook.yml -e @calico-ee-overrides.yml
```

> [!WARNING]
> Pass `--unmanaged-cni` as a CLI flag only. Setting `unmanaged_cni = true`
> in an MKE config TOML (`mke_config_src`) instead — or alongside — makes
> `mke install` fail with `TigopCompatibleManifest is unexpectedly false`.
> The validated install used no `mke_config_src` TOML at all.

Until step 3 completes, every node is `NotReady` (taint
`node.kubernetes.io/not-ready`) and no pod-network pods schedule; that is
expected, not a failure. Confirm MKE deployed no CNI:

```sh
kubectl get ds -n kube-system calico-node   # expect: NotFound
```

### MKE privileged-attributes grant for the Tigera service accounts

MKE's admission controller refuses pods that request `hostNetwork`,
`hostPath` mounts, `hostPID` or `privileged` unless the pod's
ServiceAccount is on the cluster-config allowlist — and the Tigera operator
creates such pods (`calico-node`, `calico-typha`, `calico-apiserver`,
`csi-node-driver`) under its own ServiceAccounts, not as an MKE admin. On the
validation cluster the operator stalled at the first two with:

```
deployments.apps "calico-typha" is forbidden: non-admin user "tigera-operator:tigera-operator"
[service account "calico-system:calico-typha"]. The configured privileged attributes access
... for service accounts ("[hostbindmounts hostipc hostnetwork hostpid kernelcapabilities
privileged]")("[system-upgrade:system-upgrade]") lack required permissions to use attributes
[hostnetwork] for resource calico-typha
```

Before step 3, append the five `calico-system` ServiceAccounts to
`priv_attributes_service_accounts` in the MKE cluster-config TOML, following
the download / edit / upload procedure in
[Run privileged support containers on MKE](../operations-guide/privileged-support-containers.md#2-grant-the-privilege-attributes)
— **preserving** the `system-upgrade:system-upgrade` entry a default install
already carries:

```toml
[cluster_config]
  priv_attributes_allowed_for_service_accounts = ["hostIPC", "hostNetwork", "hostPID", "hostBindMounts", "privileged", "kernelCapabilities"]
  priv_attributes_service_accounts = ["system-upgrade:system-upgrade", "calico-system:calico-node", "calico-system:calico-typha", "calico-system:calico-kube-controllers", "calico-system:calico-apiserver", "calico-system:csi-node-driver"]
```

`ansible/tasks/helpers/suc_priv_grant.py <downloaded.toml> <namespace:sa>`
performs the same merge for one entry at a time and can be run once per
ServiceAccount on the downloaded file before uploading it. The grant takes
effect on the next admission decision; if the operator already hit the
error it retries on its own within about a minute. If you later enable
further Tigera components (compliance, intrusion detection, packet capture,
egress gateways), watch `kubectl get tigerastatus` for the same `forbidden`
message and add the ServiceAccount it names.


### CNI interfaces unmanaged by NetworkManager

The image ships
`/usr/lib/NetworkManager/conf.d/10-calico-unmanaged.conf`, marking
Calico's veth pairs and every encapsulation mode's tunnel device unmanaged
so NetworkManager does not compete with Calico for their configuration —
see [Image architecture](image-architecture.md#networkmanager). Verify:

```sh
cat /usr/lib/NetworkManager/conf.d/10-calico-unmanaged.conf
nmcli device status   # cali*, tunl*, vxlan.calico, wireguard.cali devices should read "unmanaged"
```

> [!WARNING]
> If you or another provisioning step drop a file into `/etc/NetworkManager/conf.d/`
> that also sets `unmanaged-devices`, it **replaces** the list above
> rather than merging with it — `/usr/lib` snippets parse first, but the
> key itself is not merged across files. Restate the same device list in
> any override, or NetworkManager resumes managing Calico's interfaces.

### firewalld

Tigera requires firewalld disabled on nodes running Calico Enterprise. The
installer's default (`disable_firewalld: false`) keeps firewalld running
with per-service port rules that do not cover Calico Enterprise's own
ports — BGP 179, Typha 5473, IPIP (protocol 4), VXLAN 4789, WireGuard
51820/51821 — and on the validation cluster that produced Typha and BGP
connectivity failures until firewalld was disabled. Set
`disable_firewalld: true` for managers (as in the overrides file above; see
[Harden MKE3 / Kubernetes](../operations-guide/harden-mke3-kubernetes.md)).
No-touch-joined workers are never touched by the installer, so disable it
in the same provisioning payload as the module preload:

```
%post --erroronfail
systemctl disable firewalld.service
%end
```

or, cloud-init `runcmd`:

```yaml
runcmd:
  - systemctl disable --now firewalld.service
```

### `calico-selinux`

The image already installs Tigera's `calico-selinux` RPM
(`bootc/mke3/Containerfile-template`) — no action needed here.

## 3. Install Calico Enterprise components

Once the checks above pass, run Tigera's own operator-based installer.
Set `$CALICO_EE_VERSION` to the release your license entitles you to
(Tigera support case 00010382 was raised against 3.22; 3.23.x is current
at the time of writing — do not assume either applies to your
entitlement).

```sh
CALICO_EE_VERSION=v3.23.2   # confirm against your Tigera entitlement

# 1. Operator and CRDs
kubectl create -f https://downloads.tigera.io/ee/${CALICO_EE_VERSION}/manifests/operator-crds.yaml
kubectl create -f https://downloads.tigera.io/ee/${CALICO_EE_VERSION}/manifests/tigera-operator.yaml

# 2. Prometheus operator (skip if you already run one >= v0.40.0)
kubectl create -f https://downloads.tigera.io/ee/${CALICO_EE_VERSION}/manifests/tigera-prometheus-operator.yaml

# 3. Registry pull secret -- from your Tigera support representative,
#    or your own private-registry mirror credentials
kubectl create secret generic tigera-pull-secret \
  --type=kubernetes.io/dockerconfigjson -n tigera-operator \
  --from-file=.dockerconfigjson=<path/to/pull-secret.json>

# 4. Custom resources -- trim to what this stack can run (see below), set
#    flexVolumePath: None, then create
curl -O -L https://downloads.tigera.io/ee/${CALICO_EE_VERSION}/manifests/custom-resources.yaml
# edit custom-resources.yaml as described in the next two subsections
kubectl create -f custom-resources.yaml

# Watch rollout
watch kubectl get tigerastatus
```

Wait until `apiserver` reports `Available` before continuing.

```sh
# 5. License
kubectl create -f </path/to/license.yaml>
watch kubectl get tigerastatus
```

### Which CRs from `custom-resources.yaml` to apply

The shipped Enterprise file contains `Installation`, `APIServer`,
`Monitor`, `Manager`, `IntrusionDetection`, `LogStorage`, `LogCollector`
and `PolicyRecommendation`. `LogStorage` runs Elasticsearch and needs a
default `StorageClass` with dynamic provisioning; a `bootc-mke3` install
has none (`kubectl get sc` → `No resources found`), and `Manager`,
`IntrusionDetection`, `LogCollector` and `PolicyRecommendation` depend on
it. Without storage, keep **`Installation`, `APIServer` and `Monitor`** and
delete the rest — that is what the validation run applied. Keep `Monitor`
even though it looks optional: the Tigera operator creates the RBAC for the
`tigera-prometheus-operator` deployed in step 2 only when a `Monitor` CR
exists, and without it that operator crash-loops with `no controller can be
started, check the RBAC permissions of the service account`.

### `Installation` CR: `flexVolumePath: None`

bootc mounts `/usr` read-only, so the default FlexVolume driver path
(`/usr/libexec/kubernetes/kubelet-plugins/volume/exec/`) cannot be written
and `calico-node`'s `flexvol-driver` init container fails, blocking the
DaemonSet on every node. Disable it in the `Installation` CR inside
`custom-resources.yaml` before step 4 (MKE does not use FlexVolume):

```yaml
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  variant: TigeraSecureEnterprise
  flexVolumePath: None
  imagePullSecrets:
    - name: tigera-pull-secret
  # ... rest of the shipped CR unchanged
```

> [!NOTE]
> These steps are the validated **fresh-install** path (MKE deployed
> `--unmanaged-cni`, no MKE-managed Calico present). For a cluster that
> already runs MKE's baked-in Calico OSS, what the `Installation` CR must
> say about the existing `calico-node` DaemonSet is the unconfirmed
> migration-path question flagged in [Before you begin](#before-you-begin)
> — do not skip that confirmation because the commands look identical.

### License state gates several features silently

Felix reads the `LicenseKey` at startup and disables licensed features it
cannot validate, logging warnings rather than failing. With an expired key
(past its 30-day grace) the validation cluster logged
`License for Flow Logs File Output feature has expired. Flow logs will be
disabled.` and the same for L7 logs and Prometheus metrics, while
`tigerastatus` stayed `Available` and `NetworkPolicy` enforcement kept
working. Check `kubectl get licensekeys.projectcalico.org default -o
jsonpath='{.status}'` for `expiry` and `maxnodes` before reading a quiet
`tigerastatus` as "everything is on". The `-j NFLOG` collector rules are
programmed regardless of license state — `nft_log` is required even on an
unlicensed cluster.

## Verification

Platform checks:

- `lsmod` still shows every module from
  [step 1](#1-provisioning-preload-the-required-kernel-modules) loaded,
  and `sysctl kernel.modules_disabled` is still `1` — the fix must not
  come from weakening the image's hardening.
- `kubectl get pods -n calico-system` — `calico-node` `Running` with a
  restart count of `0`, not just eventually-`Running` after crash-looping.
  On the validation cluster all 12 were `1/1` within two minutes of the
  privileged-attributes grant, with zero restarts.
- `nmcli device status` — Calico's interfaces (`cali*`, and whichever
  tunnel device your encapsulation mode uses) read `unmanaged`.
- `kubectl get tigerastatus` — every applied component `Available`.
- BGP mesh: `kubectl exec -n calico-system <calico-node pod> -c calico-node
  -- birdcl show protocols` lists every other node as `Established`
  (11 of 11 on the validation cluster).

Dataplane checks with a real workload (all passed on the validation
cluster; a 6-replica `nginx` Deployment spread across the workers, a
`ClusterIP` and a `NodePort` Service, and `curl` client pods on other
nodes):

- Pod-to-pod across nodes: `curl` from a client pod to each backend pod IP
  returns `200`, including every cross-node pair (IPIP encapsulation in the
  default `ippool`).
- Service: repeated `curl http://<service>/` from a pod returns `200`;
  `nslookup <service>.<ns>.svc.cluster.local` resolves to the ClusterIP.
- NodePort from a pod to a worker's InternalIP returns `200`; pod egress to
  the internet returns `200`.
- Policy enforcement, using `projectcalico.org/v3` `NetworkPolicy` through
  the Enterprise API server: a namespace-wide `selector: all()` deny with
  `types: [Ingress, Egress]` blocks the client immediately; adding an
  ingress allow on the backend from `app == 'client'` plus a matching client
  egress rule (TCP 80 to the backend and UDP 53) restores exactly that
  path, while a third pod with the egress allow but no ingress allow on the
  backend stays blocked.

## Known gaps

- Validation covered steps 1-5 plus the dataplane checks above on 12
  nodes. Flow-log, L7-log and Prometheus file/metrics output could not be
  verified: the only license available had expired (see
  [License state](#license-state-gates-several-features-silently)).
  `LogStorage`, `Manager`, `IntrusionDetection`, `LogCollector` and
  `PolicyRecommendation` were not applied (no StorageClass).
- The Ansible installer has no task for the Tigera privileged-attributes
  grant; it is done by hand (or with `suc_priv_grant.py`) between the MKE
  install and step 3.
- The OSS-to-Enterprise migration path for an MKE-managed (non-operator)
  Calico install is unconfirmed; Tigera's documented upgrade path assumes
  an operator-installed OSS baseline that MKE3 does not use.
- Kubernetes `v1.34.9-mirantis-2` / MKE 3.9.6 with Calico Enterprise
  `v3.23.2` has not been checked against Tigera's published compatibility
  matrix; the validation install worked, but that is an observation, not
  confirmed Tigera support coverage.
- The six PRODENG-3783 modules (`nfnetlink_queue`, `nfnetlink_log`,
  `xt_NFQUEUE`, `xt_NFLOG`, `nft_log`, `ip_set_hash_ipport`) are not on
  the allowlist of any released `bootc-mirantis` image; provision-time
  preload is the only path today. Whether to add them to the image is an
  open decision on PRODENG-3783.
- `xt_limit` (`-m limit`) fails the same way on this image; Felix does not
  currently emit it, so it is not preloaded.
- The Ansible installer has no dedicated variable for `--unmanaged-cni`;
  it is passed by overriding the whole `mke_install_flags` list.
