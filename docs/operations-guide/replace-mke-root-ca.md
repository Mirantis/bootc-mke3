# Replace MKE root CA material

MKE deploys three internal certificate authorities — **Cluster Root CA**
(node-to-node/swarm), **etcd Root CA**, and **Client Root CA** (client
bundles and, by default, MKE API access) — each valid for 20 years and not
normally rotated. This runbook covers replacing one or more of them with
your own certificate and key via the `mke ca` CLI, automated by the
standalone `mke-custom-ca-playbook.yml`.

> This is unrelated to the MKE web-server/API TLS certificate. See
> [Use your own TLS certificate for MKE](../installation-guide/use-custom-tls-certificates.md)
> for that instead — it's an install-time-only setting, whereas this
> playbook can run any time after install.

## Prerequisites

1. A running `bootc-mke3` cluster with SSH and sudo access to the manager
   nodes. If install-time hardening already revoked sudo/disabled sshd (the
   default — see the [installation runbook](../installation-guide/install-bootc-mke3.md#post-install-automation)),
   restore access first or use the
   [break-glass recovery procedure](../installation-guide/install-controllers.md#break-glass-recovery-locked-out-of-ssh-and-sudo).
2. A certificate/key bundle in PEM format for each CA you're replacing. Per
   Mirantis's requirements, each must be a self-signed root certificate (no
   intermediates), with an unencrypted key, and the exact Common Name MKE
   expects:

   | CA | Variable prefix | Required Common Name |
   |---|---|---|
   | Cluster Root CA | `mke_custom_ca_cluster_*` | `swarm-ca` |
   | etcd Root CA | `mke_custom_ca_etcd_*` | `swarm-ca` |
   | Client Root CA | `mke_custom_ca_client_*` | `UCP Client Root CA` |

   > **This etcd CA row deliberately contradicts Mirantis's published
   > docs.** [Manage MKE certificate authorities](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/manage-certificate-authorities.html)
   > and the `ca` CLI reference both state the etcd CA's required CN is
   > `MKE etcd Root CA` — that's what MKE's own self-generated etcd CA
   > actually carries. But the `ca --etcd` command's validation of a
   > *replacement* cert checks for `swarm-ca` instead: a cert with CN
   > `MKE etcd Root CA` is rejected with `provided cert and key are invalid: root CA certificate has a
   > wrong common name: expected "swarm-ca", actual "MKE etcd Root CA"`; a
   > cert with CN `swarm-ca` is accepted and, after the reboot cycle, is
   > exactly what ends up on disk at
   > `/var/lib/docker/volumes/ucp-etcd-root-ca/_data/cert.pem`. Use
   > `swarm-ca`, not the documented value, until Mirantis fixes the docs
   > or the CLI. Re-verify against your own MKE patch version before
   > relying on this in case a future release corrects the check.

3. **A recent MKE backup.** Mirantis requires one to run the `ca` command at
   all (or the `--force-recent-backup` override); see Step 1 below.
4. Expect cluster downtime: replacing a CA restarts several MKE components
   and requires rebooting every manager node one at a time. Run outside peak
   hours.

## Procedure

1. Take a backup, unless you've deliberately decided to skip it (e.g. a
   brand-new cluster with no data yet):

   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-backup-playbook.yml
   ```

   If you skip this, set `mke_custom_ca_force_recent_backup: true` in step 2
   — otherwise the `ca` command refuses to run.

2. In `ansible/vars/mke-custom-ca-vars.yml` (or via `-e` on the command
   line), enable and point at the bundle for each CA you want to replace.
   Each is independent — enable one, two, or all three in a single run:

   | Variable | Purpose |
   |---|---|
   | `mke_custom_ca_cluster_enabled` / `_etcd_enabled` / `_client_enabled` | Toggle per CA type. Default `false`. |
   | `mke_custom_ca_{cluster,etcd,client}_cert_src` / `_key_src` | Path on the Ansible controller, or literal PEM content, for each CA's `cert.pem`/`key.pem`. |
   | `mke_custom_ca_force_recent_backup` | Passed as `--force-recent-backup`; only set `true` if you deliberately skipped step 1. |
   | `mke_custom_ca_reboot_after` | Default `true`. The new CA material has no effect until every manager reboots — set `false` only if you intend to reboot manually during a separate maintenance window. |

3. Run the playbook:

   ```bash
   ansible-playbook -i <path-to-your-inventory> mke-custom-ca-playbook.yml \
     -e mke_custom_ca_cluster_enabled=true \
     -e mke_custom_ca_cluster_cert_src=/path/to/cluster-ca-cert.pem \
     -e mke_custom_ca_cluster_key_src=/path/to/cluster-ca-key.pem
   ```

   The playbook, in order:
   1. Stages the supplied cert/key on the lead manager and runs
      `mke ca --cluster`/`--etcd`/`--client` for each enabled CA type
      (`tasks/mke-custom-ca-tasks.yml`), then removes the staged copy.
   2. Detects the current Swarm Raft leader among the managers
      (`docker node inspect --format '{{.ManagerStatus.Leader}}'`) rather
      than assuming it — leadership can drift from the node that ran the
      initial `swarm init`.
   3. Reboots every non-leader manager, one at a time, then reboots the
      leader last, per Mirantis's documented requirement — waiting for MKE
      to report healthy after each reboot before moving to the next node.

## Expected Results

- After the run completes, every manager reports healthy and rejoined:

  ```bash
  docker node ls --format "{{.ID}} {{.Hostname}} {{.Status}} {{.TLSStatus}}"
  ```

- Replacing the **Client Root CA** invalidates existing non-admin client
  bundles — affected users must download new ones (see
  [Access the cluster](access-cluster.md)).
- Replacing the **Cluster** or **etcd Root CA** does not by itself invalidate
  client bundles, but causes the restarts/reboots described above.
- For all three CA types, after the run the on-disk cert for each (`/var/lib/docker/swarm/certificates/swarm-root-ca.crt`
  for Cluster, `/var/lib/docker/volumes/ucp-etcd-root-ca/_data/cert.pem` for
  etcd, `/var/lib/docker/volumes/ucp-client-root-ca/_data/cert.pem` for
  Client) has the exact SHA-256 fingerprint of the supplied cert, `docker
  node ls` shows every manager `Ready`, and `kubectl get nodes` against a
  freshly downloaded client bundle succeeds.

## F.A.Q

### Can I replace more than one CA in a single run?

Yes — enable any combination of `mke_custom_ca_cluster_enabled`,
`_etcd_enabled`, and `_client_enabled` together. The playbook applies each
enabled one in sequence, then runs a single shared reboot pass at the end.

### Do I have to let it reboot the managers?

The new CA material does not take effect until every manager reboots. Set
`mke_custom_ca_reboot_after: false` only if you want to control exactly when
that reboot happens yourself; until you do reboot manually, MKE keeps
running on the old CA material.

### Can I skip the backup requirement?

Only by setting `mke_custom_ca_force_recent_backup: true`, which passes
`--force-recent-backup` straight through to the `ca` CLI. Use it only when
you've deliberately accepted the risk (e.g. a brand-new cluster with nothing
to restore).

### Is this the same as configuring MKE's web-server TLS certificate?

No — see [Use your own TLS certificate for MKE](../installation-guide/use-custom-tls-certificates.md)
for that. That setting only takes effect at install time and covers just the
browser/API-facing certificate; this playbook replaces MKE's internal CAs
and can run at any time after install.

## References

- [Manage MKE certificate authorities](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/manage-certificate-authorities.html)
- [`ca` CLI reference](https://docs.mirantis.com/mke/3.9/cli-ref/mke-cli-ca.html)
