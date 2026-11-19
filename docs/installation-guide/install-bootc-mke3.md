# Install bootc-mke3

Deploy an MKE cluster on the provisioned infrastructure with the Ansible installer.

## Requirements

1. Ansible is installed on the machine from which you run the installation.
Ansible's control node cannot run natively on Windows. If your workstation is Windows, run `ansible-playbook` from WSL (Windows Subsystem for Linux).
2. The ansible installer needs an ansible inventory for a cluster of machines. The machines must meet the minimum requirements for the Mirantis Containers components.
3. `kubectl` is installed on the Ansible controller. The post-install play
   (`mke-post-install-playbook.yml`, chained at the end of
   `mke-install-playbook.yml`) runs entirely with `hosts: localhost` against
   the fetched MKE client-bundle kubeconfig. The SUC manifests,
   `cluster-upgrade-controller`, and `machine-config-controller` are all
   static Kubernetes manifests. A local `kubectl` applies them
   (`ansible/tasks/cluster-upgrade-controller-tasks.yml`,
   `ansible/tasks/machine-config-controller-tasks.yml`). `helm` is not necessary.
4. `python3` 3.6 or newer is in the `PATH` of the Ansible controller. The post-install
   play runs `ansible/tasks/helpers/suc_priv_grant.py` with a bare `python3`
   (`ansible/tasks/suc-priv-grant-tasks.yml`), and the script uses f-strings.
   This is the `python3` that the Ansible user resolves. It can be different from the
   interpreter that Ansible itself runs under (`ansible --version`).

### bootc-mke3 component configuration

There are no default MKE admin credentials. `admin_user` and `admin_pass` are not defined in `ansible/vars/mke-creds.yml` on purpose. You must supply them before you install. The first play of `mke-install-playbook.yml` ("Validate MKE admin credentials") asserts that `admin_user` is defined and not empty. It also asserts that `admin_pass` is defined and has at least 8 characters. If an assertion fails, the run fails before the playbook changes any host. Both values can contain spaces, quotes and shell metacharacters. They are shell-quoted when they are passed to `mke install`.

Set them in one of two ways. You can uncomment and edit the two lines in `ansible/vars/mke-creds.yml`. Or you can set them on the command line, which keeps the password out of the working tree:

```bash
ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml \
  -e admin_user=<username> -e admin_pass=<password-of-8-or-more-characters>
```

Do not commit real credentials. We recommend that you use `ansible-vault encrypt_string` for the password.

## Procedure

