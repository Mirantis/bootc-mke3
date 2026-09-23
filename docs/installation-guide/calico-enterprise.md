# Calico Enterprise

This document covers installing Tigera Calico Enterprise on top of a
`bootc-mke3` cluster: what has to be in place before a node ever boots,
what to check before running Tigera's installer, and the installer steps
themselves.

> [!IMPORTANT]
> **Not yet verified end-to-end.** This procedure has not been run against
> a live Calico Enterprise install — the team holds no Tigera license or
> registry entitlement today. It is compiled from Tigera's published
> requirements/install docs, `lsmod` evidence gathered on shipped images,
> and one customer failure report (Tigera support case 00010382), tracked
> as [PRODENG-3366](https://mirantis.jira.com/browse/PRODENG-3366) and
> [PRODENG-3783](https://mirantis.jira.com/browse/PRODENG-3783). Treat
> every step as a starting point to validate, not a confirmed runbook.

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
> **MKE3 already runs Calico as its CNI, installed directly by MKE rather
> than by Tigera's operator.** Tigera's documented "Calico → Calico
> Enterprise" upgrade path assumes an operator-installed Calico Open
> Source baseline; that assumption does not hold here. Do not run this
> procedure against a cluster with live workloads until Tigera support has
> confirmed a migration path for an MKE-managed, non-operator Calico
> install — ask them directly, referencing your MKE3/Calico OSS versions.
> This document does not yet have that confirmation.

## 1. Provisioning: preload the required kernel modules

The image loads a fixed kernel-module allowlist at boot and then sets
`kernel.modules_disabled=1`, a **one-way latch**: no module can be loaded
for the rest of that boot session by any means once it applies — not
`modprobe`, not on-demand autoload, not a sysctl or `MachineConfigChange`.
See [Image architecture](image-architecture.md#kernel-modules) for the
full mechanism.

As of the current `bootc-mirantis` `main`, the image preloads Calico
Enterprise's `ipip`, IPv6 netfilter, IPVS/SCTP match, logging, L7
proxy/TPROXY, and bandwidth-QoS modules (added 2026-09-08,
[PRODENG-3366](https://mirantis.jira.com/browse/PRODENG-3366)). Two
further modules Felix requires at startup, `nfnetlink_queue` and
`nfnetlink_log` (Tigera support case 00010382 — Felix crash-loops without
them), are in an **open, not-yet-merged** PR
([bootc-mirantis#210](https://github.com/Mirantis/bootc-mirantis/pull/210),
[PRODENG-3783](https://mirantis.jira.com/browse/PRODENG-3783)). Until that
merges and you're on an image built after it, add them yourself at
provision time using the same extension point.

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
> Once you're on an image that already ships `nfnetlink_queue`/
> `nfnetlink_log` (post-#210), the two provision-time recipes below become
> a no-op — both are written to be safe to leave in place permanently
> rather than removed once the image catches up. Verify with `lsmod`
> either way (see [Verification](#verification)).

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
      ExecStart=/bin/sh -c 'touch /var/lib/calico-ee-modules-reboot-done; lsmod | grep -q nfnetlink_queue && exit 0; systemctl reboot'
runcmd:
  - systemctl enable --now calico-ee-modules-reboot.service
```

Run this **before** installing Calico Enterprise, not after, so Felix
never starts even once without the modules loaded.

## 2. Quick installation points

Check these on a target node before running the Tigera installer.

### Kernel modules present and loaded

```sh
cat /usr/lib/modules-load.d/mke-modules.conf /etc/modules-load.d/*.conf 2>/dev/null
lsmod | grep -E 'ipip|nfnetlink_queue|nfnetlink_log|ip6_tables|xt_ipvs'
sysctl kernel.modules_disabled   # expect 1 -- confirms the latch, not a problem
```

If any expected module is missing from `lsmod`, do not proceed —
`modprobe` cannot fix it on a running node; see
[Provisioning](#1-provisioning-preload-the-required-kernel-modules) above
and reprovision or reboot after adding the drop-in.

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

Tigera requires firewalld disabled on nodes running Calico Enterprise —
it interferes with the rules Felix installs. On managers this is handled
by the MKE3 Ansible installer's `disable_firewalld` variable (see
[Harden MKE3 / Kubernetes](../operations-guide/harden-mke3-kubernetes.md));
no-touch-joined workers are never touched by the installer, so disable it
in the same provisioning payload as the module preload above:

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

# 4. Custom resources -- review before applying; uncomment optional
#    features (compliance, packet capture) you want enabled
curl -O -L https://downloads.tigera.io/ee/${CALICO_EE_VERSION}/manifests/custom-resources.yaml
# edit custom-resources.yaml as needed
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

> [!NOTE]
> Steps 1-4 are the same regardless of whether this is a fresh install or
> a migration from MKE's baked-in Calico OSS. What differs is what
> `custom-resources.yaml`'s `Installation` CR should say about the
> existing `calico-node` DaemonSet MKE already runs, and that is exactly
> the unconfirmed migration-path question flagged in
> [Before you begin](#before-you-begin) — do not skip that confirmation
> because these commands look identical to a fresh install.

## Verification

- `lsmod` still shows every module from
  [step 1](#1-provisioning-preload-the-required-kernel-modules) loaded,
  and `sysctl kernel.modules_disabled` is still `1` — the fix must not
  come from weakening the image's hardening.
- `kubectl get pods -n calico-system` — `calico-node` `Running` with a
  restart count of `0`, not just eventually-`Running` after crash-looping.
- `nmcli device status` — Calico's interfaces (`cali*`, and whichever
  tunnel device your encapsulation mode uses) read `unmanaged`.
- `watch kubectl get tigerastatus` — every component `Available`.
- Cross-node pod-to-pod connectivity on your chosen encapsulation mode
  (e.g. `tunl0` present and carrying traffic in IPIP mode).

## Known gaps

- No live Calico Enterprise install has validated any of the above —
  see the warning at the top of this document.
- The OSS-to-Enterprise migration path for an MKE-managed (non-operator)
  Calico install is unconfirmed; Tigera's documented upgrade path assumes
  an operator-installed OSS baseline that MKE3 does not use.
- The Kubernetes version compatibility matrix for MKE 3.9.x against a
  current Calico Enterprise release has not been checked.
- `nfnetlink_queue`/`nfnetlink_log` are not yet in a released
  `bootc-mirantis` image — [bootc-mirantis#210](https://github.com/Mirantis/bootc-mirantis/pull/210)
  is open, not merged, as of this writing.
