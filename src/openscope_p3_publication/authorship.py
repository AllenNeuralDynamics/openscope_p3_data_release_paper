"""Apply a maintainer's local review to a pinned contribution snapshot."""

from copy import deepcopy
from typing import Any


def apply_author_review(
    payload: dict[str, Any],
    review: dict[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    """Return approved contributors without changing the submitted records."""
    if review.get("project") != payload.get("project_name"):
        raise ValueError("Author review project does not match the portal snapshot")
    if review.get("commit") != source_commit:
        raise ValueError("Author review commit does not match the portal snapshot")
    approvals = review.get("contributors")
    if not isinstance(approvals, dict) or not approvals:
        raise ValueError("Author review contributors must be a nonempty mapping")

    source_names = [
        str((entry.get("author") or {}).get("name") or "").strip()
        for entry in payload.get("contributors") or []
    ]
    if not all(source_names) or len(source_names) != len(set(source_names)):
        raise ValueError("Portal contributor names must be nonempty and unique for review")
    unknown_names = set(approvals) - set(source_names)
    if unknown_names:
        raise ValueError(f"Author review contains unknown contributors: {sorted(unknown_names)}")

    reviewed = deepcopy(payload)
    approved_contributors = []
    for entry, source_name in zip(reviewed["contributors"], source_names, strict=True):
        if source_name not in approvals:
            continue
        changes = approvals[source_name]
        if not isinstance(changes, dict) or set(changes) - {"name", "sections"}:
            raise ValueError(f"Unsupported author review changes for {source_name}")
        if "name" in changes:
            name = changes["name"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Reviewed author name must be a nonempty string")
            entry["author"]["name"] = name.strip()

        section_changes = changes.get("sections", {})
        if not isinstance(section_changes, dict):
            raise ValueError("Reviewed sections must be a mapping")
        sections = entry.get("section_levels") or []
        existing_sections = {section["section"] for section in sections}
        if set(section_changes) - existing_sections:
            raise ValueError(f"Reviewed section is not present for {source_name}")
        for replacement in section_changes.values():
            if replacement not in (payload.get("sections") or []):
                raise ValueError(f"Reviewed section is not a project section: {replacement}")
        for section in sections:
            section["section"] = section_changes.get(section["section"], section["section"])
        section_names = [section["section"] for section in sections]
        if len(section_names) != len(set(section_names)):
            raise ValueError(f"Reviewed sections would contain duplicates for {source_name}")
        approved_contributors.append(entry)

    names = [entry["author"]["name"].strip() for entry in approved_contributors]
    if len(names) != len(set(names)):
        raise ValueError("Reviewed contributor names would contain duplicates")
    reviewed["contributors"] = approved_contributors
    return reviewed