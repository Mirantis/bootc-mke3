# Contributing to bootc-mke3

This repository is the **operator side** of `bootc-mke3`. It contains the
Ansible installer and upgrader, Terraform for vSphere and AWS, and the
installation, operations and troubleshooting guides under
[`docs/`](docs/). It does **not** build images. Image build, CI and release
are in [`bootc-mirantis`](https://github.com/Mirantis/bootc-mirantis).
Problems with install, upgrade, nodes and clusters belong here. Problems with
image build and pipelines belong in `bootc-mirantis`.

If you find a problem but do not plan to fix it, file an issue on this
repository or contact your Mirantis representative.

## Making a change

1. Branch from `main`. Name the branch with the Jira ticket and a short slug,
   for example `PRODENG-3950-modules-disabled-docs`. For changes with no
   ticket, use a descriptive slug (for example
   `docs-controller-proxy-and-python-notes`).
2. Commit in small steps that are easy to review. Start each subject with the
   ticket key in brackets and write it in the imperative: `[PRODENG-3950] Fix a
   stale anchor into the ClusterUpgrade runbook`. For work with no ticket, use
   a type prefix such as `docs:`, `ansible:` or `feat:`.
3. Open a pull request against `main`. Describe what changed and how you
   verified it. Request a review from the owners in
   [CODEOWNERS](CODEOWNERS).
4. Make sure that the lint checks pass (see below) before you ask for a
   review.

## Repository layout

| Path | Contents |
| :--- | :------- |
| `ansible/` | Playbooks, task files and vars for MCR/MKE install, upgrade, backup, custom CA, controllers |
| `terraform/` | `vsphere/` and `aws/` provisioning |
| `docs/installation-guide/`, `docs/operations-guide/` | Runbooks and guides (entry points: `docs/installation-guide.md`, `docs/operations-guide.md`) |
| `docs/examples/` | Example inventories, configs and cluster-support manifests referenced from the docs |

## Lint

Three checks run on pull requests. Each check has its configuration at the
repository root:

| Check | Workflow | Config | Blocking |
| :---- | :------- | :----- | :------- |
| yamllint | [`lint.yml`](.github/workflows/lint.yml) | [`.yamllint`](.yamllint) | Errors fail. Warnings are advisory |
| ShellCheck | [`lint.yml`](.github/workflows/lint.yml) | [`.shellcheckrc`](.shellcheckrc) | Errors and warnings fail. Info and style are advisory |
| ansible-lint | [`ansible-lint.yml`](.github/workflows/ansible-lint.yml) | [`.ansible-lint`](.ansible-lint) | Advisory only, until we work down the known backlog |

Run the checks locally before you push. Install
[yamllint](https://yamllint.readthedocs.io/),
[ShellCheck](https://www.shellcheck.net/) and
[ansible-lint](https://ansible.readthedocs.io/projects/lint/) first:

```sh
yamllint .
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning
ansible-lint ansible/
```

The repository currently has no shell scripts. The ShellCheck job reports
this and passes. It starts to enforce rules when you add a shell script (a
`*.sh` file, or a file with a shell shebang).

yamllint does not check the Terraform `templatefile()` inputs under
`terraform/vsphere/helpers/cloudinit/` and the `*.cloud-init.yaml` files.
They have template directives or a mandatory `#cloud-config` first line. The
reasons are in the `ignore:` block of `.yamllint`. It is better to fix a
finding than to suppress it. If you must suppress a finding, use an inline
`# yamllint disable-line rule:xxxx` or `# shellcheck disable=SCxxxx` with a
one-line reason.

## Secrets

Never commit client bundles, registry credentials, private keys, Terraform
state or `*.tfvars`. [`.gitignore`](.gitignore) blocks `ansible/mke-bundle/`
(TLS keys), `ansible/vars/reg-creds`, `*.tfstate*` and `*.tfvars*`. This is a
safety net. It does not replace keeping those files outside the working
tree. Examples in `docs/` and `*.example` files must use placeholders only. If
you commit a secret, treat it as compromised and rotate it. It is not enough
to remove it from the history.

## Documentation

Update the docs in the same pull request as the behavior that they describe.
Keep them the same as the Ansible and Terraform code. If the docs and the code
disagree, the code is authoritative, so fix the docs. Make sure that the
relative links and anchors that you change still work. The pinned product
versions in the README asset table follow the releases that `bootc-mirantis`
publishes.

## License

See [LICENSE](LICENSE). Ask a maintainer before you add third-party code or
files under a different license.
