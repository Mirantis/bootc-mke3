# Use your own TLS certificate for MKE

By default, MKE serves its web UI and API (`https://<mke_url>`) with a
self-signed certificate. Browsers and API clients do not trust this
certificate. This runbook describes how to install MKE with your own
certificate instead. It uses
`ansible/tasks/mke-external-certs-tasks.yml` and the `--external-server-cert`
install flag.

> This procedure replaces only the **web-server/API-facing** certificate.
> The internal Cluster/etcd/Client root CAs of MKE (which issue
> node-to-node, etcd, and client-bundle certificates) are a separate
> mechanism. For those CAs, see
> [Replace MKE root CA material](../operations-guide/replace-mke-root-ca.md).

## Requirements

1. A cluster on which **`mke-install-playbook.yml` has not yet run**. This
   customization is possible only at install time. If you enable it after
   MKE is installed, it does not rotate a live certificate. See the F.A.Q below.
2. A certificate bundle in PEM format:
   - `ca.pem` — root CA public certificate.
   - `cert.pem` — server certificate plus any intermediate CA certificates.
     **It must already include Subject Alternative Names (SANs)** for
     `mke_url` (the ansible inventory var) and for any load balancer address
     that is used to reach MKE. MKE does not add SANs to a certificate that
     you supply. It rejects requests for host names that the certificate
     does not include.
   - `key.pem` — unencrypted server private key that matches `cert.pem`.
3. An Ansible inventory that is ready as described in the [installation runbook](../installation-guide/install-bootc-mke3.md).

## Procedure

1. In `ansible/vars/common-vars.yml`, set:

   | Variable | Value |
   |---|---|
   | `mke_external_certs_enabled` | `true` |
   | `mke_external_ca_src` | path to `ca.pem` on the Ansible controller, or the literal PEM content |
   | `mke_external_cert_src` | path to `cert.pem`, or the literal PEM content |
   | `mke_external_key_src` | path to `key.pem`, or the literal PEM content |

   Each `*_src` var accepts a file path on the Ansible controller or
   the literal PEM content. This is the same convention as `mke_config_src`.
   See the [install runbook's F.A.Q](install-bootc-mke3.md#faq). Ansible copies
   a single shared cert/key to each manager node. MKE automatically
   propagates it to managers that join or are promoted later.

2. Run the installer as usual:

   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-install-playbook.yml
   ```

   Before the MKE install runs, `tasks/mke-external-certs-tasks.yml` creates
   the `ucp-controller-server-certs` Docker volume on each manager and
   writes your `ca.pem`/`cert.pem`/`key.pem` into it. Then
   `tasks/mke-install-tasks.yml` appends `--external-server-cert` to the
   `mke install` command, so MKE uses the supplied bundle and does not
   generate its own.

## Expected Results

- `https://<mke_url>` presents your certificate chain and not the
  self-signed default of MKE:

  ```bash
  echo | openssl s_client -connect <mke_url>:443 -showcerts 2>/dev/null | openssl x509 -noout -issuer -subject
  ```

- Browsers and API clients that already trust your CA do not show a
  certificate warning when they access the MKE web UI.

## F.A.Q

### Can I rotate the certificate on an already-installed cluster?

Not through this playbook. The Mirantis MKE 3.9 documentation describes
only a live-rotation path through the MKE web UI (**\<user name\> →
Admin Settings → Certificates** → upload key/cert/CA → **Save**). It does
not describe a CLI or API equivalent. For a live rotation, use the web UI.
Or set `mke_external_certs_enabled` and reprovision for a fresh install.

### Can different managers use different certificates?

Not with this integration as implemented. `tasks/mke-external-certs-tasks.yml`
copies one shared bundle to each manager. MKE itself supports per-node
certificates that share a common SAN (see the upstream reference below).
To automate that, you would need per-host variables. This repo does not
do that at this time.

### Does this also replace MKE's internal CAs?

No. For the separate, standalone playbook that replaces the internal
Cluster/etcd/Client root CAs of MKE, see
[Replace MKE root CA material](../operations-guide/replace-mke-root-ca.md).

## References

- [Use an External Certificate Authority](https://docs.mirantis.com/mke/3.9/install/predeployment/use-ext-ca.html)
- [`install` CLI reference](https://docs.mirantis.com/mke/3.9/cli-ref/mke-cli-install.html)
- [Use your own TLS certificates (post-install/UI path)](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/use-your-own-tls-certificates.html)
- [Add SANs to cluster certificates](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/add-sans-to-cluster-certs.html)
