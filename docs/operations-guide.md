# Operations Guide

Day-2 operations for a running `bootc-mke3` MKE 3 cluster: accessing it, growing it, upgrading it, and securing it.

## Access an MKE cluster

- [Access the cluster (kubectl and Docker Swarm)](operations-guide/access-cluster.md) — the MKE client bundle path; no SSH required.

## Administer an MKE cluster

- [No-touch cluster join](operations-guide/no-touch-join.md) — how the built-in first-boot join mechanism works.
- [Join machines with no-touch join](operations-guide/join-machines-no-touch.md) — step-by-step procedure for adding worker machines.
- [Promote and demote machines](operations-guide/promote-demote-machine.md) — change a machine between manager and worker; quorum rules.
- [Expel a machine from the cluster](operations-guide/expel-machine.md) — cordon at both layers, drain, and remove a machine; forced expel of an unreachable one.
- [Machine configuration changes](operations-guide/machine-config-operations.md) — DNS/NTP/kernel/reboot changes cluster-wide via `machine-config-controller`.
- [bootc-mke3 mixed clusters](operations-guide/mixed-cluster.md) — migrating from a classic MCR/MKE3 cluster to bootc-mke3.

## Upgrades and migrations

- [Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)](operations-guide/upgrade-with-controller.md) — the canonical, controller-driven upgrade path.
- [Upgrade bootc-mke3 via Ansible](operations-guide/upgrade-with-ansible.md) — manual exception path for when the controller is unavailable or disabled.
- [Roll back a bootc-mke3 upgrade](operations-guide/rollback-bootc-mke3.md) — revert a failed `ClusterUpgrade`'s OS+MCR+MKE changes via `spec.rollback.requested`.

## Security

- [Security Analysis: Cluster Management Controllers](operations-guide/controller-security-analysis.md) — trust model and risk register for `cluster-upgrade-controller` and `machine-config-controller`.
- [Verify bootc-mke3 image signatures](operations-guide/verify-image-signatures.md) — `cosign verify` at mirroring, pull, and install/switch time; which controllers are signed; how to read the SBOM/CVE reports attached to releases.
- [Harden MKE3 / Kubernetes](operations-guide/harden-mke3-kubernetes.md) — concrete steps to configure a secure baseline.
- [Replace MKE root CA material](operations-guide/replace-mke-root-ca.md) — bring your own Cluster/etcd/Client root CA, any time after install.

## Troubleshooting and support

- [Run privileged support containers on MKE](operations-guide/privileged-support-containers.md) — the one-time MKE grant that lets support pods run privileged on nodes; prerequisite for both runbooks below.
- [Open a debug shell on a node](operations-guide/node-debug-shell.md) — root shell on any node via `kubectl`, with host filesystem and namespace access; no SSH.
- [Collect support bundles from nodes](operations-guide/collect-support-bundles.md) — bulk diagnostic capture across nodes (journal, MCR, MKE 3, `bootc`, host state) to a node directory, PVC, or S3.
