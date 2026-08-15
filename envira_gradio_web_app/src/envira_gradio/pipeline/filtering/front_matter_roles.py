"""Explainable page-one document-role classification.

This module classifies valid publication apparatus separately from layout noise.
Decisions require semantic evidence plus front-matter structure; publisher names,
years, small type, and absolute coordinates are never destructive on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..config import Page1FilterConfig
from ..types import FilterStageResult

_BODY_HEADING = re.compile(
    r"^\s*(?:(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\s.)\-:]*)?"
    r"(introduction|background|materials?\s+and\s+methods?|methods?|results?)\b",
    re.I,
)
_ABSTRACT = re.compile(r"^\s*(abstract|summary)\b", re.I)
_KEYWORDS = re.compile(r"^\s*(key\s*words?|index\s+terms?)\b", re.I)
_HISTORY_HEADING = re.compile(
    r"^\s*(article|manuscript|publication|submission)\s*"
    r"(history|information|details?|record|timeline)\b",
    re.I,
)
_HISTORY_EVENT = re.compile(
    r"\b(receiv\w*|revis\w*|accept\w*|submit\w*|publish\w*|"
    r"available\s+(?:on|in)line|first\s+published|version\s+of\s+record)\b",
    re.I,
)
_DATE = re.compile(
    r"\b(?:\d{1,2}[\s./-]+(?:[A-Za-z]{3,12}|\d{1,2})[\s,./-]+\d{2,4}|"
    r"(?:[A-Za-z]{3,12})\s+\d{1,2},?\s+\d{4}|\d{4}-\d{1,2}-\d{1,2})\b"
)
_LEGAL = re.compile(
    r"(?:©|\bcopyright\b|\blicen[cs](?:e|ed|ing)\b|\ball\s+rights?\b|"
    r"\bright\s+to\s+(?:copy|reuse|reproduce|distribute)\b|"
    r"\bcreative\s+commons\b|\bopen\s+access\b|\bpermissions?\b|"
    r"\bpublished\s+by\b|\breproduction\b|\bredistribution\b)",
    re.I,
)
_PROSE_PUNCT = re.compile(r"[.!?](?:\s|$)")
_PROTECTED_LABELS = {
    "caption", "formula", "picture", "chart", "figure", "table", "reference"
}


@dataclass(frozen=True)
class _Profile:
    region: dict[str, Any]
    text: str
    words: int
    x0: float
    y0: float
    x1: float
    y1: float
    history_events: int
    dates: int
    legal_hits: int
    prose_like: bool
    protected: bool


def _page_size(page: Any) -> tuple[float, float]:
    width = getattr(page, "width_px", None) or page.get("image_width_px")
    height = getattr(page, "height_px", None) or page.get("image_height_px")
    return float(width), float(height)


def _profile(region: dict[str, Any], width: float, height: float) -> _Profile:
    text = " ".join(str(region.get("text") or region.get("orig") or "").split())
    words = len(text.split())
    x0, y0, x1, y1 = map(float, region["bbox_px"])
    label = str(region.get("docling_label") or "").lower()
    typ = str(region.get("type") or "").lower()
    history_events = len(_HISTORY_EVENT.findall(text))
    dates = len(_DATE.findall(text))
    legal_hits = len(_LEGAL.findall(text))
    prose_like = bool(words >= 18 and (_PROSE_PUNCT.search(text) or words >= 34))
    protected = bool(
        label in _PROTECTED_LABELS
        or typ in _PROTECTED_LABELS
        or _ABSTRACT.match(text)
        or _KEYWORDS.match(text)
        or _BODY_HEADING.match(text)
    )
    return _Profile(
        region, text, words, x0 / width, y0 / height, x1 / width, y1 / height,
        history_events, dates, legal_hits, prose_like, protected,
    )


def _overlap(a: _Profile, b: _Profile) -> float:
    intersection = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return intersection / max(min(a.x1 - a.x0, b.x1 - b.x0), 1e-9)


def classify_page1_front_matter_roles(
    regions: list[dict[str, Any]],
    page_map: dict[int, Any],
    config: Page1FilterConfig,
) -> FilterStageResult:
    """Move high-confidence administrative/legal roles out of the body stream."""
    if not config.role_classification_enabled or 1 not in page_map:
        return FilterStageResult(list(regions), diagnostics={"enabled": False})
    width, height = _page_size(page_map[1])
    profiles = [_profile(r, width, height) for r in regions if int(r.get("page_number", -1)) == 1]
    body_anchors = [p for p in profiles if _BODY_HEADING.match(p.text)]
    abstract_anchors = [p for p in profiles if _ABSTRACT.match(p.text)]
    body_start = min((p.y0 for p in body_anchors), default=1.0)
    structural_context = bool(body_anchors or abstract_anchors)

    decisions: dict[str, dict[str, Any]] = {}
    seeds: list[_Profile] = []
    for p in profiles:
        if p.protected or not p.text or p.words > config.role_max_candidate_words:
            continue
        before_body = structural_context and p.y0 < body_start
        compact = p.words <= 45 and (p.y1 - p.y0) <= 0.09
        history_semantics = p.history_events >= 2 or (
            p.history_events >= 1 and p.dates >= 1
        )
        history_heading = bool(_HISTORY_HEADING.match(p.text))
        legal_semantics = p.legal_hits >= 1
        role = None
        semantic_score = 0.0
        if history_semantics or history_heading:
            role = "article_history"
            semantic_score = min(1.0, 0.48 + 0.16 * p.history_events + 0.14 * p.dates + 0.2 * history_heading)
        elif legal_semantics:
            role = "publisher_legal"
            semantic_score = min(1.0, 0.64 + 0.12 * min(p.legal_hits, 3))
        if role is None:
            continue
        structural_score = 0.45 * before_body + 0.25 * compact + 0.20 * (not p.prose_like)
        confidence = min(1.0, 0.62 * semantic_score + 0.38 * structural_score)
        if p.prose_like:
            confidence -= 0.20
        if before_body and compact and confidence >= config.role_min_confidence:
            rid = str(p.region.get("layout_region_id"))
            decisions[rid] = {
                "region_id": rid, "role": role, "confidence": round(confidence, 3),
                "decision_kind": "semantic_structural_seed",
                "evidence": {
                    "before_body": before_body, "compact": compact,
                    "history_event_count": p.history_events, "date_count": p.dates,
                    "legal_concept_count": p.legal_hits, "prose_like": p.prose_like,
                },
            }
            seeds.append(p)

    # Include heading/continuation rows only when aligned with a confident semantic seed.
    for p in profiles:
        rid = str(p.region.get("layout_region_id"))
        if rid in decisions or p.protected or p.prose_like or p.words > config.role_max_candidate_words:
            continue
        for seed in seeds:
            gap = max(0.0, max(p.y0, seed.y0) - min(p.y1, seed.y1))
            if (
                gap <= config.role_cluster_max_vertical_gap
                and _overlap(p, seed) >= config.role_cluster_min_horizontal_overlap
                and p.y0 < body_start
                and (p.words <= 45 or _HISTORY_HEADING.match(p.text))
            ):
                decisions[rid] = {
                    "region_id": rid, "role": decisions[str(seed.region.get('layout_region_id'))]["role"],
                    "confidence": decisions[str(seed.region.get('layout_region_id'))]["confidence"],
                    "decision_kind": "aligned_group_continuation",
                    "evidence": {"seed_region_id": str(seed.region.get("layout_region_id"))},
                }
                break

    kept, excluded = [], []
    for region in regions:
        decision = decisions.get(str(region.get("layout_region_id")))
        if not decision:
            kept.append(region)
            continue
        excluded.append({
            **region,
            "filter_reason": f"page1_{decision['role']}",
            "document_role": decision["role"],
            "document_role_decision": decision,
            "content_policy_disposition": "secondary_stream",
        })
    return FilterStageResult(
        kept,
        excluded,
        {
            "enabled": True,
            "body_start_y": body_start if body_anchors else None,
            "structural_context_found": structural_context,
            "candidate_count": len(profiles), "drop_count": len(excluded),
            "decisions": list(decisions.values()),
        },
    )
