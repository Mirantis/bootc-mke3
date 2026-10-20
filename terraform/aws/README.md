# Provision `bootc-mke3` on AWS with Terraform

Calls the [`terraform-mirantis-provision-aws` `mke3` example](https://registry.terraform.io/modules/terraform-mirantis-modules/provision-aws/mirantis/latest/examples/mke3) directly as a module (pinned to `0.1.7`) to provision EC2 nodes for `bootc-mke3` and produce an ansible inventory.

> [!IMPORTANT]
> AWS-based provisioning is considered **dev/testing only**, not a production-grade path. Because of that, the `bootc-mke3` AMI is not published anywhere automated. Contact your Mirantis representative to obtain a current AMI ID and its owning AWS account. See also [docs/installation-guide/provisioning.md](../../docs/installation-guide/provisioning.md) and the [AWS provisioning runbook](../../docs/installation-guide/provision-terraform-aws.md).

## Prerequisites

- Terraform >= 1.5
- AWS credentials configured (`AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)
- A current `bootc-mke3` AMI ID (and owning AWS account) — see the note above

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars — set name, ami_id/ami_owner (see note above), node counts/types
terraform init
terraform apply
# retrieve the generated ansible inventory
terraform output -raw bootc_ansible_output > inventory.yaml
```

Then continue with the [`bootc-mke3` install runbook](../../docs/installation-guide/install-bootc-mke3.md) using `inventory.yaml` as the ansible inventory.

## State

State is local (default backend): `terraform.tfstate` is written to this directory. It is gitignored but contains sensitive values (including the generated SSH private key material and node details), so keep it private and never commit it. There is no locking or sharing, so only one operator should apply this root; to collaborate, add a `backend` block in `versions.tf` and run `terraform init -migrate-state`.

## Structure

This folder is intentionally thin — `main.tf` calls the upstream `mke3` example as a module (`terraform-mirantis-modules/provision-aws/mirantis//examples/mke3`), and `variables.tf`/`outputs.tf` mirror only the inputs/outputs `bootc-mke3` actually needs (the upstream example's launchpad-oriented `mke`/`mke_connect`/`launchpad_yaml` surface is satisfied internally with placeholders in `main.tf` and not exposed). To pick up a newer upstream release, bump the `version` pin in `main.tf` and diff `variables.tf`/`outputs.tf` against the upstream example's `variables.tf`/`output.tf`.

## Inputs

| Variable | Description | Default |
|---|---|---|
| `name` | Stack/cluster name, used in all resource labels | — |
| `aws.region` | AWS region | `us-east-1` |
| `network` | VPC CIDR and gateway flags | `172.31.0.0/16`, no NAT/VPN |
| `subnets` | Subnet CIDR blocks mapped to node groups | `{}` |
| `nodegroups` | EC2 node group definitions: `ami_id`+`ami_owner` for bootc (with `ssh_user` required alongside `ami_id`), `type`, `count`, `volume_size`, `role`, `public`. Each entry also accepts a `user_data` field, but it is silently ignored whenever `is_bootc_based = true` — see below | — |
| `is_bootc_based` | Inject the `cloud-user` cloud-init payload, overriding any per-nodegroup `user_data` | `true` |
| `ssh_pk_location` | Directory to write the generated SSH private key; empty means the upstream module's default location | `""` |
| `extra_tags` | Additional AWS tags applied to all resources | `{}` |

## Outputs

| Output | Description |
|---|---|
| `bootc_ansible_output` | Rendered ansible inventory YAML for the `bootc-mke3` playbooks (sensitive) |
| `nodes` | Provisioned node details per group (sensitive) |
| `ingresses` | Load-balancer DNS names |
| `platforms` | Resolved AMI data for any platform-based (non-bootc) nodegroups (sensitive) |
