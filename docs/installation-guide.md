# Installation Guide

This guide covers the tasks that take you from bare infrastructure to a running `bootc-mke3` MKE 3 cluster. The tasks are: provision machines, select an image, and run the Ansible installer.

## Provisioning

- [Provisioning overview](installation-guide/provisioning.md): registry setup, machine requirements, and the available provisioning approaches.
- [ISO editions](installation-guide/iso-editions.md): the Simple and Generic images, and how to customize the Generic image with kickstart.
- [Image architecture](installation-guide/image-architecture.md): what the image contains (kernel-module allowlist and lockdown, NetworkManager configuration, baked services) and the supported customisation points.
- [Ansible inventory input](installation-guide/ansible-inventory-input.md): the inventory file structure that the installer and upgrader use.
- [Provision with Terraform on vSphere](installation-guide/provision-terraform-vsphere.md)
- [Provision with Terraform on AWS](installation-guide/provision-terraform-aws.md): for development and testing only, not production-grade.
- [Provision manually](installation-guide/provision-manually.md): provisioning without the Mirantis Terraform tooling.

## Installing bootc-mke3

- [Install bootc-mke3](installation-guide/install-bootc-mke3.md): run the Ansible installer against a provisioned inventory.
- [Use your own TLS certificate for MKE](installation-guide/use-custom-tls-certificates.md): install MKE with a custom web-server/API certificate instead of the default self-signed certificate.
- [Post-install controllers](installation-guide/install-controllers.md): what the System Upgrade Controller, `cluster-upgrade-controller`, and `machine-config-controller` deploy by default, and how to verify them.
- [Air-gapped bootc-mke3](installation-guide/airgap-bootc-mke3.md): what you must mirror to an internal registry and which Ansible variables to change.

After you install a cluster, see the [Operations Guide](operations-guide.md) for day-2 tasks (upgrades, adding machines, cluster access, hardening).
