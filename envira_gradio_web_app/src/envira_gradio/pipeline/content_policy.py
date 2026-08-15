"""Consumer retention policy for valid semantic sections removed from the body stream."""

from __future__ import annotations

import re
from typing import Any

from .config import ContentPolicyConfig

_HEADINGS_BY_LANGUAGE = {
    "en": {
        "references": re.compile(r"^(references|bibliography)$", re.I),
        "acknowledgements": re.compile(r"^(acknowledg(e)?ments?)$", re.I),
        "declarations": re.compile(
            r"^(declarations?|conflict(s)? of interest|competing interests?)$", re.I
        ),
        "appendices": re.compile(r"^(appendix|appendices)(\b|\s+[a-z0-9])", re.I),
        "supplementary_sections": re.compile(
            r"^(supplementary|supporting)\s+(material|information|data)", re.I
        ),
    }
}


def section_category(text: str, language: str = "en") -> str | None:
    normalized = " ".join(text.split()).strip().rstrip(":.")
    patterns = _HEADINGS_BY_LANGUAGE.get("en" if language == "auto" else language, {})
    return next(
        (name for name, pattern in patterns.items() if pattern.match(normalized)), None
    )


def apply_content_policy(
    excluded: list[dict[str, Any]],
    policy: ContentPolicyConfig,
    *,
    language: str = "en",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Move configured semantic sections back to the retained stream, preserving provenance."""
    ordered = sorted(
        excluded,
        key=lambda row: (
            int(row.get("page_number", -1)),
            int(row.get("post_conclusion_sequence_index", 10**9)),
        ),
    )
    active: str | None = None
    retained, remaining, decisions = [], [], []
    for region in ordered:
        heading = section_category(
            str(region.get("text") or region.get("orig") or ""), language
        )
        if heading:
            active = heading
        enabled = bool(active and getattr(policy, f"retain_{active}"))
        secondary_action = (
            "secondary_stream"
            if policy.preserve_excluded_sections_in_secondary_stream
            else "raw_only"
        )
        decision = {
            "region_id": region.get("layout_region_id"),
            "section_category": active,
            "action": "retain" if enabled else secondary_action,
            "reason": "content_policy" if active else "unclassified_tail",
        }
        decisions.append(decision)
        if enabled:
            restored = dict(region)
            restored["content_policy_disposition"] = "retained_semantic_section"
            restored["content_policy_section"] = active
            retained.append(restored)
        elif policy.preserve_excluded_sections_in_secondary_stream:
            remaining.append(region)
    return retained, remaining, decisions
