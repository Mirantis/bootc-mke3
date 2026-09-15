# bootc-mke3

`bootc-mke3` is an integrated container orchestration platform that is powered by an immutable Rocky Linux operating system, offering next-level security and reliability.

This repository contains a collection of tool, utilities and guides for managing and operating with `bootc-mke3`. These tools support operations, automation, and configuration for secure and scalable container environments.

## Table of Contents

- [Installation Guide](#installation-guide)
  - [Assets](#assets)
- [Operations Guide](#operations-guide)
- [Troubleshooting Guide](#troubleshooting-guide)

## Installation Guide

Installation covers everything from provisioning bare infrastructure to a running MKE cluster: registry and machine requirements, provisioning with Terraform (vSphere/AWS) or manually, running the Ansible installer, and the controllers deployed by default post-install. See the full guide at [Installation guide documentation pages](docs/installation-guide.md).

### Assets

Mirantis provides assets for provisioning `bootc-mke3` on different providers. Assets consist of bootable images that can be used to provision a virtual machine or bare-metal machine.

| Type  | Download link | Description | Mirantis product's version |
| :---- | ------------- | ----------- | -------------------------- |
| ISO   | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9.8-mcr29.6.1-mke3.9.5-bare-simple.iso)      | **Simple** ISO with basic kickstart embedded. Unattended Anaconda installation will be performed. See [this document](docs/installation-guide/iso-editions.md#simple) to get more details about Simple image edition. | MCR 29.6.1.1 / MKE 3.9.6 |
| ISO   | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9.8-mcr29.6.1-mke3.9.5-bare-generic.iso)      | **Generic** ISO without any customisation. See [this document](docs/installation-guide/iso-editions.md#generic-image-customisation) to get the details on how to properly customise it | MCR 29.6.1.1 / MKE 3.9.6 |
| QCOW2 | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9.8-mcr29.6.1-mke3.9.5-cloud.qcow2)      | Standard QEMU/KVM bootable image | MCR 29.6.1.1 / MKE 3.9.6 |

> [!NOTE]
> **Simple** ISO edition is used mostly for demo/test purposes. For production-grade clusters consider using **Generic** ISO.

## Operations Guide

Operations covers day-2 tasks on a running cluster: upgrading it (via the `ClusterUpgrade` CR or the Ansible exception path), adding machines with no-touch join, accessing it with the MKE client bundle, and securing it. See the full guide at [Operations guide documentation pages](docs/operations-guide.md).

## Troubleshooting Guide

If you encounter issues, please file an issue on this repository or contact your Mirantis representative.