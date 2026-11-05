# Upgrade bootc-mke3 via Ansible

This guide explains how to upgrade an existing Mirantis Kubernetes Engine (MKE) cluster to the latest version or switch to a specific newer release, by running an Ansible playbook from an operator's workstation.

> **This is a manual, Ansible-driven exception path.** It requires SSH and
> sudo access to every cluster machine from the machine running the
> playbook. The canonical way to upgrade a `bootc-mke3` cluster is the
> kube-native `ClusterUpgrade` custom resource, handled by
> `cluster-upgrade-controller` (installed by default) — see
> [upgrade via the ClusterUpgrade CR](upgrade-with-controller.md), which
> needs no SSH. Use this Ansible playbook only when the controller is
> unavailable or disabled on the cluster, or when you specifically need
> workstation-driven orchestration outside Kubernetes. Both paths run the
> identical underlying `mirantis/ucp upgrade` checks and commands.

## Prerequisites

1. Ansible installed on the machine running the upgrade.
2. An Ansible inventory describing the cluster. See the [inventory description document](../installation-guide/ansible-inventory-input.md) for details.
3. Cluster machines should have RO access to a OCI registry with new `bootc-mke3` version. See [this document](../installation-guide/provisioning.md#registry) for more information about registry requirement.

## Procedure

Before starting upgrade procedure, you can specify custom values for upgrade operation (if needed). To do so, add values in:
 - `vars/common-vars.yml`
 - `vars/upgrade-vars.yml`
 - `vars/mke-creds.yml`

Additionally, you can perform MCR/OS upgrade in one of the two ways: 

1. **Switch to a specific image and/or tag.** To do so, update `bootc_image_ref` in `vars/upgrade-vars.yml` with the full OCI image URL, including the image tag. If you're planning to use/switch to a private registry, please add corresponding credentials to machines, using [this ansible playbook](../../ansible/reg-creds-playbook.yml). Verify the target image's cosign signature before setting `bootc_image_ref` — see [Verify bootc-mke3 image signatures](verify-image-signatures.md#at-installswitch-time).
2. **Upgrade to the latest version of the current image tag.** To do so, leave `bootc_image_ref` unchanged or empty in `vars/upgrade-vars.yml`. **This is a no-op under the current tagging scheme**: every build gets a unique, never-reused tag, so nothing is ever pushed under a tag a node is already tracking — `bootc upgrade` will find nothing new. Use option 1 instead; this option is documented for completeness / older registries only.

Worker nodes are upgraded in batches of `upgrade_worker_batch_size` (default `3`, in `vars/upgrade-vars.yml`) — analogous to `workerConcurrency` on the [ClusterUpgrade CR path](upgrade-with-controller.md).

Once all the variables are set (if needed), perform next two steps:

1. Ensure the expected Ansible inventory file exists and is correct.

2. Run the upgrade from the `ansible/` directory, so `ansible.cfg` (which sets
   `host_key_checking = false`, required for fresh hosts whose SSH host keys
   aren't yet known) is picked up:
   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-upgrade-playbook.yml
   ```
   Running `ansible-playbook` from outside `ansible/` (e.g. from the repo
   root) skips `ansible.cfg` and will fail with `Host key verification
   failed` against newly provisioned hosts.

## Expected Results

Ansible playbook runs without error. In order to verify the upgrade, go to the MKE UI (`mke_url` in ansible inventory file) and log in with the credentials specified in `vars/mke-creds.yml` and make sure version is upgraded as expected.

## MKE upgrade process troubleshooting

MKE upgrade performed by ansible tooling which effectively just executing [MKE bootstrapper docker image with upgrade command](https://docs.mirantis.com/mke/3.9/cli-ref/mke-cli-upgrade.html). Additionally, before upgrade is performed, there are number of preupgrade checks and backups performed.

To troubleshoot MKE upgrade process, please see [official MKE documentation page](https://docs.mirantis.com/mke/3.9/ops/upgrades-and-migrations/upgrade-mke/troubleshoot-upgrade.html)

## MCR upgrade process troubleshooting

MCR upgrade is implemented using ansible tooling which applies new bootc deployments, containing new MCR versions (and other OS packages) in the form of an OCI image. In case of failure, you will be prompted with an error message that applying the new bootc deployment failed. If the upgrade failed on this stage, you need to manually inspect the node to check if:

1. There is no issue with network connectivity between node(s) and container registry, that contains new deployment in a form of OCI image
2. There is no issue with registry credentials (if private registry is used)

## Upgrade rollback

> [!NOTE]
> This section covers the **OS/MCR-only** manual rollback. It does not
> restore MKE. For the combined OS+MCR+MKE rollback via the canonical
> `ClusterUpgrade` CR path, see
> [Roll back a bootc-mke3 upgrade](rollback-bootc-mke3.md) instead.

In case of MCR upgrade failure, there is a way to perform a rollback to a previous deployment (= previous version of MCR and OS packages).

### Procedure

1. Ensure that node(s) are not running any critical workloads by draining the node (if it wasn't performed before).
2. SSH to the node and execute the command:
```
sudo bootc rollback
```
3. Once the operation has finished, reboot the machine.

### Expected results

The machine should have previous version of MCR and OS packages after reboot, without affecting the MKE version.
