# State: this root uses Terraform's default local backend (terraform.tfstate in
# this directory). State is gitignored and holds the vSphere password in plain
# text, so it must not be shared or committed. There is no locking or sharing
# across operators; add a `backend` block here before more than one person
# applies this root.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    vsphere = {
      source  = "hashicorp/vsphere"
      version = "~> 2.0"
    }
  }
}

provider "vsphere" {
  vsphere_server = var.vsphere_server
  user           = var.vsphere_user
  password       = var.vsphere_password

  # Verify the vSphere server certificate by default. Set
  # allow_unverified_ssl = true in terraform.tfvars only for servers with a
  # self-signed certificate.
  allow_unverified_ssl = var.allow_unverified_ssl
}
