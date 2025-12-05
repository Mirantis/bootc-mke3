# Upgrade MKEx

This guide explains how to upgrade an existing Mirantis Kubernetes Engine (MKE) cluster to the latest version or switch to a specific newer release.

## Prerequisites

1. Ansible installed on the machine running the upgrade.
2. An Ansible inventory describing the cluster. See the [inventory description document](../ansible-inventory-input.md) for details.

## Procedure

Before starting upgrade procedure, you can specify custom values for upgrade operation (if needed). To do so, add values in:
 - `vars/common-vars.yml`
 - `vars/upgrade-vars.yml`
 - `vars/mke-creds.yml`

Additionally, you can perform MCR/OS upgrade in one of the two ways: 

1. Upgrade to the latest version of the current image tag. To do so, leave `bootc_image_ref` unchanged or empty in `upgrade-vars.yaml`.
2. Switch to a specific image and/or tag. To do so, update `bootc_image_ref` in `upgrade-vars.yaml` with the full OCI image URL, including the image tag.

Once all the variables are set (if needed), perform next two steps:

1. Ensure the expected Ansible inventory file exists and is correct.

2. Run the upgrade
   ```bash
   ansible-playbook -i <path-to-your-inventory> ansible/mke-upgrade-playbook.yml
   ```

## Expected Results

Ansible playbook runs without error. In order to verify the upgrade, go to the MKE UI (`mke_url` in ansible inventory file) and log in with the credentials specified in `vars/mke-creds.yml` and make sure version is upgraded as expected.

## MKE upgrade process troubleshooting

MKE upgrade performed by ansible tooling which effectively just executing [MKE bootstrapper docker image with upgrade command](https://docs.mirantis.com/mke/3.8/cli-ref/mke-cli-upgrade.html). Additionally, before upgrade is performed, there are number of preupgrade checks and backups performed. 

To troubleshoot MKE upgrade process, please see [official MKE documentation page](https://docs.mirantis.com/mke/3.8/ops/upgrades-and-migrations/upgrade-mke/troubleshoot-upgrade.html)

## MCR upgrade process troubleshooting

MCR upgrade is done by ansible tooling which is applying new bootc deployment that contains a new MCR version (and other OS packages) in a form of OCI image. In case of failure, you will be prompted with an error message that applying new bootc deployment failed. If upgrade failed on this stage, you need to manually inspect the node to check if:

1. There is no issue with network connectivity between node(s) and container registry, that contains new deployment in a form of OCI image
2. There is no issue with registry credentials (if private registry is used)

## Upgrade rollback

In case of MCR upgrade failure, there is a way to perform a rollback to a previous deployment (= previous version of MCR and OS packages).

### Procedure

1. Ensure that node(s) are not running any critical workloads by draining the node (if it wasn't performed before).
2. SSH to the node and execute the command:
```
sudo bootc rollback
```
3. Once the operation has finished, reboot the machine.

### Expected results

The machine should have previous version of MCR and OS packages after reboot.
