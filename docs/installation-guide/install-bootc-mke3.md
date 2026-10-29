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
4. `python3` 3.6 or newer on the Ansible controller's `PATH`. The post-install
   play runs `ansible/tasks/helpers/suc_priv_grant.py` with a bare `python3`
   (`ansible/tasks/suc-priv-grant-tasks.yml`), and the script uses f-strings.
   This is the `python3` the Ansible user resolves, which can differ from the
   interpreter Ansible itself runs under (`ansible --version`).

### bootc-mke3 component configuration

There are no default MKE admin credentials. `admin_user` and `admin_pass` are intentionally left undefined in `ansible/vars/mke-creds.yml`, and you must supply them before installing. The first play of `mke-install-playbook.yml` ("Validate MKE admin credentials") asserts that `admin_user` is defined and non-empty and that `admin_pass` is defined and at least 8 characters long. If it is not, the run fails before any host is modified. Both values may contain spaces, quotes and shell metacharacters; they are shell-quoted when passed to `mke install`.

Set them either by uncommenting and editing the two lines in `ansible/vars/mke-creds.yml`, or on the command line (keeps the password out of the working tree):

```bash
ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml \
  -e admin_user=<username> -e admin_pass=<password-of-8-or-more-characters>
```

Do not commit real credentials; consider `ansible-vault encrypt_string` for the password.

## Procedure

1. Ensure expected ansible inventory exists. See [inventory description document](ansible-inventory-input.md) for more details.
2. Set `admin_user` and `admin_pass` (required, see above) in `vars/mke-creds.yml` or via `-e`. To override any other default values, specify the desired values in `vars/common-vars.yml`
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

### Post-install fails with `Status code was -1 ... Request failed: <urlopen error timed out>`
The "Authenticate to MKE and obtain a short-lived auth token" task
(`ansible/tasks/mke-client-bundle-tasks.yml`) and the later MKE API calls run
from the Ansible **controller** (`delegate_to: localhost`), not from a manager.
Status `-1` means no HTTP response was received at all. If the controller sits
behind a corporate proxy (`http_proxy`/`https_proxy` set in its environment),
Ansible's `uri` module sends these requests through the proxy, which usually
cannot reach the MKE address, so they time out even though the install over
SSH worked. `kubectl` honours the same variables.

Check with `env | grep -i proxy`, then exclude the MKE address from proxying
for the Ansible run. Use the exact `mke_url` value (hostname or IP) and the
manager hostnames; `no_proxy` entries do not support CIDR ranges here:
```bash
export no_proxy="$no_proxy,<mke_url>,<manager1>,<manager2>,<manager3>"
export NO_PROXY="$no_proxy"
cd ansible
ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml
```
To confirm the path independently of Ansible:
`curl -vk --noproxy '*' -m 10 https://<mke_url>/_ping`.

Note that the login and download tasks use `no_log: true`, so the underlying
error is censored unless `no_log` is temporarily set to `false` while
debugging (revert it afterwards: the task arguments contain the admin
password). Reproducing the call with `curl -v` from the controller avoids
editing the playbook.

### Post-install fails with `SyntaxError: invalid syntax` in `suc_priv_grant.py`
The "Merge SUC privilege grant into MKE cluster config" task runs
`python3 ansible/tasks/helpers/suc_priv_grant.py` on the controller, and the
script uses f-strings (e.g. line 54, `_format_str_array`). A `python3` older than
3.6 reports a plain `SyntaxError: invalid syntax` on that line. The version
that matters is the one the Ansible user's `PATH` resolves for `python3`, not
necessarily the one reported by `ansible --version` or by a different shell:
```bash
command -v python3
python3 -c 'import sys; print(sys.executable, sys.version)'
python3 -c "v='a'; print(f'\"{v}\"')"   # must print "a" with quotes
```
Put a Python 3.6+ interpreter first in `PATH` for the run, or point the task at
it explicitly. The post-install play is idempotent, so it can be re-run after
the fix.
