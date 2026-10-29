# Contributing to bootc-mke3

This repository is the **operator side** of `bootc-mke3`: the Ansible
installer and upgrader, Terraform for vSphere and AWS, and the installation,
operations and troubleshooting guides under [`docs/`](docs/). It does **not**
build images; image build, CI and release live in
[`bootc-mirantis`](https://github.com/Mirantis/bootc-mirantis). Install,
upgrade, node and cluster problems belong here; image-build and pipeline
problems belong there.

Found a problem but not planning to fix it? File an issue on this repository
or contact your Mirantis representative.

## Making a change

1. Branch from `main`. Name the branch after the Jira ticket plus a short slug,
   e.g. `PRODENG-3950-modules-disabled-docs`. Changes with no ticket use a
   descriptive slug (e.g. `docs-controller-proxy-and-python-notes`).
2. Commit in small, reviewable steps. Subjects start with the ticket key in
   brackets and are imperative: `[PRODENG-3950] Fix a stale anchor into the
   ClusterUpgrade runbook`. Ticketless work uses a type prefix such as `docs:`,
   `ansible:` or `feat:`.
3. Open a pull request against `main`, describe what changed and how you
   verified it, and request review from the owners in
   [CODEOWNERS](CODEOWNERS).
4. Make sure the lint checks pass (see below) before asking for review.

## Repository layout

| Path | Contents |
| :--- | :------- |
| `ansible/` | Playbooks, task files and vars for MCR/MKE install, upgrade, backup, custom CA, controllers |
| `terraform/` | `vsphere/` and `aws/` provisioning |
| `docs/installation-guide/`, `docs/operations-guide/` | Runbooks and guides (entry points: `docs/installation-guide.md`, `docs/operations-guide.md`) |
| `docs/examples/` | Example inventories, configs and cluster-support manifests referenced from the docs |

## Lint

Three checks run on pull requests, each configured at the repo root:

| Check | Workflow | Config | Blocking |
| :---- | :------- | :----- | :------- |
| yamllint | [`lint.yml`](.github/workflows/lint.yml) | [`.yamllint`](.yamllint) | Errors fail; warnings are advisory |
| ShellCheck | [`lint.yml`](.github/workflows/lint.yml) | [`.shellcheckrc`](.shellcheckrc) | Errors and warnings fail; info/style are advisory |
| ansible-lint | [`ansible-lint.yml`](.github/workflows/ansible-lint.yml) | [`.ansible-lint`](.ansible-lint) | Advisory only, until the known backlog is worked down |

Run them locally before pushing (install
[yamllint](https://yamllint.readthedocs.io/),
[ShellCheck](https://www.shellcheck.net/) and
[ansible-lint](https://ansible.readthedocs.io/projects/lint/)):

```sh
yamllint .
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning
ansible-lint ansible/
```

The repository currently has no shell scripts; the ShellCheck job reports that
and passes, and starts enforcing as soon as one (`*.sh`, or a file with a shell
shebang) is added.

Terraform `templatefile()` inputs under `terraform/vsphere/helpers/cloudinit/`
and `*.cloud-init.yaml` files are excluded from yamllint (they carry template
directives or a mandatory `#cloud-config` first line); the reasons are in the
`ignore:` block of `.yamllint`. Prefer fixing a finding over suppressing it; if
a suppression is genuinely needed, use an inline
`# yamllint disable-line rule:xxxx` or `# shellcheck disable=SCxxxx` with a
one-line reason.

## Secrets

Never commit client bundles, registry credentials, private keys, Terraform
state or `*.tfvars`. [`.gitignore`](.gitignore) blocks `ansible/mke-bundle/`
(TLS keys), `ansible/vars/reg-creds`, `*.tfstate*` and `*.tfvars*`, but it is
a safety net, not a substitute for keeping those files outside the working
tree. Examples in `docs/` and `*.example` files must use placeholders only. If
a secret is committed, treat it as compromised and rotate it; removing it from
history is not enough.

## Documentation

Update the docs in the same pull request as the behaviour they describe, and
keep them in step with the Ansible and Terraform code: where docs and code
disagree, the code is authoritative, so fix the docs. Check that relative links
and anchors you touch still resolve. Pinned product versions in the README
asset table follow the releases published from `bootc-mirantis`.

## License

See [LICENSE](LICENSE). Ask a maintainer before adding third-party code or
files under a different license.
