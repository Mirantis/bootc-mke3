# Installation Guide

This guide covers everything needed to go from bare infrastructure to a running `bootc-mke3` MKE 3 cluster: provisioning machines, choosing an image, and running the Ansible installer.

## Provisioning

- [Provisioning overview](installation-guide/provisioning.md) — registry setup, machine requirements, and the available provisioning approaches.
- [ISO editions](installation-guide/iso-editions.md) — Simple vs. Generic images and how to customize the Generic image via kickstart.
- [Image architecture](installation-guide/image-architecture.md) — what the image ships (kernel-module allowlist and lockdown, NetworkManager config, baked services) and the supported customisation points.
- [Ansible inventory input](installation-guide/ansible-inventory-input.md) — inventory file structure consumed by the installer/upgrader.
- [Provision with Terraform on vSphere](installation-guide/provision-terraform-vsphere.md)
- [Provision with Terraform on AWS](installation-guide/provision-terraform-aws.md) — dev/testing only, not production-grade.
- [Provision manually](installation-guide/provision-manually.md) — roll-your-own provisioning without the Mirantis Terraform tooling.

## Installing bootc-mke3

- [Install bootc-mke3](installation-guide/install-bootc-mke3.md) — run the Ansible installer against a provisioned inventory.
- [Use your own TLS certificate for MKE](installation-guide/use-custom-tls-certificates.md) — install MKE with a custom web-server/API certificate instead of the self-signed default.
- [Post-install controllers](installation-guide/install-controllers.md) — what the System Upgrade Controller, `cluster-upgrade-controller`, and `machine-config-controller` deploy by default, and how to verify them.
- [Air-gapped bootc-mke3](installation-guide/airgap-bootc-mke3.md) — what must be mirrored to an internal registry and the Ansible variables to repoint.

## Add-ons

- [Calico Enterprise](installation-guide/calico-enterprise.md) — provisioning-time kernel modules, pre-install checks, and the Tigera operator install steps for running Calico Enterprise on top of `bootc-mke3`.

See also the [Operations Guide](operations-guide.md) for day-2 tasks (upgrades, adding machines, cluster access, hardening) once a cluster is installed.
