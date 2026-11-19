# Replace MKE root CA material

MKE deploys three internal certificate authorities: **Cluster Root CA**
(node-to-node/swarm), **etcd Root CA**, and **Client Root CA** (client
bundles and, by default, MKE API access). Each is valid for 20 years, and
normally you do not rotate them. This runbook describes how to replace one or
more of them with your own certificate and key. It uses the `mke ca` CLI,
automated by the standalone `mke-custom-ca-playbook.yml`.

> This runbook is not about the MKE web-server/API TLS certificate. For that
> certificate, see
> [Use your own TLS certificate for MKE](../installation-guide/use-custom-tls-certificates.md).
> You can set that certificate only at installation. You can run this playbook
> at any time after installation.

## Prerequisites

1. A running `bootc-mke3` cluster with SSH and sudo access to the manager
   nodes. If installation hardening already revoked sudo and disabled sshd,
   first restore access, or use the
   [break-glass recovery procedure](../installation-guide/install-controllers.md#break-glass-recovery-locked-out-of-ssh-and-sudo).
   Hardening does this by default (see the
   [installation runbook](../installation-guide/install-bootc-mke3.md#post-install-automation)).
2. A certificate/key bundle in PEM format for each CA that you replace.
   Mirantis requires that each certificate is a self-signed root certificate
   (no intermediates), with an unencrypted key and the exact Common Name that
   MKE expects:

   | CA | Variable prefix | Required Common Name |
   |---|---|---|
   | Cluster Root CA | `mke_custom_ca_cluster_*` | `swarm-ca` |
   | etcd Root CA | `mke_custom_ca_etcd_*` | `swarm-ca` |
   | Client Root CA | `mke_custom_ca_client_*` | `UCP Client Root CA` |

   > **The etcd CA row deliberately contradicts the published Mirantis
   > documentation.** [Manage MKE certificate authorities](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/manage-certificate-authorities.html)
   > and the `ca` CLI reference both state that the required CN of the etcd CA
   > is `MKE etcd Root CA`. The etcd CA that MKE generates itself has this CN.
   > But the validation of a *replacement* certificate in the `ca --etcd`
   > command checks for `swarm-ca`. The command rejects a certificate with CN
   > `MKE etcd Root CA` with `provided cert and key are invalid: root CA certificate has a
   > wrong common name: expected "swarm-ca", actual "MKE etcd Root CA"`. The
   > command accepts a certificate with CN `swarm-ca`. After the reboot cycle,
   > this certificate is exactly what is on disk at
   > `/var/lib/docker/volumes/ucp-etcd-root-ca/_data/cert.pem`. Use
   > `swarm-ca`, not the documented value, until Mirantis corrects the
   > documentation or the CLI. A future release may correct the check. Verify
   > the behavior again with your own MKE patch version before you use this
   > row.

3. **A recent MKE backup.** Mirantis requires a backup to run the `ca`
   command (or the `--force-recent-backup` override). See step 1 below.
4. Expect cluster downtime. When you replace a CA, several MKE components
   restart. You must also reboot every manager node, one at a time. Do the
   work outside peak hours.

## Procedure

1. Take a backup. You can skip the backup only if you deliberately decide to
   do so (for example, a new cluster with no data):

   ```bash
   cd ansible
   ansible-playbook -i <path-to-your-inventory> mke-backup-playbook.yml
   ```

   The playbook writes root-only (`0600`) archives on every manager to `mke_backup_dir` (default `/var/lib/mke-ansible-backup`, set in `vars/common-vars.yml`): `mke-<MKE version>-backup-<timestamp>.tar` and `swarm-<engine version>-backup-<timestamp>.tar.tgz`. The directory is persistent, so the archives stay after the manager reboots in step 3. The playbook never deletes them, and they stay on the disk of the manager until you delete them. They hold the MKE CA private keys. Delete them after you verify the new CAs and when you no longer need them.

   If you skip the backup, set `mke_custom_ca_force_recent_backup: true` in
   step 2. If you do not, the `ca` command refuses to run.

2. In `ansible/vars/mke-custom-ca-vars.yml` (or with `-e` on the command
   line), enable each CA that you want to replace, and set the bundle for it.
   Each CA is independent. In one run, you can enable one, two, or all three:

   | Variable | Purpose |
   |---|---|
   | `mke_custom_ca_cluster_enabled` / `_etcd_enabled` / `_client_enabled` | Toggle for each CA type. Default `false`. |
   | `mke_custom_ca_{cluster,etcd,client}_cert_src` / `_key_src` | Path on the Ansible controller, or literal PEM content, for the `cert.pem`/`key.pem` of each CA. |
   | `mke_custom_ca_force_recent_backup` | Passed as `--force-recent-backup`. Set to `true` only if you deliberately skipped step 1. |
   | `mke_custom_ca_reboot_after` | Default `true`. The new CA material has no effect until every manager reboots. Set to `false` only if you plan to reboot manually in a separate maintenance window. |

3. Run the playbook:

   ```bash
   ansible-playbook -i <path-to-your-inventory> mke-custom-ca-playbook.yml \
     -e mke_custom_ca_cluster_enabled=true \
     -e mke_custom_ca_cluster_cert_src=/path/to/cluster-ca-cert.pem \
     -e mke_custom_ca_cluster_key_src=/path/to/cluster-ca-key.pem
   ```

   The playbook does these steps in this order:
   1. It stages the supplied cert/key on the lead manager. It runs
      `mke ca --cluster`/`--etcd`/`--client` for each enabled CA type
      (`tasks/mke-custom-ca-tasks.yml`). Then it removes the staged copy.
   2. It detects the current Swarm Raft leader among the managers
      (`docker node inspect --format '{{.ManagerStatus.Leader}}'`). It does
      not assume the leader, because leadership can move from the node that
      ran the first `swarm init`.
   3. It reboots every non-leader manager, one at a time. Then it reboots the
      leader last, as Mirantis documents. After each reboot, it waits for MKE
      to report healthy before it goes to the next node.

## Expected Results

- After the run completes, every manager reports healthy and is back in the cluster:

  ```bash
  docker node ls --format "{{.ID}} {{.Hostname}} {{.Status}} {{.TLSStatus}}"
  ```

- Replacement of the **Client Root CA** invalidates existing non-admin client
  bundles. Affected users must download new bundles (see
  [Access the cluster](access-cluster.md)).
- Replacement of the **Cluster** or **etcd Root CA** does not invalidate client
  bundles by itself, but it causes the restarts and reboots described above.
- For all three CA types, the on-disk certificate of each CA has the exact
  SHA-256 fingerprint of the supplied certificate after the run. The paths are
  `/var/lib/docker/swarm/certificates/swarm-root-ca.crt` for Cluster,
  `/var/lib/docker/volumes/ucp-etcd-root-ca/_data/cert.pem` for etcd, and
  `/var/lib/docker/volumes/ucp-client-root-ca/_data/cert.pem` for Client.
  `docker node ls` shows every manager as `Ready`. `kubectl get nodes`
  succeeds with a newly downloaded client bundle.

## F.A.Q

### Can I replace more than one CA in a single run?

Yes. Enable any combination of `mke_custom_ca_cluster_enabled`,
`_etcd_enabled`, and `_client_enabled` together. The playbook applies each
enabled CA in sequence. Then it does one shared reboot pass at the end.

### Do I have to let it reboot the managers?

The new CA material does not take effect until every manager reboots. Set
`mke_custom_ca_reboot_after: false` only if you want to control when the
reboot happens. Until you reboot manually, MKE keeps using the old CA
material.

### Can I skip the backup requirement?

Only if you set `mke_custom_ca_force_recent_backup: true`. This passes
`--force-recent-backup` directly to the `ca` CLI. Use it only when you
deliberately accept the risk (for example, a new cluster with nothing to
restore).

### Is this the same as configuring MKE's web-server TLS certificate?

No. See [Use your own TLS certificate for MKE](../installation-guide/use-custom-tls-certificates.md)
for that certificate. You can set it only at installation, and it covers only
the browser/API-facing certificate. This playbook replaces the internal CAs of
MKE and you can run it at any time after installation.

## References

- [Manage MKE certificate authorities](https://docs.mirantis.com/mke/3.9/ops/administer-cluster/manage-certificate-authorities.html)
- [`ca` CLI reference](https://docs.mirantis.com/mke/3.9/cli-ref/mke-cli-ca.html)
