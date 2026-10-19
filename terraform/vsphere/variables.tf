variable "vsphere_server" {
  description = "URL of vSphere server"
}

variable "vsphere_user" {
  description = "Username for connecting to vSphere"
}

variable "vsphere_password" {
  description = "Password for vSphere connection"
}

variable "allow_unverified_ssl" {
  description = "Skip TLS certificate verification of the vSphere server. Set to true only for servers with a self-signed certificate."
  type        = bool
  default     = false
}

variable "datacenter" {
  default = ""
}

variable "resource_pool" {
}

variable "folder" {
  default = ""
}

variable "datastore" {
  default = null
}

variable "datastore_cluster" {
  default = null
}

variable "network" {
}

variable "network_type" {
  description = "Type of the network. Either 'IPAM' or 'DHCP'"
}

variable "manager_vm_template" {
  description = "VM to use as a template for managers"
}

variable "worker_vm_template" {
  description = "VM to use as a template for workers"
}

variable "ssh_private_key_file" {
  description = "Private key for SSH connections to created virtual machines"
}
variable "ssh_public_key_file" {
  description = "Public key for SSH connections to created virtual machines"
}

variable "quantity_managers" {
  description = "Number of MKEx manager VMs to create"
  default     = 3
}

variable "quantity_workers" {
  description = "Number of MKEx worker VMs to create"
  default     = 3
}

variable "cpu_count_managers" {
  description = "Number of CPUs in managers VMs"
  default     = 2
}

variable "memory_count_managers" {
  description = "Amount of memory in managers VMs"
  default     = 16384
}

variable "cpu_count_workers" {
  description = "Number of CPUs in workers VMs"
  default     = 4
}

variable "memory_count_workers" {
  description = "Amount of memory in workers VMs"
  default     = 16384
}

variable "ip_range_managers" {
  description = "IP addresses to be assigned to managers VMs"
  type        = string
  default     = "192.168.1.10-192.168.1.20"
}

variable "ip_range_workers" {
  description = "IP addresses to be assigned to worker VMs"
  type        = string
  default     = "192.168.1.30-192.168.1.40"
}

variable "network_gateway" {
  description = "Gateway IP address to be used as default gateway for VMs"
  type        = string
  default     = "192.168.1.1"
}

variable "nameserver" {
  description = "DNS to be added to the VM network configuration"
  type        = string
  default     = "8.8.8.8"
}

variable "cluster_name" {
  description = "Name of the cluster (will be used as prefix for cluster nodes)"
  default     = "mke-cluster"
}

variable "docker_hub_username" {
  description = "Docker Hub username to add docker hub auth to k0s cluster"
  default     = "user"
}

variable "docker_hub_pass" {
  description = "Docker Hub password to add docker hub auth to k0s cluster"
  default     = "password"
}

variable "manager_disk_size" {
  description = "Manager disk size in GBs"
  default     = 40
}

variable "worker_disk_size" {
  description = "Worker disk size in GBs"
  default     = 60
}

variable "vm_user" {
  description = "Username that will be used to login to the VM"
}

variable "firmware" {
  description = "Firmware to be used for the VM. Possible options are 'bios' and 'efi'"
}
