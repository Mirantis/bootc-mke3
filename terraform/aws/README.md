# Provision `bootc-mke3` on AWS with Terraform

This root module calls the [`terraform-mirantis-provision-aws` `mke3` example](https://registry.terraform.io/modules/terraform-mirantis-modules/provision-aws/mirantis/latest/examples/mke3) directly as a module (pinned to `0.1.7`). It provisions EC2 nodes for `bootc-mke3` and produces an ansible inventory.

> [!IMPORTANT]
> AWS-based provisioning is for **development and testing only**. It is not a production-grade path. For this reason, Mirantis does not publish the `bootc-mke3` AMI in an automated way. Contact your Mirantis representative to get a current AMI ID and its owning AWS account. See also [docs/installation-guide/provisioning.md](../../docs/installation-guide/provisioning.md) and the [AWS provisioning runbook](../../docs/installation-guide/provision-terraform-aws.md).

## Prerequisites

- Terraform >= 1.5
- AWS credentials that you configure (`AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)
- A current `bootc-mke3` AMI ID (and owning AWS account). See the note above.

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars — set name, ami_id/ami_owner (see note above), node counts/types
terraform init
terraform apply
# retrieve the generated ansible inventory
terraform output -raw bootc_ansible_output > inventory.yaml
```

Then continue with the [`bootc-mke3` install runbook](../../docs/installation-guide/install-bootc-mke3.md). Use `inventory.yaml` as the ansible inventory.

## State

The state is local (default backend). Terraform writes `terraform.tfstate` to this directory. Git ignores this file, but it contains sensitive values (including the generated SSH private key material and node details). Keep it private and never commit it. There is no locking or sharing, so only one operator can apply this root module. To work with others, add a `backend` block in `versions.tf` and run `terraform init -migrate-state`.

## Structure

This folder is thin on purpose. `main.tf` calls the upstream `mke3` example as a module (`terraform-mirantis-modules/provision-aws/mirantis//examples/mke3`). `variables.tf` and `outputs.tf` mirror only the inputs and outputs that `bootc-mke3` needs. `main.tf` satisfies the launchpad-oriented `mke`/`mke_connect`/`launchpad_yaml` surface of the upstream example internally with placeholders, and does not expose it. To use a newer upstream release, change the `version` pin in `main.tf`. Then compare `variables.tf` and `outputs.tf` with `variables.tf` and `output.tf` of the upstream example.

## Inputs

| Variable | Description | Default |
|---|---|---|
| `name` | Stack/cluster name, used in all resource labels | — |
| `aws.region` | AWS region | `us-east-1` |
| `network` | VPC CIDR and gateway flags | `172.31.0.0/16`, no NAT/VPN |
| `subnets` | Subnet CIDR blocks mapped to node groups | `{}` |
| `nodegroups` | EC2 node group definitions: `ami_id`+`ami_owner` for bootc (you must set `ssh_user` with `ami_id`), `type`, `count`, `volume_size`, `role`, `public`. Each entry also accepts a `user_data` field, but Terraform ignores it without a message when `is_bootc_based = true`. See below | — |
| `is_bootc_based` | Inject the `cloud-user` cloud-init payload, which overrides any per-nodegroup `user_data` | `true` |
| `ssh_pk_location` | Directory to write the generated SSH private key. An empty value means the default location of the upstream module | `""` |
| `extra_tags` | Additional AWS tags applied to all resources | `{}` |

## Outputs

| Output | Description |
|---|---|
| `bootc_ansible_output` | Rendered ansible inventory YAML for the `bootc-mke3` playbooks (sensitive) |
| `nodes` | Provisioned node details per group (sensitive) |
| `ingresses` | Load-balancer DNS names |
| `platforms` | Resolved AMI data for any platform-based (non-bootc) nodegroups (sensitive) |
