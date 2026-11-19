# Provision `bootc-mke3` with Terraform on AWS

Use Terraform to provision machines on AWS.

> [!IMPORTANT]
> Mirantis considers AWS-based provisioning **dev/testing only**. It is not a production-grade `bootc-mke3` provisioning path. Mirantis maintains AWS AMIs for `bootc-mke3` builds for this purpose. The AMI IDs are not published in this document and are not publicly announced. Contact your Mirantis representative to get a current AMI ID and the AWS account that owns it.

## Requirements

### Prerequisites

Before you start this guide, make sure that you have these items:

1. Terraform >= 1.5 installed locally.
2. AWS credentials configured (`AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) for a user or role that can create VPCs, subnets, security groups, load balancers, key pairs, and EC2 instances.
3. A current `bootc-mke3` AMI ID and its owning AWS account, as described above.

### What gets provisioned

This procedure calls the [`terraform-mirantis-provision-aws` `mke3` example](https://registry.terraform.io/modules/terraform-mirantis-modules/provision-aws/mirantis/latest/examples/mke3) directly as a Terraform module from [`terraform/aws`](../../terraform/aws). The module provisions a VPC, subnets, security groups, an MKE load balancer, an SSH key pair, and EC2 instances. The module groups the instances by role (`manager`, `worker`, and optionally `msr`). The `bootc-mke3` AMI is not in the built-in platform library of the module. Therefore the `bootc-mke3` nodegroups set the AMI directly with `ami_id`/`ami_owner`, and they do not use the `platform` shortcut.

When `is_bootc_based = true` (the default in this folder), a small cloud-init payload configures the `cloud-user` of the image with passwordless sudo and docker-group access. It uses the generated SSH key. The `bootc-mke3` ansible playbooks expect this configuration for [machine connection](provisioning.md#machine-connection). This path does not use launchpad. MCR and MKE are already in the `bootc-mke3` AMI. The module satisfies its launchpad-oriented inputs and outputs internally with placeholders, and it does not expose them to `terraform.tfvars`.

> [!NOTE]
> Each `nodegroups.*` entry accepts a `user_data` field. The module
> **silently ignores it when `is_bootc_based = true`** (the default). The
> module always uses its own fixed cloud-init payload (the payload
> described above), regardless of any `user_data` value of a nodegroup.
> While `is_bootc_based` is `true`, you cannot use this module to
> inject custom cloud-init (for example, a no-touch join credential).
> Instead, provision such nodes directly outside this module (for example,
> with `aws ec2 run-instances --user-data ...`).

> [!WARNING]
> The default security group of the upstream module (name suffix `-permissive`) allows **all protocols and ports from `0.0.0.0/0`**, not only intra-VPC traffic. This is convenient for throwaway dev/test use. We recommend that you tighten it before you run anything longer-lived or exposed on this path.

### Variables

To configure the stack, make a copy of [terraform.tfvars.example](../../terraform/aws/terraform.tfvars.example) in the same `terraform/aws` folder and name it `terraform.tfvars`.

Set these values:

1. `name` — the label and prefix for all created resources.
2. `nodegroups.*.ami_id` and `nodegroups.*.ami_owner` — the `bootc-mke3` AMI ID and the owning AWS account (see prerequisites above).
3. `nodegroups.*.ssh_user` — `cloud-user` for `bootc-mke3` images.
4. `subnets` / `network` — change the CIDRs if the defaults conflict with existing AWS resources.

The full variable reference is in [`terraform/aws/README.md`](../../terraform/aws/README.md#inputs).

## Procedure

1. Run `cd terraform/aws`.
2. Run `cp terraform.tfvars.example terraform.tfvars` and edit the file as described above.
3. Prepare Terraform: `terraform init`
4. Run Terraform: `terraform apply`
5. To get the ansible inventory, run: `terraform output -raw bootc_ansible_output > inventory.yaml`
6. Continue with the [`bootc-mke3` install runbook](install-bootc-mke3.md). Use `inventory.yaml` as the ansible inventory.

## Expected Results

1. Terraform operations ended without error.
2. Terraform created the VPC, security groups, load balancer, and EC2 instances according to the Terraform configuration.
3. Terraform produced an ansible inventory for the management stage.
