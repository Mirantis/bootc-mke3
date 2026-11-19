# Operations Guide

Day-2 operations for a running `bootc-mke3` MKE 3 cluster: access the cluster, add machines, upgrade the cluster, and secure the cluster.

## Access an MKE cluster

- [Access the cluster (kubectl and Docker Swarm)](operations-guide/access-cluster.md): the MKE client bundle path. SSH is not necessary.

## Administer an MKE cluster

- [No-touch cluster join](operations-guide/no-touch-join.md): how the built-in first-boot join mechanism operates.
- [Join machines with no-touch join](operations-guide/join-machines-no-touch.md): the step-by-step procedure to add worker machines.
- [Promote and demote machines](operations-guide/promote-demote-machine.md): change a machine between manager and worker, and the quorum rules.
- [Expel a machine from the cluster](operations-guide/expel-machine.md): cordon at both layers, drain, and remove a machine. Also, the forced expel of an unreachable machine.
- [Machine configuration changes](operations-guide/machine-config-operations.md): change the DNS, NTP, kernel, and reboot settings of the whole cluster with `machine-config-controller`.
- [bootc-mke3 mixed clusters](operations-guide/mixed-cluster.md): migrate from a classic MCR/MKE3 cluster to bootc-mke3.

## Upgrades and migrations

- [Upgrade bootc-mke3 (via the `ClusterUpgrade` CR)](operations-guide/upgrade-with-controller.md): the canonical upgrade path, which the controller drives.
- [Upgrade bootc-mke3 via Ansible](operations-guide/upgrade-with-ansible.md): the manual exception path for when the controller is not available or is disabled.
- [Roll back a bootc-mke3 upgrade](operations-guide/rollback-bootc-mke3.md): revert the OS, MCR, and MKE changes of a failed `ClusterUpgrade` with `spec.rollback.requested`.

## Security

- [Security Analysis: Cluster Management Controllers](operations-guide/controller-security-analysis.md): the trust model and risk register for `cluster-upgrade-controller` and `machine-config-controller`.
- [Verify bootc-mke3 image signatures](operations-guide/verify-image-signatures.md): `cosign verify` at mirroring, pull, and install/switch time. Which controllers are signed. How to read the SBOM/CVE reports attached to releases.
- [Harden MKE3 / Kubernetes](operations-guide/harden-mke3-kubernetes.md): the steps to configure a secure baseline.
- [Replace MKE root CA material](operations-guide/replace-mke-root-ca.md): use your own Cluster, etcd, and Client root CA at any time after installation.

## Troubleshooting and support

- [Run privileged support containers on MKE](operations-guide/privileged-support-containers.md): the one-time MKE grant that lets support pods run privileged on nodes. It is a prerequisite for the two runbooks below.
- [Open a debug shell on a node](operations-guide/node-debug-shell.md): a root shell on any node through `kubectl`, with access to the host file system and namespaces. SSH is not necessary.
- [Collect support bundles from nodes](operations-guide/collect-support-bundles.md): collect diagnostic data from many nodes (journal, MCR, MKE 3, `bootc`, host state) to a node directory, a PVC, or S3.
