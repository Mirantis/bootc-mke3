# Install bootc-mke3

Deploy MKE cluster on top of provisioned infrastructure using the Ansible installer.

## Requirements

1. Ansible installed on the machine from which installation will be executed.
Ansible's control node cannot run natively on Windows — if your workstation is Windows, run `ansible-playbook` from WSL (Windows Subsystem for Linux) instead.
2. The ansible installer requires an ansible inventory for a cluster of machines that meet the minimum requirements for the Mirantis Containers components.
3. `kubectl` installed on the Ansible controller. The post-install play
   (`mke-post-install-playbook.yml`, chained at the end of
   `mke-install-playbook.yml`) runs entirely via `hosts: localhost` against
   the fetched MKE client-bundle kubeconfig — SUC's manifests,
   `cluster-upgrade-controller`, and `machine-config-controller` are all
   static Kubernetes manifests applied with a local `kubectl`
   (`ansible/tasks/cluster-upgrade-controller-tasks.yml`,
   `ansible/tasks/machine-config-controller-tasks.yml`). No `helm` needed.

### bootc-mke3 component configuration

By default, admin user credentials for MKE UI are `admin/password`. If you want to configure admin user credentials for MKE, please change them in `ansible/vars/mke-creds.yml` file.

## Procedure

1. Ensure expected ansible inventory exists. See [inventory description document](ansible-inventory-input.md) for more details.
2. To override any default values, specify the desired values in the `vars/common-vars.yml` and `vars/mke-creds.yml` files
3. Optionally: You can set the MCR and MKE licenses via the `mcr_license` and `mke_license` variables respectively.
4. Run ansible from the `ansible/` directory, so `ansible.cfg` (which sets
   `host_key_checking = false`, required for fresh hosts whose SSH host keys
   aren't yet known) is picked up:
   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml
   ```
   Running `ansible-playbook` from outside `ansible/` (e.g. from the repo
   root) skips `ansible.cfg` and will fail with `Host key verification
   failed` against newly provisioned hosts.

## Expected Results

Ansible playbook runs without error. In order to verify the installation, go to the MKE UI (`mke_url` in ansible inventory file) and log in with the credentials specified in `vars/mke-creds.yml`

## Post-install automation

A default run also deploys the System Upgrade Controller (SUC),
`cluster-upgrade-controller`, and `machine-config-controller` to the
cluster — see the [controllers runbook](install-controllers.md) for what
each one does, where their versions come from, and how to verify them.

The same run additionally applies `disable_sshd_after_install` and
`revoke_sudo_after_install` (`vars/common-vars.yml`), both `true` by
default: sshd is stopped and masked (not merely disabled — on cloud images
`cloud-init.service` pulls a disabled `sshd` back in on every boot via
`Wants=sshd.service`, so only a mask survives reboots), and the ansible
user's sudo access (wheel group, sudo group, and any named
`/etc/sudoers.d/<user>` drop-in) is
revoked, on every host, in the "Harden hosts after MKE installation" play —
which runs *before* the post-install controller installs (SUC,
`cluster-upgrade-controller`, `machine-config-controller`), not after them,
despite this section's ordering. A vanilla, unmodified run of this runbook
therefore locks you out of SSH and sudo on every cluster machine with no
further action needed. Set both to `false` in
`vars/common-vars.yml` before installing if you need SSH/sudo afterwards;
otherwise, use the [cluster access runbook](../operations-guide/access-cluster.md) for the
client-bundle-based access path this hardening assumes, or the
[controllers runbook](install-controllers.md#break-glass-recovery-locked-out-of-ssh-and-sudo)
for how to recover if you're already locked out.

## F.A.Q
### How can I install MKE with pre-configured settings/config?
`mke_config_src` must hold the **literal TOML content** of your MKE config,
not a file path — `ansible/tasks/mke-toml-config.yml` writes the variable's
value directly as file content (`ansible.builtin.copy: content: "{{
mke_config_src }}"`). Set it via a `lookup`, e.g. `mke_config_src: "{{
lookup('file', '/usr/test/bootc-mke3-install/mke-config.toml') }}"` in your
vars file — assigning a bare path string writes that string into
`/etc/docker/mke-config.toml` instead of your TOML. For the minimum version
of the TOML file check [mke-config-min.toml.example](../examples/mke-config-min.toml.example). For complete list of toml config options check https://docs.mirantis.com/mke/3.9/ops/administer-cluster/configure-an-mke-cluster/configuration-options.html
