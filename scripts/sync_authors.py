#!/usr/bin/env python3
"""Sync AuthorshipExtractor YAML from the AIND contribution portal."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://metadata-portal.allenneuraldynamics.org/contributions"
CONTRIBUTION_FORM = "https://data.allenneuraldynamics.org/contributions/add"
DEFAULT_PROJECT = "p3_data_release"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "authors.yml"
DEFAULT_AVATAR_MANIFEST = Path(__file__).resolve().parents[1] / "author_avatars.json"

CREDIT_ROLE_NAMES = {
    "conceptualization": "Conceptualization",
    "methodology": "Methodology",
    "software": "Software",
    "validation": "Validation",
    "formal-analysis": "Formal analysis",
    "investigation": "Investigation",
    "resources": "Resources",
    "data-curation": "Data curation",
    "writing-original-draft": "Writing – original draft",
    "writing-review-editing": "Writing – review & editing",
    "visualization": "Visualization",
    "supervision": "Supervision",
    "project-administration": "Project administration",
    "funding-acquisition": "Funding acquisition",
}
PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def api_url(path: str, **parameters: str) -> str:
    return f"{API_ROOT}/{path}?{urllib.parse.urlencode(parameters)}"


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "openscope-p3-publication-authorship-sync/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def load_avatar_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("Author avatar manifest version is not supported")
    portraits = manifest.get("contributors") or {}
    unresolved = manifest.get("unresolved") or {}
    if not isinstance(portraits, dict) or not isinstance(unresolved, dict):
        raise ValueError("Author avatar manifest records must be mappings")
    overlap = set(portraits) & set(unresolved)
    if overlap:
        raise ValueError(f"Avatar records cannot be both resolved and unresolved: {overlap}")
    for contributor_id, record in portraits.items():
        if not isinstance(record, dict) or not record.get("name"):
            raise ValueError(f"Avatar record is invalid: {contributor_id}")
        for field in ("avatar_url", "source_page"):
            parsed = urllib.parse.urlparse(str(record.get(field) or ""))
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(
                    f"Avatar {field} must be an HTTPS URL: {contributor_id}"
                )
        if int(record.get("width") or 0) <= 0 or int(record.get("height") or 0) <= 0:
            raise ValueError(f"Avatar dimensions are invalid: {contributor_id}")
    return manifest


def canonical_role(role: str) -> str:
    return CREDIT_ROLE_NAMES.get(role, role.replace("-", " ").capitalize())


def author_id(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "contributor"


def unique_author_id(name: str, used_ids: set[str]) -> str:
    base = author_id(name)
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def clean_orcid(value: Any) -> str | None:
    if not value:
        return None
    identifier = re.sub(r"\s+", "", str(value))
    if re.fullmatch(r"\d{4}-\d{4}-\d{4}-[\dX]{4}", identifier):
        return identifier
    return None


def transform_contributor(
    entry: dict[str, Any],
    used_ids: set[str],
    avatar_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    author = entry.get("author") or {}
    name = str(author.get("name") or "").strip()
    if not name:
        raise ValueError("Contribution record is missing author.name")

    contributor_id = unique_author_id(name, used_ids)
    contributor: dict[str, Any] = {
        "id": contributor_id,
        "name": name,
    }
    avatar = (avatar_records or {}).get(contributor_id)
    if avatar:
        portal_name = re.sub(r"\s+", " ", name).strip()
        avatar_name = re.sub(r"\s+", " ", str(avatar["name"])).strip()
        if portal_name != avatar_name:
            raise ValueError(
                f"Avatar identity mismatch for {contributor_id}: "
                f"{avatar_name!r} != {portal_name!r}"
            )
        contributor["avatar_url"] = str(avatar["avatar_url"])
    orcid = clean_orcid(author.get("registry_identifier"))
    if orcid:
        contributor["orcid"] = orcid
    if author.get("email"):
        contributor["email"] = str(author["email"]).strip()

    affiliations = [
        str(affiliation).strip()
        for affiliation in author.get("affiliation") or []
        if str(affiliation).strip()
    ]
    contributor["affiliations"] = affiliations

    credit_levels = []
    for credit in entry.get("credit_levels") or []:
        level = {
            "role": canonical_role(str(credit["role"])),
            "level": str(credit["level"]),
        }
        if credit.get("description"):
            level["description"] = str(credit["description"]).strip()
        if credit.get("linked_assets"):
            level["linked_assets"] = credit["linked_assets"]
        credit_levels.append(level)
    contributor["roles"] = [level["role"] for level in credit_levels]
    contributor["credit_levels"] = credit_levels

    section_contributions = []
    for section in entry.get("section_levels") or []:
        contribution = {
            "section": str(section["section"]).strip(),
            "effort": str(section["level"]),
        }
        if section.get("description"):
            contribution["description"] = str(section["description"]).strip()
        section_contributions.append(contribution)
    contributor["section_contributions"] = section_contributions

    timeline = {}
    if entry.get("start_date"):
        timeline["joined"] = str(entry["start_date"])
    if entry.get("end_date"):
        timeline["left"] = str(entry["end_date"])
    if timeline:
        contributor["timeline"] = timeline

    if orcid:
        contributor["social_links"] = [
            {"platform": "orcid", "url": f"https://orcid.org/{orcid}"}
        ]
    contributor["is_admin"] = bool(entry.get("is_admin"))
    contributor["from_asset"] = bool(entry.get("from_asset"))
    return contributor


def transform_payload(
    payload: dict[str, Any],
    source_url: str,
    source_commit: dict[str, str],
    avatar_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = str(payload.get("project_name") or "")
    if not project:
        raise ValueError("Contribution payload is missing project_name")

    used_ids: set[str] = set()
    avatar_records = (avatar_manifest or {}).get("contributors") or {}
    contributors = [
        transform_contributor(entry, used_ids, avatar_records)
        for entry in payload.get("contributors") or []
    ]
    contributor_ids = {contributor["id"] for contributor in contributors}
    manifest_ids = set(avatar_records) | set((avatar_manifest or {}).get("unresolved") or {})
    unknown_ids = manifest_ids - contributor_ids
    if unknown_ids:
        raise ValueError(f"Avatar manifest contains unknown contributors: {unknown_ids}")
    portal_settings = {
        key: payload.get(key)
        for key in (
            "sections",
            "doi",
            "assets",
            "edit_locked",
            "show_sections",
            "show_levels",
            "show_timeline",
            "allow_lead",
            "allow_levels",
        )
    }
    return {
        "version": 1,
        "source": {
            "project": project,
            "endpoint": source_url,
            "contribution_form": f"{CONTRIBUTION_FORM}?project={project}",
            "commit": source_commit["commit"],
            "timestamp": source_commit["timestamp"],
        },
        "portal": portal_settings,
        "project": {"contributors": contributors, "affiliations": []},
    }


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_key(value: Any) -> str:
    key = str(value)
    return key if PLAIN_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def emit_yaml(value: Any, indent: int, lines: list[str]) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        for key, child in value.items():
            rendered_key = yaml_key(key)
            if isinstance(child, dict | list) and child:
                lines.append(f"{prefix}{rendered_key}:")
                emit_yaml(child, indent + 2, lines)
            elif isinstance(child, dict):
                lines.append(f"{prefix}{rendered_key}: {{}}")
            elif isinstance(child, list):
                lines.append(f"{prefix}{rendered_key}: []")
            else:
                lines.append(f"{prefix}{rendered_key}: {yaml_scalar(child)}")
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, dict | list) and child:
                lines.append(f"{prefix}-")
                emit_yaml(child, indent + 2, lines)
            elif isinstance(child, dict):
                lines.append(f"{prefix}- {{}}")
            elif isinstance(child, list):
                lines.append(f"{prefix}- []")
            else:
                lines.append(f"{prefix}- {yaml_scalar(child)}")
    else:
        lines.append(f"{prefix}{yaml_scalar(value)}")


def dump_yaml(data: dict[str, Any]) -> str:
    lines = [
        "# Generated by scripts/sync_authors.py; do not edit contributor records here.",
        "# Update contributions through the form recorded under source.contribution_form.",
    ]
    emit_yaml(data, 0, lines)
    return "\n".join(lines) + "\n"


def sync_authors(
    project: str,
    output: Path,
    avatar_manifest_path: Path = DEFAULT_AVATAR_MANIFEST,
) -> tuple[int, str]:
    history_url = api_url("get", project=project, history="true")
    history = fetch_json(history_url)
    if not history:
        raise ValueError(f"No contribution history found for {project}")
    source_commit = history[0]
    source_url = api_url(
        "get", project=project, commit=source_commit["commit"], format="json"
    )
    payload = fetch_json(source_url)
    if payload.get("project_name") != project:
        raise ValueError(f"Requested {project}, received {payload.get('project_name')}")
    avatar_manifest = load_avatar_manifest(avatar_manifest_path)
    data = transform_payload(payload, source_url, source_commit, avatar_manifest)
    output.write_text(dump_yaml(data), encoding="utf-8")
    return len(data["project"]["contributors"]), source_commit["commit"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--avatar-manifest",
        type=Path,
        default=DEFAULT_AVATAR_MANIFEST,
        help="Remote-only author avatar URL manifest",
    )
    arguments = parser.parse_args()
    count, commit = sync_authors(
        arguments.project,
        arguments.output,
        arguments.avatar_manifest,
    )
    print(f"Wrote {arguments.output} with {count} contributors from commit {commit}")


if __name__ == "__main__":
    main()