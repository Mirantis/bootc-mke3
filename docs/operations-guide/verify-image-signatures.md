# Verify bootc-mke3 image signatures

`bootc-mirantis` (the repository that builds and pushes `bootc-mke3` OCI
images) cosign-signs every image it pushes: the `rocky-9-base` base image
and the versioned `bootc-mke3` product image, in both its dev registry
(`registry.ci.mirantis.com/bootc-mke3-dev`) and prod registry
(`registry.mirantis.com/bootc-mke3`), each registry with its own key pair.
This runbook covers verifying that signature — a check you can run at any of
three points in an image's lifecycle in this repo:

- **Mirroring** it into your own internal/air-gapped registry — see the
  [air-gap runbook](../installation-guide/airgap-bootc-mke3.md).
- **Pulling** it for use, e.g. before referencing it in an Ansible inventory
  or kickstart file — see [Provisioning](../installation-guide/provisioning.md#registry).
- **Using** it — installing from it (Generic ISO kickstart, see
  [ISO editions](../installation-guide/iso-editions.md#generic-image-customisation))
  or switching an existing node to it during an upgrade (see
  [Upgrade via the ClusterUpgrade CR](upgrade-with-controller.md) or the
  [Ansible exception path](upgrade-with-ansible.md)).

## Prerequisites

1. `cosign` v2.5.3 installed on the machine doing the verification — this
   matches the version `bootc-mirantis` signs with. Newer major versions
   (v3.x) change flag semantics for transparency-log handling and are not
   guaranteed compatible with the signatures produced here.
2. The current public key for the registry you're verifying against (`dev`
   or `prod`). Public keys are **not** committed to any repository and are
   **not** published to any URL — ask PRODENG for the current key. See
   `bootc-mirantis`'s
   [`docs/cosign-signing.md`](https://github.com/Mirantis/bootc-mirantis/blob/main/docs/cosign-signing.md)
   for the current key-storage and retrieval policy, and for what to do if
   you suspect a key has rotated.

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
the [Releases page](https://github.com/Mirantis/bootc-mke3/releases)); `<tag>` is whichever build
tag you're mirroring, pulling, or switching to.

A signature mismatch, a missing signature, or a key mismatch makes `cosign
verify` exit non-zero and print a diagnostic — treat that as a hard failure
and do not mirror, pull, install from, or switch to that image. Check the
exit code; a non-zero exit is the failure signal, not merely the presence of
warning text on stdout.

## At mirroring time

Before or during mirroring a `bootc-mke3` OCI image into your own registry
(see the [air-gap runbook](../installation-guide/airgap-bootc-mke3.md)),
verify it against the source registry (`registry.mirantis.com` or
`registry.ci.mirantis.com/bootc-mke3-dev`) using the command above.
Mirroring tools that copy by digest (e.g. `skopeo copy`) copy the image
manifest but do not necessarily carry the cosign signature — signatures are
stored as separate OCI artifacts alongside the image — so verify against the
source before copying, and re-verify against the destination afterwards if
your mirroring tool is not known to copy signature artifacts too.

## At pull time

Before pulling a `bootc-mke3` image reference into an Ansible variable
(`bootc_image_ref` in `vars/upgrade-vars.yml`), a kickstart file, or a
manual `podman pull`/`skopeo copy`, verify it with the command above against
whichever registry (`registry.mirantis.com`, your internal mirror, or the
dev registry) that reference resolves to.

## At install/switch time

- **Initial install (Generic ISO kickstart):** verify the `<oci-name>`
  before putting it in the kickstart's `bootc switch --mutate-in-place
  --transport registry <oci-name>` line — see
  [Generic image customisation](../installation-guide/iso-editions.md#generic-image-customisation).
- **Upgrade:** verify the target `bootc_image_ref` (Ansible path, see
  [Upgrade via Ansible](upgrade-with-ansible.md)) or `spec.os.image`
  (`ClusterUpgrade` CR path, see the target-image-access step in
  [Upgrade via the ClusterUpgrade CR](upgrade-with-controller.md))
  before applying it — both drive `bootc switch`/`bootc upgrade` on cluster
  nodes.

## Scope

The [Verify](#verify) command above covers images `bootc-mirantis` pushes
itself: `rocky-9-base` and the versioned `bootc-mke3` product image, in both
the dev and prod registries.

The controllers are built and signed by their own repositories, not by
`bootc-mirantis`:

| Component | Signed? | Notes |
|---|---|---|
| `cluster-upgrade-controller` | Yes | Production images and Helm chart are cosign-signed by the repository's release workflow (PRODENG-3686, Done 2026-08-25). |
| `machine-config-controller` | Yes | Same as above (PRODENG-3686). |

The controllers' signing key is configured in their own CI, not in
`bootc-mirantis`. Do not assume the `bootc-mke3` prod public key verifies
them — ask PRODENG which public key applies before relying on a verification
result.

## SBOM and CVE scan reports on GitHub releases

Separately from signatures, each production release on
[`Mirantis/bootc-mke3` Releases](https://github.com/Mirantis/bootc-mke3/releases)
carries the SBOM and CVE-scan reports produced when `bootc-mirantis` built the
images (PRODENG-3712). Six files per platform, named
`<platform>-<image>-<report>`, where `<platform>` is `bare` or `cloud`, and
`<image>` is `base` (`rocky-9-base`) or `mke3` (the `bootc-mke3` product image):

| File | Content |
|---|---|
| `<platform>-{base,mke3}-sbom.json` | CycloneDX SBOM generated by `syft` |
| `<platform>-{base,mke3}-trivy.json` | `trivy` findings, machine-readable |
| `<platform>-{base,mke3}-trivy.txt` | The same findings as a table |

How to read them:

- **The trivy reports list fixable HIGH/CRITICAL findings only.** The scan runs
  with `--scanners vuln --ignore-unfixed --severity HIGH,CRITICAL`, so
  vulnerabilities with no published fix, and everything below HIGH, are absent.
  An empty report does not mean the image has no known CVEs. Use the SBOM with
  your own scanner for the full picture.
- **They are a build-time snapshot.** Nothing rescans after the release; CVEs
  published later are not reflected. Re-scan the SBOM periodically.
- **Do not add the `base` and `mke3` counts together.** `bootc-mke3` is built
  `FROM` the base image, so base-layer findings appear in both reports. When
  counting, deduplicate on `(Target, VulnerabilityID, PkgName)`.
- **Scope is the two OCI images.** Controller images and charts are not
  scanned in this pipeline.
- **They are not cosign-signed.** Signatures cover the OCI images above, not
  these release assets. Treat the reports as informational, not as an
  attestation.
- **Presence is best-effort.** A missing report is skipped with a warning, not
  a release failure. Releases up to and including build `20260917-79` have no
  reports; `20260922-83` (`bare` + `cloud`) is the first with them.

Example: list the findings of a release's `bootc-mke3` image, one row per
deduplicated CVE and package.

```sh
jq -r '[.Results[]? | .Target as $t | (.Vulnerabilities // [])[]
        | [$t, .Severity, .VulnerabilityID, .PkgName, .InstalledVersion, (.FixedVersion // "-")]]
      | unique[] | @tsv' cloud-mke3-trivy.json
```

## Key rotation

Keys rotate independently per environment (dev/prod), and this repo is not
notified when that happens. Always ask PRODENG for the *current* key rather
than reusing a previously obtained one, and re-verify if you suspect a
rotation occurred since you last checked.
