# bootc-mke3

`bootc-mke3` is an integrated container orchestration platform that is powered by an immutable Rocky Linux operating system, offering next-level security and reliability.

This repository contains a collection of tool, utilities and guides for managing and operating with `bootc-mke3`. These tools support operations, automation, and configuration for secure and scalable container environments.

## Provisioning

Provisioning is the process of preparing a cluster of `bootc-mke3` compute nodes within a network environment that meets the requirements for deploying and operating Mirantis products.

For further details, please see [provisioning document](docs/provisioning.md).

### Assets

Mirantis provides assets for provisioning `bootc-mke3` on different providers. Assets consist of bootable images that can be used to provision virtual machine or baremetale machine.

| Type  | Download link | Description | Mirantis product's version |
| :---- | ------------- | ----------- | -------------------------- |
| ISO   | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9-bare-mcr25.0-mke3.8-simple.iso)      | **Simple** ISO with basic kickstart embedded. Unattended Anaconda installation will be performed. See [this document](docs/iso-editions.md#simple) to get more details about Simple image edition. | MCR 25.0.14.2 / MKE 3.8.10 |
| ISO   | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9-bare-mcr25.0-mke3.8-generic.iso)      | **Generic** ISO without any customisation. See [this document](docs/iso-editions.md#generic-image-customisation.md) to get the details on how to properly customise it | MCR 25.0.14.2 / MKE 3.8.10 |
| QCOW2 | [Link](https://get.mirantis.com/bootc-mke3/images/bootc-mke3-r9-cloud-mcr25.0-mke3.8.qcow2)      | Standard QEMU/KVM bootable image | MCR 25.0.14.2 / MKE 3.8.10 |

> [!NOTE]
> **Simple** ISO edition is used mostly for demo/test purposes. For production-grade clusters consider susing **Generic** ISO.

## Installation

Installation in this document refers to the process of deploying Mirantis Kubernetes Engine on top of already provisioned machines (VMs or baremetal). 

To perform installation, [Ansible](https://docs.ansible.com/) is used. There are number of tasks and the playbook that serves this purpose.

Prerequisites for the installation can be found in the [Provisioning](#provisioning) section of this document.

To perform the installation, please see [installation runbook](docs/runbooks/install-bootc-mke3.md).

## Upgrade

To perform an upgrade , please see [upgrade runbook](docs/runbooks/upgrade-bootc-mke3.md).

## Troubleshooting

If you encounter issues, file an issue, or talk to us on the #prod-eng or #mkex-internal channel on the Mirantis Slack server.
