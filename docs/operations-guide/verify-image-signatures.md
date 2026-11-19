# Verify bootc-mke3 image signatures

`bootc-mirantis` (the repository that builds and pushes `bootc-mke3` OCI
images) signs every image that it pushes with cosign. These images are the
`rocky-9-base` base image and the versioned `bootc-mke3` product image. It
pushes them to the dev registry (`registry.ci.mirantis.com/bootc-mke3-dev`)
and the prod registry (`registry.mirantis.com/bootc-mke3`). Each registry has
its own key pair. This runbook describes how to verify that signature. You can
do this check at any of three points in the lifecycle of an image in this
repository:

- **Mirroring** it into your own internal or air-gapped registry. See the
  [air-gap runbook](../installation-guide/airgap-bootc-mke3.md).
- **Pulling** it for use, for example before you put it in an Ansible
  inventory or kickstart file. See
  [Provisioning](../installation-guide/provisioning.md#registry).
- **Using** it: you install from it, or you switch an existing node to it
  during an upgrade. For the install (Generic ISO kickstart), see
  [ISO editions](../installation-guide/iso-editions.md#generic-image-customisation).
  For the upgrade, see
  [Upgrade via the ClusterUpgrade CR](upgrade-with-controller.md) or the
  [Ansible exception path](upgrade-with-ansible.md).

## Prerequisites

1. `cosign` v2.5.3 installed on the machine that does the verification. This
   is the version that `bootc-mirantis` signs with. Newer major versions
   (v3.x) change the flag semantics for transparency-log handling. They are not
   guaranteed to be compatible with the signatures that this repository makes.
2. The current public key for the registry that you verify against (`dev`
   or `prod`). Public keys are **not** committed to any repository and are
   **not** published to any URL. Ask PRODENG for the current key. For the
   current policy on key storage and retrieval, see
   [`docs/cosign-signing.md`](https://github.com/Mirantis/bootc-mirantis/blob/main/docs/cosign-signing.md)
   in `bootc-mirantis`. This file also states what to do if you suspect that a
   key rotated.

## Verify

```sh
# prod — registry.mirantis.com, uploads to the public Rekor transparency log
cosign verify --key <path-to-prod-public-key-from-PRODENG> \
  registry.mirantis.com/bootc-mke3/<image>:<tag>

# dev — registry.ci.mirantis.com/bootc-mke3-dev, no transparency log
cosign verify --key <path-to-dev-public-key-from-PRODENG> \
  --private-infrastructure=true registry.ci.mirantis.com/bootc-mke3-dev/<image>:<tag>
```

`<image>` is `rocky-9-base` or the versioned `bootc-mke3` product image name
(of the form `r<rocky-version>-mcr<mcr-version>-mke<mke-version>-bare`, see
the [Releases page](https://github.com/Mirantis/bootc-mke3/releases)).
`<tag>` is the build tag that you mirror, pull, or switch to.

If a signature does not match, a signature is missing, or a key does not
match, `cosign verify` exits with a non-zero code and prints a diagnostic.
Treat this as a hard failure. Do not mirror, pull, install from, or switch to
that image. Check the exit code. A non-zero exit code is the failure signal.
Warning text on stdout is not the failure signal.

## At mirroring time

Before or while you mirror a `bootc-mke3` OCI image into your own registry
(see the [air-gap runbook](../installation-guide/airgap-bootc-mke3.md)),
verify it against the source registry (`registry.mirantis.com` or
`registry.ci.mirantis.com/bootc-mke3-dev`). Use the command above.
Mirroring tools that copy by digest (for example `skopeo copy`) copy the image
manifest. They do not necessarily copy the cosign signature, because
signatures are stored as separate OCI artifacts next to the image. Therefore
verify against the source before you copy. After the copy, verify again
against the destination if you do not know that your mirroring tool copies
signature artifacts too.

## At pull time

Before you put a `bootc-mke3` image reference in an Ansible variable
(`bootc_image_ref` in `vars/upgrade-vars.yml`), a kickstart file, or a manual
`podman pull`/`skopeo copy`, verify it with the command above. Use the
registry that the reference resolves to (`registry.mirantis.com`, your
internal mirror, or the dev registry).

## At install/switch time

- **Initial install (Generic ISO kickstart):** verify the `<oci-name>` before
  you put it in the `bootc switch --mutate-in-place --transport registry
  <oci-name>` line of the kickstart. See
  [Generic image customisation](../installation-guide/iso-editions.md#generic-image-customisation).
- **Upgrade:** before you apply the upgrade, verify the target image. In the
  Ansible path, the target is `bootc_image_ref` (see
  [Upgrade via Ansible](upgrade-with-ansible.md)). In the `ClusterUpgrade` CR
  path, the target is `spec.os.image` (see the target-image-access step in
  [Upgrade via the ClusterUpgrade CR](upgrade-with-controller.md)). Both paths
  drive `bootc switch`/`bootc upgrade` on cluster nodes.

## Scope

The [Verify](#verify) command above covers the images that `bootc-mirantis`
pushes itself: `rocky-9-base` and the versioned `bootc-mke3` product image, in
both the dev and prod registries.

The controllers are built and signed by their own repositories, not by
`bootc-mirantis`:

| Component | Signed? | Notes |
|---|---|---|
| `cluster-upgrade-controller` | Yes | The release workflow of the repository signs production images and the Helm chart with cosign (PRODENG-3686, Done 2026-08-25). |
| `machine-config-controller` | Yes | Same as above (PRODENG-3686). |

The signing key of the controllers is configured in their own CI, not in
`bootc-mirantis`. Do not assume that the `bootc-mke3` prod public key verifies
them. Ask PRODENG which public key applies before you rely on a verification
result.

## SBOM and CVE scan reports on GitHub releases

Separately from signatures, each production release on
[`Mirantis/bootc-mke3` Releases](https://github.com/Mirantis/bootc-mke3/releases)
has the SBOM and CVE-scan reports that were made when `bootc-mirantis` built
the images (PRODENG-3712). There are six files for each platform, named
`<platform>-<image>-<report>`. `<platform>` is `bare` or `cloud`. `<image>` is
`base` (`rocky-9-base`) or `mke3` (the `bootc-mke3` product image):

| File | Content |
|---|---|
| `<platform>-{base,mke3}-sbom.json` | CycloneDX SBOM generated by `syft` |
| `<platform>-{base,mke3}-trivy.json` | `trivy` findings, machine-readable |
| `<platform>-{base,mke3}-trivy.txt` | The same findings as a table |

How to read the reports:

- **The trivy reports list only fixable HIGH/CRITICAL findings.** The scan runs
  with `--scanners vuln --ignore-unfixed --severity HIGH,CRITICAL`. Therefore
  the reports do not show vulnerabilities that have no published fix, and they
  do not show anything below HIGH. An empty report does not mean that the image
  has no known CVEs. For the full result, use the SBOM with your own scanner.
- **They are a snapshot from build time.** Nothing scans again after the
  release. The reports do not show CVEs that are published later. Scan the SBOM
  again periodically.
- **Do not add the `base` and `mke3` counts together.** `bootc-mke3` is built
  `FROM` the base image, so the findings of the base layer are in both reports.
  When you count, deduplicate on `(Target, VulnerabilityID, PkgName)`.
- **The scope is the two OCI images.** This pipeline does not scan controller
  images and charts.
- **They are not signed with cosign.** Signatures cover the OCI images above,
  not these release assets. Treat the reports as information, not as an
  attestation.
- **The reports are best-effort.** If a report is missing, the pipeline skips
  it with a warning. It does not fail the release. Releases up to and including
  build `20260917-79` have no reports. `20260922-83` (`bare` + `cloud`) is the
  first release that has them.

Example: list the findings of the `bootc-mke3` image of a release, with one
row for each deduplicated CVE and package.

```sh
jq -r '[.Results[]? | .Target as $t | (.Vulnerabilities // [])[]
        | [$t, .Severity, .VulnerabilityID, .PkgName, .InstalledVersion, (.FixedVersion // "-")]]
      | unique[] | @tsv' cloud-mke3-trivy.json
```

## Key rotation

Keys rotate independently for each environment (dev/prod). This repository
does not get a notification when a key rotates. Always ask PRODENG for the
*current* key. Do not reuse a key that you got before. Verify again if you
suspect that a rotation occurred since your last check.
