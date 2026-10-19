# State: this root uses Terraform's default local backend (terraform.tfstate in
# this directory). State is gitignored and contains sensitive values (generated
# SSH private key, node details), so it must not be shared or committed. There
# is no locking or sharing across operators; add a `backend` block here before
# more than one person applies this root.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.56"
    }
  }
}
