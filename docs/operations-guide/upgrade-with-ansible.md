# Upgrade bootc-mke3 via Ansible

This guide describes how to upgrade an existing Mirantis Kubernetes Engine (MKE) cluster to the latest version, or to a specific newer release. You run an Ansible playbook from the workstation of an operator.

> **This is a manual, Ansible-driven exception path.** It needs SSH and
> sudo access to every cluster machine from the machine that runs the
> playbook. The canonical way to upgrade a `bootc-mke3` cluster is the
> kube-native `ClusterUpgrade` custom resource, which
> `cluster-upgrade-controller` (installed by default) handles. See
> [upgrade via the ClusterUpgrade CR](upgrade-with-controller.md), which
> does not need SSH. Use this Ansible playbook only when the controller is
> unavailable or disabled on the cluster. You can also use it when you
> specifically need orchestration from a workstation outside Kubernetes. Both
> paths run the same underlying `mirantis/ucp upgrade` checks and commands.

## Prerequisites

1. Ansible installed on the machine that runs the upgrade.
2. An Ansible inventory that describes the cluster. For details, see the [inventory description document](../installation-guide/ansible-inventory-input.md).
3. We recommend that the cluster machines have RO (read-only) access to an OCI registry that has the new `bootc-mke3` version. For more information about the registry requirement, see [this document](../installation-guide/provisioning.md#registry).

## Procedure

Before you start the upgrade procedure, you can set custom values for the upgrade operation (if it is necessary). To do this, add values in:
 - `vars/common-vars.yml`
 - `vars/upgrade-vars.yml`
 - `vars/mke-creds.yml`

You can do the MCR/OS upgrade in one of two ways:

1. **Switch to a specific image and/or tag.** To do this, set `bootc_image_ref` in `vars/upgrade-vars.yml` to the full OCI image URL, including the image tag. If you plan to switch to a private registry, add the applicable credentials to the machines with [this ansible playbook](../../ansible/reg-creds-playbook.yml). Before you set `bootc_image_ref`, check the cosign signature of the target image. See [the runbook for bootc-mke3 image signatures](verify-image-signatures.md#at-installswitch-time).
2. **Upgrade to the latest version of the current image tag.** To do this, keep `bootc_image_ref` unchanged or empty in `vars/upgrade-vars.yml`. **This does nothing under the current tagging scheme.** Every build gets a unique tag that is never reused. Therefore the build process never pushes a new image under a tag that a node already tracks, and `bootc upgrade` finds nothing new. Use option 1 instead. This guide describes this option only for completeness and for older registries.

The playbook upgrades worker nodes in batches of `upgrade_worker_batch_size` (default `3`, in `vars/upgrade-vars.yml`). This is similar to `workerConcurrency` on the [ClusterUpgrade CR path](upgrade-with-controller.md).

When you set all the variables (if it is necessary), do these two steps:

1. Make sure that the expected Ansible inventory file exists and is correct.

2. Run the upgrade from the `ansible/` directory, so that Ansible uses
   `ansible.cfg`. This file sets `host_key_checking = false`, which is
   necessary for new hosts whose SSH host keys are not yet known:
   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-upgrade-playbook.yml
   ```
   If you run `ansible-playbook` from outside `ansible/` (for example, from the
   repository root), Ansible does not use `ansible.cfg`. The playbook then
   fails with `Host key verification failed` on newly provisioned hosts.

### Backups taken by the playbook

Before the playbook switches the managers to the new image, `mke-upgrade-playbook.yml` runs `mke-backup-playbook.yml` on every manager. It writes two root-only (`0600`) archives to `mke_backup_dir` (default `/var/lib/mke-ansible-backup`, set in `vars/common-vars.yml`):

- `mke-<MKE version>-backup-<timestamp>.tar`: the MKE backup.
- `swarm-<engine version>-backup-<timestamp>.tar.tgz`: the Swarm state from `/var/lib/docker/swarm/`.

The directory is on persistent storage, so the archives stay after the manager reboots in this procedure. The playbook never deletes them, and they stay on the disk of the manager until you delete them. They hold the MKE CA private keys. Delete them when you no longer need them. The directory is not `/var/lib/mke-backup`, which is the default `backupDir` of `cluster-upgrade-controller`. Therefore a restore by the controller never uses these archives.

## Expected Results

The Ansible playbook runs without error. To check the upgrade, open the MKE UI (`mke_url` in the Ansible inventory file). Log in with the credentials in `vars/mke-creds.yml`. Make sure that the MKE version is the version that you expect after the upgrade.

## MKE upgrade process troubleshooting

The Ansible tooling does the MKE upgrade. It runs the [MKE bootstrapper docker image with the upgrade command](https://docs.mirantis.com/mke/3.9/cli-ref/mke-cli-upgrade.html). Before the upgrade, the tooling also does a number of pre-upgrade checks and backups.

To troubleshoot the MKE upgrade process, see the [official MKE documentation page](https://docs.mirantis.com/mke/3.9/ops/upgrades-and-migrations/upgrade-mke/troubleshoot-upgrade.html).

## MCR upgrade process troubleshooting

The Ansible tooling does the MCR upgrade. It applies new bootc deployments that contain new MCR versions (and other OS packages) as an OCI image. If the upgrade fails, an error message shows that the new bootc deployment failed. If the upgrade failed at this stage, inspect the node manually to check these conditions:

1. There is no problem with the network connection between the nodes and the container registry that has the new deployment as an OCI image.
2. There is no problem with the registry credentials (if you use a private registry).

## Upgrade rollback

> [!NOTE]
> This section describes the **OS/MCR-only** manual rollback. It does not
> restore MKE. For the combined OS+MCR+MKE rollback with the canonical
> `ClusterUpgrade` CR path, see
> [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) instead.

If the MCR upgrade fails, you can roll back to a previous deployment (the previous version of MCR and OS packages).

### Procedure

1. Drain the node to make sure that it does not run critical workloads (if you did not do this before).
2. Connect to the node with SSH and run the command:
```
sudo bootc rollback
```
3. When the command is complete, reboot the machine.

### Expected results

After the reboot, we expect the machine to have the previous version of MCR and OS packages. The MKE version does not change.
