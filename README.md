# bootc-mke3

`bootc-mke3` is an integrated container orchestration platform. It uses an immutable Rocky Linux operating system for security and reliability.

This repository contains tools, utilities and guides to manage and operate `bootc-mke3`. These tools support operations, automation, and configuration for secure and scalable container environments.

## Table of Contents

- [Installation Guide](#installation-guide)
  - [Releases](#releases)
- [Operations Guide](#operations-guide)
- [Troubleshooting Guide](#troubleshooting-guide)

## Installation Guide

Installation covers all tasks from provisioning bare infrastructure to a running MKE cluster. These tasks are: registry and machine requirements, provisioning with Terraform (vSphere/AWS) or manually, and running the Ansible installer. They also include the controllers that the installer deploys by default after installation. For the full guide, see [Installation guide documentation pages](docs/installation-guide.md).

### Releases

Mirantis publishes `bootc-mke3` assets on the [Releases page](https://github.com/Mirantis/bootc-mke3/releases). This repository does not list download links or versions. Each release notes the MCR and MKE versions that it contains. It also gives these items:

- The OCI image references (`registry.mirantis.com/bootc-mke3/...`), including the exact build tag.
- The download links for the bootable ISO and QCOW2 images.
- The versions of the preloaded controllers.
- The SBOM/CVE reports (see [Verify bootc-mke3 image signatures](docs/operations-guide/verify-image-signatures.md#sbom-and-cve-scan-reports-on-github-releases)).

Not every release covers every platform. Read the `Platforms` line of the release that you select.

> [!NOTE]
> The **Simple** ISO edition is mostly for demo and test purposes. For production-grade clusters, we recommend the **Generic** ISO. See [ISO editions](docs/installation-guide/iso-editions.md).

## Operations Guide

Operations covers day-2 tasks on a running cluster. These tasks are: upgrade the cluster (with the `ClusterUpgrade` CR or the Ansible exception path) and add machines with no-touch join. Other tasks are: access the cluster with the MKE client bundle, and secure the cluster. For the full guide, see [Operations guide documentation pages](docs/operations-guide.md).

## Troubleshooting Guide

If you have a problem, file an issue on this repository or contact your Mirantis representative.