1. Make sure that the ansible inventory exists. For more details, see the [inventory description document](ansible-inventory-input.md).
2. Set `admin_user` and `admin_pass` (required, see above) in `vars/mke-creds.yml` or with `-e`. To change other default values, specify the values in `vars/common-vars.yml`.
3. Optional: Set the MCR and MKE licenses with the `mcr_license` and `mke_license` variables.
4. Run ansible from the `ansible/` directory. Then `ansible.cfg` is used. It sets
   `host_key_checking = false`, which is necessary for new hosts whose SSH host keys
   are not yet known:
   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml
   ```
   If you run `ansible-playbook` from outside `ansible/` (for example, from the repository
   root), it does not use `ansible.cfg`. It then fails with `Host key verification
   failed` on newly provisioned hosts.

## Expected Results

The Ansible playbook runs without error. To verify the installation, go to the MKE UI (`mke_url` in the ansible inventory file). Log in with the credentials specified in `vars/mke-creds.yml`.

## Post-install automation

A default run also deploys the System Upgrade Controller (SUC),
`cluster-upgrade-controller`, and `machine-config-controller` to the
cluster. See the [controllers runbook](install-controllers.md) for what
each controller does, where its version comes from, and how to verify it.

The same run also applies `disable_sshd_after_install` and
`revoke_sudo_after_install` (`vars/common-vars.yml`). Both are `true` by
default. The run stops and masks sshd. A disabled sshd is not sufficient:
on cloud images, `cloud-init.service` starts a disabled `sshd` again on every
boot with `Wants=sshd.service`. Only a mask stays in effect after a reboot.
The run also revokes the sudo access of the ansible user on every host. This
includes the wheel group, the sudo group, and any named
`/etc/sudoers.d/<user>` drop-in. This is done in the "Harden hosts after MKE
installation" play. That play runs *before* the post-install controller
installs (SUC, `cluster-upgrade-controller`, `machine-config-controller`) and
not after them, although this section lists them in a different order. A
default run of this runbook, with no changes, locks you out of SSH and sudo on
every cluster machine. No further action is necessary. If you need SSH or
sudo afterwards, set both variables to `false` in
`vars/common-vars.yml` before you install. Otherwise, use the
[cluster access runbook](../operations-guide/access-cluster.md) for the
access path with the client bundle, which this hardening assumes. If you are
already locked out, use the
[controllers runbook](install-controllers.md#break-glass-recovery-locked-out-of-ssh-and-sudo)
to recover.

## F.A.Q
### How can I install MKE with pre-configured settings/config?
`mke_config_src` must hold the **literal TOML content** of your MKE config,
not a file path. `ansible/tasks/mke-toml-config.yml` writes the value of the
variable directly as file content (`ansible.builtin.copy: content: "{{
mke_config_src }}"`). Set it with a `lookup`, for example `mke_config_src: "{{
lookup('file', '/usr/test/bootc-mke3-install/mke-config.toml') }}"` in your
vars file. If you assign a bare path string, Ansible writes that string into
`/etc/docker/mke-config.toml` and not your TOML. For the minimum version
of the TOML file, see [mke-config-min.toml.example](../examples/mke-config-min.toml.example). For the complete list of toml config options, see https://docs.mirantis.com/mke/3.9/ops/administer-cluster/configure-an-mke-cluster/configuration-options.html

### Post-install fails with `Status code was -1 ... Request failed: <urlopen error timed out>`
The "Authenticate to MKE and obtain a short-lived auth token" task
(`ansible/tasks/mke-client-bundle-tasks.yml`) runs from the Ansible
**controller** (`delegate_to: localhost`), not from a manager. The later MKE
API calls also run from the controller.
Status `-1` means that no HTTP response was received. If the controller is
behind a corporate proxy (`http_proxy`/`https_proxy` set in its environment),
the Ansible `uri` module sends these requests through the proxy. The proxy
usually cannot reach the MKE address, so the requests time out although the
install over SSH worked. `kubectl` uses the same variables.

Check with `env | grep -i proxy`. Then exclude the MKE address from the proxy
for the Ansible run. Use the exact `mke_url` value (hostname or IP) and the
manager hostnames. `no_proxy` entries do not support CIDR ranges here:
```bash
export no_proxy="$no_proxy,<mke_url>,<manager1>,<manager2>,<manager3>"
export NO_PROXY="$no_proxy"
cd ansible
ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml
```
To confirm the path without Ansible, use:
`curl -vk --noproxy '*' -m 10 https://<mke_url>/_ping`.

The login and download tasks use `no_log: true`. Thus the underlying
error is censored, unless you temporarily set `no_log` to `false` while
you debug. Set it back afterwards, because the task arguments contain the admin
password. To avoid a change to the playbook, repeat the call with `curl -v`
from the controller.

### Post-install fails with `SyntaxError: invalid syntax` in `suc_priv_grant.py`
The "Merge SUC privilege grant into MKE cluster config" task runs
`python3 ansible/tasks/helpers/suc_priv_grant.py` on the controller, and the
script uses f-strings (for example line 54, `_format_str_array`). A `python3` older than
3.6 reports a plain `SyntaxError: invalid syntax` on that line. The version
that matters is the one that the `PATH` of the Ansible user resolves for `python3`. It
can be different from the version that `ansible --version` or a different shell reports:
```bash
command -v python3
python3 -c 'import sys; print(sys.executable, sys.version)'
python3 -c "v='a'; print(f'\"{v}\"')"   # must print "a" with quotes
```
Put a Python 3.6+ interpreter first in `PATH` for the run, or point the task at
it explicitly. The post-install play is idempotent, so you can run it again after
the fix.
