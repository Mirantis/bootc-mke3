# bootc-mke3

`bootc-mke3` is an integrated container orchestration platform that is powered by an immutable Rocky Linux operating system, offering next-level security and reliability.

This repository contains a collection of tool, utilities and guides for managing and operating with `bootc-mke3`. These tools support operations, automation, and configuration for secure and scalable container environments.

## Table of Contents

- [Installation Guide](#installation-guide)
  - [Releases](#releases)
- [Operations Guide](#operations-guide)
- [Troubleshooting Guide](#troubleshooting-guide)

## Installation Guide

Installation covers everything from provisioning bare infrastructure to a running MKE cluster: registry and machine requirements, provisioning with Terraform (vSphere/AWS) or manually, running the Ansible installer, and the controllers deployed by default post-install. See the full guide at [Installation guide documentation pages](docs/installation-guide.md).

### Releases

Mirantis publishes `bootc-mke3` assets on the [Releases page](https://github.com/Mirantis/bootc-mke3/releases). That is the place to find them; this repository does not list download links or versions. Each release notes the MCR and MKE versions it contains, the OCI image references (`registry.mirantis.com/bootc-mke3/...`, including the exact build tag), download links for the bootable ISO and QCOW2 images, the versions of the preloaded controllers, and the SBOM/CVE reports (see [Verify bootc-mke3 image signatures](docs/operations-guide/verify-image-signatures.md#sbom-and-cve-scan-reports-on-github-releases)). Not every release covers every platform; check the `Platforms` line of the release you pick.

> [!NOTE]
> **Simple** ISO edition is used mostly for demo/test purposes. For production-grade clusters consider using **Generic** ISO. See [ISO editions](docs/installation-guide/iso-editions.md).

## Operations Guide

Operations covers day-2 tasks on a running cluster: upgrading it (via the `ClusterUpgrade` CR or the Ansible exception path), adding machines with no-touch join, accessing it with the MKE client bundle, and securing it. See the full guide at [Operations guide documentation pages](docs/operations-guide.md).

## Troubleshooting Guide

If you encounter issues, please file an issue on this repository or contact your Mirantis representative.