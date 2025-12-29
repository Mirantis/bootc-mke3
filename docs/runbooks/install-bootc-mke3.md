# Install bootc-mke3

Deploy MKE cluster on top of provisioned infrastructure using the Ansible installer.

## Requirements

1. Ansible installed on the machine from which installation will be executed.
2. The ansible installer requires an ansible inventory for a cluster of machines that meet the minimum requirements for the Mirantis Containers components.

### bootc-mke3 component configuration

By default, admin user credentials for MKE UI are `admin/password`. If you want to configure admin user credentials for MKE, please change them in `ansible/vars/mke-creds.yml` file.

## Procedure

1. Ensure expected ansible inventory exists. See [inventory description document](../ansible-inventory-input.md) for more details.
2. To override any default values, specify the desired values in the `vars/common-vars.yml` and `vars/mke-creds.yml` files
3. Optionally: You can set the MCR and MKE licenses via the `mcr_license` and `mke_license` variables respectively.
4. Run ansible: `ansible-playbook -i <path-to-your-inventory> ansible/mke-install-playbook.yml`

## Expected Results

Ansible playbook runs without error. In order to verify the installation, go to the MKE UI (`mke_url` in ansible inventory file) and log in with the credentials specified in `vars/mke-creds.yml`

## F.A.Q
### How can I install MKE with pre-configured settings/config?
You'll need to set the `mke_config_src` to the path where your MKE toml file is. i.e. /usr/test/bootc-mke3-install/mke-config.toml. For the minimum version of the TOML file check [mke-config-min.toml.example](../examples/mke-config-min.toml.example). For complete list of toml config options check https://docs.mirantis.com/mke/3.8/ops/administer-cluster/configure-an-mke-cluster/configuration-options.html
