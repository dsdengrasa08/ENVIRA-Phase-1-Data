"""Class-aware, non-destructive caption-to-asset association.

Caption ownership is decided once from explicit lexical, geometric, column, and
structural evidence.  The stage emits relationships only; physical regions are
never resized, reclassified, or suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .config import CaptionAssociationConfig
from .types import LayoutRegion
from .region_index import RegionIndex

_REFERENCE_RE = re.compile(
    r"^\s*(?P<label>(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?P<kind>fig(?:ure)?\.?|table|tab\.?|equation|eq\.?|"
    r"algorithm|listing)\s+(?P<number>[A-Z]?\d+(?:[.\-]\w+)?|[A-Z]|[IVXLCDM]+))"
    r"(?:\s*[:.\-])?(?:\s+|$)",
    re.IGNORECASE,
)
_PARENT_TYPES = {"Figure", "Table", "Formula", "Code"}
_EXPECTED_PARENT = {
    "figure": {"Figure"},
    "table": {"Table"},
    "equation": {"Formula"},
    "algorithm": {"Code", "Figure"},
    "listing": {"Code"},
}
_BLOCKER_TYPES = {"Title", "Section-header", "Figure", "Table", "Formula", "Code"}


@dataclass(frozen=True)
class CaptionReference:
    kind: str
    label: str
    number: str


def parse_caption_reference(text: Any) -> CaptionReference | None:
    """Parse an explicit asset identifier without publisher-specific vocabulary."""
    match = _REFERENCE_RE.match(str(text or ""))
    if not match:
        return None
    raw_kind = match.group("kind").casefold().rstrip(".")
    kind = (
        "figure"
        if raw_kind in {"fig", "figure"}
        else "table"
        if raw_kind in {"tab", "table"}
        else "equation"
        if raw_kind in {"eq", "equation"}
        else raw_kind
    )
    return CaptionReference(kind, match.group("label").strip(), match.group("number"))


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _horizontal_overlap(a: list[float], b: list[float]) -> float:
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return intersection / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _blocker_between(
    caption: LayoutRegion,
    parent: LayoutRegion,
    regions: list[LayoutRegion],
    minimum_overlap: float,
) -> str | None:
    cb, pb = caption["bbox_px"], parent["bbox_px"]
    top, bottom = sorted(((cb[1] + cb[3]) / 2, (pb[1] + pb[3]) / 2))
    for region in regions:
        if (
            region is caption
            or region is parent
            or region.get("type") not in _BLOCKER_TYPES
        ):
            continue
        rb = region["bbox_px"]
        center = (rb[1] + rb[3]) / 2
        if top < center < bottom and _horizontal_overlap(cb, rb) >= minimum_overlap:
            return str(region["layout_region_id"])
    return None


def associate_captions(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    *,
    config: CaptionAssociationConfig | None = None,
    index: RegionIndex | None = None,
    metrics: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Assign each caption candidate to at most one compatible parent.

    Explicit identifiers constrain the eligible parent class. Detector-only
    captions may consider every supported parent class, but competing scores are
    retained as an unresolved relationship rather than resolved by input order.
    """
    config = config or CaptionAssociationConfig()
    if not config.enabled:
        return []
    index = index or RegionIndex.build(regions, pages)
    metrics = metrics if metrics is not None else {}
    metrics.update(
        caption_candidates=0,
        parent_pairs_considered=0,
        pairs_scored=0,
        blocker_queries=0,
    )
    output: list[dict[str, Any]] = []
    for page_number, page_regions in sorted(index.by_page.items()):
        width, height = index.page_sizes.get(page_number, (1.0, 1.0))
        parents = index.types(page_number, *sorted(_PARENT_TYPES))
        blockers = index.types(page_number, *sorted(_BLOCKER_TYPES))
        references = {
            str(region["layout_region_id"]): parse_caption_reference(
                region.get("text") or region.get("orig")
            )
            for region in page_regions
        }
        candidates = [
            r
            for r in page_regions
            if r.get("type") == "Caption" or references[str(r["layout_region_id"])]
        ]
        metrics["caption_candidates"] += len(candidates)
        for caption in candidates:
            reference = references[str(caption["layout_region_id"])]
            expected = _EXPECTED_PARENT.get(reference.kind) if reference else None
            cb = list(map(float, caption["bbox_px"]))
            alternatives: list[dict[str, Any]] = []
            for parent in parents:
                metrics["parent_pairs_considered"] += 1
                if expected and parent.get("type") not in expected:
                    continue
                pb = list(map(float, parent["bbox_px"]))
                overlap = _horizontal_overlap(cb, pb)
                gap = max(0.0, max(cb[1], pb[1]) - min(cb[3], pb[3])) / height
                if (
                    overlap < config.min_horizontal_overlap_ratio
                    or gap > config.max_vertical_gap_page_ratio
                ):
                    continue
                caption_column, parent_column = (
                    caption.get("reading_order_column"),
                    parent.get("reading_order_column"),
                )
                if caption_column not in {
                    None,
                    "single",
                    parent_column,
                } and parent_column not in {None, "single"}:
                    continue
                blocker = _blocker_between(
                    caption,
                    parent,
                    list(blockers),
                    config.blocker_horizontal_overlap_ratio,
                )
                metrics["blocker_queries"] += 1
                if blocker:
                    continue
                direction_match = (
                    cb[1] >= pb[3] if parent.get("type") != "Table" else cb[3] <= pb[1]
                )
                score = (
                    0.45 * overlap
                    + 0.30
                    * max(
                        0.0,
                        1 - gap / max(config.max_vertical_gap_page_ratio, 1e-9),
                    )
                    + 0.15 * bool(reference)
                    + 0.10 * direction_match
                )
                metrics["pairs_scored"] += 1
                alternatives.append(
                    {
                        "parent_region_id": str(parent["layout_region_id"]),
                        "parent_type": parent.get("type"),
                        "score": round(score, 6),
                        "horizontal_overlap": round(overlap, 6),
                        "vertical_gap_page_ratio": round(gap, 6),
                        "direction_match": direction_match,
                    }
                )
            alternatives = [
                item
                for item in alternatives
                if item["score"] >= config.acceptance_score
            ]
            alternatives.sort(
                key=lambda item: (-item["score"], item["parent_region_id"])
            )
            if not alternatives:
                output.append(
                    {
                        "relationship_id": f"p{page_number}:caption:{caption['layout_region_id']}",
                        "page_number": page_number,
                        "kind": "CAPTION_OF",
                        "child_region_id": str(caption["layout_region_id"]),
                        "parent_region_id": None,
                        "candidate_parents": [],
                        "status": "no_compatible_parent",
                        "proposed_action": "retain_unattached",
                        "caption_reference": reference.__dict__ if reference else None,
                    }
                )
                continue
            margin = (
                alternatives[0]["score"] - alternatives[1]["score"]
                if len(alternatives) > 1
                else None
            )
            ambiguous = margin is not None and margin < config.ambiguity_margin
            output.append(
                {
                    "relationship_id": f"p{page_number}:caption:{caption['layout_region_id']}",
                    "page_number": page_number,
                    "kind": "CAPTION_OF",
                    "child_region_id": str(caption["layout_region_id"]),
                    "parent_region_id": None
                    if ambiguous
                    else alternatives[0]["parent_region_id"],
                    "candidate_parents": alternatives,
                    "status": "unresolved_conflict" if ambiguous else "associated",
                    "proposed_action": "flag" if ambiguous else "associate",
                    "confidence": alternatives[0]["score"],
                    "ambiguity_margin": round(margin, 6)
                    if margin is not None
                    else None,
                    "caption_reference": reference.__dict__ if reference else None,
                    "features": {
                        "page_width": width,
                        "alternative_count": len(alternatives),
                    },
                }
            )
    return output
