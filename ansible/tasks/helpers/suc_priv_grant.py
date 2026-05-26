#!/usr/bin/env python3
"""
Merges System Upgrade Controller configuration into the MKE cluster TOML file.

Makes two independent changes:

1. [cluster_config] — priv-attribute allowlists
   Ensures priv_attributes_allowed_for_service_accounts includes all supported
   attributes (hostIPC, hostNetwork, hostPID, hostBindMounts, privileged,
   kernelCapabilities) and priv_attributes_service_accounts includes <sa-entry>.
   Allows the SA's pods to use privileged security contexts without cluster-admin.

2. [scheduling_configuration] — all-node scheduling
   Sets enable_admin_ucp_scheduling = true so all authenticated users and
   service accounts can schedule on manager and MSR nodes.

Ref: https://docs.mirantis.com/mke/3.9/ops/deploy-apps-k8s/admission-controllers-for-access.html

Idempotent: existing entries are preserved; duplicate entries are never added.
Usage: python3 suc_priv_grant.py <path-to-mke-config.toml> <namespace:serviceaccount>
"""

import re
import sys

CLUSTER_SECTION = "[cluster_config]"
ALLOWED_KEY = "priv_attributes_allowed_for_service_accounts"
SA_KEY = "priv_attributes_service_accounts"

# All privilege attributes supported by the MKE UCPAuthorization admission controller.
# Ref: https://docs.mirantis.com/mke/3.9/ops/deploy-apps-k8s/admission-controllers-for-access.html
ATTR_ENTRIES = [
    "hostIPC",
    "hostNetwork",
    "hostPID",
    "hostBindMounts",
    "privileged",
    "kernelCapabilities",
]

SCHEDULING_SECTION = "[scheduling_configuration]"
ADMIN_SCHEDULING_KEY = "enable_admin_ucp_scheduling"

# Matches a bare TOML section header — single brackets only, not [[array-of-tables]].
_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]$")


def _parse_str_array(line):
    """Return all double-quoted string values from a TOML inline-array line."""
    return re.findall(r'"([^"]*)"', line)


def _format_str_array(items):
    return "[" + ", ".join(f'"{v}"' for v in items) + "]"


def _ensure(items, entry):
    """Return items with entry appended if not already present."""
    return items if entry in items else items + [entry]


def _ensure_all(items, entries):
    """Return items with every element of entries appended if not already present."""
    result = items
    for entry in entries:
        result = _ensure(result, entry)
    return result


def _insert_before_trailing_blanks(lst, line):
    """Insert line into lst just before any trailing blank lines."""
    idx = len(lst)
    while idx > 1 and not lst[idx - 1].strip():
        idx -= 1
    lst.insert(idx, line)


def _locate_section(lines, section):
    """Return (section_start, section_end, key_positions) for the named section.

    section_start is None when the section is absent.
    section_end is the index of the first line of the next section (or len(lines)).
    key_positions is a dict mapping stripped key prefixes to their line index.
    """
    in_target = False
    section_start = None
    section_end = len(lines)
    key_positions = {}

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _SECTION_RE.match(stripped):
            if stripped == section:
                in_target = True
                section_start = i
            elif in_target:
                in_target = False
                section_end = i
                break
        elif in_target and stripped and not stripped.startswith("#"):
            # Record the index of the first occurrence of each key name.
            key = stripped.split("=")[0].strip()
            key_positions.setdefault(key, i)

    return section_start, section_end, key_positions


def _merge_cluster_config(lines, sa_entry):
    """Merge priv-attribute arrays into [cluster_config]. Mutates lines in-place."""
    section_start, section_end, key_pos = _locate_section(lines, CLUSTER_SECTION)

    if section_start is None:
        # Append the entire section.
        lines.append(f"\n{CLUSTER_SECTION}\n")
        lines.append(f"  {ALLOWED_KEY} = {_format_str_array(ATTR_ENTRIES)}\n")
        lines.append(f"  {SA_KEY} = {_format_str_array([sa_entry])}\n")
        return

    # Rebuild only the section lines so other sections are untouched.
    section_lines = lines[section_start:section_end]
    new_section = []
    allowed_found = False
    sa_found = False

    for line in section_lines:
        key = line.strip()
        if key.startswith(ALLOWED_KEY):
            merged = _ensure_all(_parse_str_array(line), ATTR_ENTRIES)
            new_section.append(f"  {ALLOWED_KEY} = {_format_str_array(merged)}\n")
            allowed_found = True
        elif key.startswith(SA_KEY):
            merged = _ensure(_parse_str_array(line), sa_entry)
            new_section.append(f"  {SA_KEY} = {_format_str_array(merged)}\n")
            sa_found = True
        else:
            new_section.append(line)

    if not allowed_found:
        _insert_before_trailing_blanks(
            new_section,
            f"  {ALLOWED_KEY} = {_format_str_array(ATTR_ENTRIES)}\n",
        )
    if not sa_found:
        _insert_before_trailing_blanks(
            new_section,
            f"  {SA_KEY} = {_format_str_array([sa_entry])}\n",
        )

    lines[section_start:section_end] = new_section


def _set_bool(lines, section, key):
    """Set key = true in the named section. Creates the section if absent."""
    section_start, section_end, key_pos = _locate_section(lines, section)

    if section_start is None:
        lines.append(f"\n{section}\n")
        lines.append(f"  {key} = true\n")
        return

    if key in key_pos:
        lines[key_pos[key]] = f"  {key} = true\n"
    else:
        section_lines = lines[section_start:section_end]
        _insert_before_trailing_blanks(section_lines, f"  {key} = true\n")
        lines[section_start:section_end] = section_lines


def process(content, sa_entry):
    lines = content.splitlines(keepends=True)
    _merge_cluster_config(lines, sa_entry)
    _set_bool(lines, SCHEDULING_SECTION, ADMIN_SCHEDULING_KEY)
    return "".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} <config.toml> <namespace:serviceaccount>")
    path = sys.argv[1]
    sa_entry = sys.argv[2]
    with open(path) as f:
        content = f.read()
    modified = process(content, sa_entry)
    with open(path, "w") as f:
        f.write(modified)
