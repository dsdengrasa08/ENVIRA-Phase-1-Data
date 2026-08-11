"""Conservative overlap analysis for caption-related layout regions.

Raw and authoritative regions are never mutated.  This module collapses only
clear duplicates and otherwise records relationships for context-aware grouping.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import re
from typing import Any

from .config import CaptionOverlapConfig
from .geometry import bbox_area, intersection_area
from .types import LayoutRegion

_IDENTIFIER_RE = re.compile(
    r"^\s*(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?:table|tab\.)\s+(?:[A-Z](?:[.\-]?\d+)?|[IVXLCDM]+|\d+(?:[.\-]\w+)?)"
    r"(?:\s*[:.\-])?(?:\s+|$)",
    re.IGNORECASE,
)
_CAPTION_TYPES = {"Caption"}


def _text(region: LayoutRegion) -> str:
    return " ".join(str(region.get("text") or region.get("orig") or "").split())


def _normalized_text(region: LayoutRegion) -> str:
    return re.sub(r"\W+", " ", _text(region).casefold()).strip()


def _is_caption_candidate(region: LayoutRegion) -> bool:
    return region.get("type") in _CAPTION_TYPES or bool(
        _IDENTIFIER_RE.match(_text(region))
    )


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def overlap_features(
    a: LayoutRegion, b: LayoutRegion, page: dict[str, Any]
) -> dict[str, Any]:
    """Return symmetric and directional geometry plus optional text evidence."""
    ab = tuple(map(float, a["bbox_px"]))
    bb = tuple(map(float, b["bbox_px"]))
    area_a, area_b = bbox_area(ab), bbox_area(bb)
    intersection = intersection_area(ab, bb)
    union = area_a + area_b - intersection
    width, height = _page_size(page)
    iw = max(0.0, min(ab[2], bb[2]) - max(ab[0], bb[0]))
    ih = max(0.0, min(ab[3], bb[3]) - max(ab[1], bb[1]))
    text_a, text_b = _normalized_text(a), _normalized_text(b)
    if text_a and text_b:
        if text_a == text_b:
            text_relation = "equal"
        elif text_a in text_b:
            text_relation = "a_in_b"
        elif text_b in text_a:
            text_relation = "b_in_a"
        else:
            text_relation = "different"
    else:
        text_relation = "unavailable"
    return {
        "intersection_area": intersection,
        "iou": intersection / union if union else 0.0,
        "a_containment": intersection / area_a if area_a else 0.0,
        "b_containment": intersection / area_b if area_b else 0.0,
        "intersection_over_smaller": (
            intersection / min(area_a, area_b) if min(area_a, area_b) else 0.0
        ),
        "horizontal_overlap": (
            iw / min(ab[2] - ab[0], bb[2] - bb[0])
            if min(ab[2] - ab[0], bb[2] - bb[0]) > 0
            else 0.0
        ),
        "vertical_overlap": (
            ih / min(ab[3] - ab[1], bb[3] - bb[1])
            if min(ab[3] - ab[1], bb[3] - bb[1]) > 0
            else 0.0
        ),
        "area_ratio": (
            min(area_a, area_b) / max(area_a, area_b) if max(area_a, area_b) else 0.0
        ),
        "edge_delta_page_ratio": max(
            abs(ab[0] - bb[0]) / width,
            abs(ab[2] - bb[2]) / width,
            abs(ab[1] - bb[1]) / height,
            abs(ab[3] - bb[3]) / height,
        ),
        "vertical_gap_page_ratio": max(0.0, max(ab[1], bb[1]) - min(ab[3], bb[3]))
        / height,
        "text_relation": text_relation,
    }


def _relationship(a, b, features, config):
    same_class = a.get("type") == b.get("type")
    duplicate_geometry = (
        features["iou"] >= config.duplicate_iou
        and features["area_ratio"] >= config.duplicate_area_ratio
        and features["edge_delta_page_ratio"] <= config.duplicate_edge_page_ratio
    )
    text_supports_duplicate = features["text_relation"] in {"equal", "unavailable"}
    if same_class and duplicate_geometry and text_supports_duplicate:
        return "DUPLICATE", "near_identical_extent"
    if features["intersection_over_smaller"] >= config.nested_containment:
        return "NESTED_COMPONENT", "directional_containment"
    if (
        same_class
        and features["horizontal_overlap"] >= 0.5
        and features["text_relation"] == "different"
    ):
        return "COMPLEMENTARY_FRAGMENT", "overlapping_unique_text"
    if {a.get("type"), b.get("type")} & {
        "Table",
        "Figure",
        "Footnote",
        "Text",
        "Section-header",
    }:
        if a.get("type") != b.get("type"):
            return "CROSS_ROLE_BOUNDARY_OVERLAP", "different_semantic_classes"
    if features["intersection_area"] > 0:
        return "AMBIGUOUS", "overlap_without_duplicate_evidence"
    return "INDEPENDENT", "no_overlap"


def resolve_caption_overlaps(
    regions, pages, config: CaptionOverlapConfig | None = None
):
    """Analyze caption overlaps and collapse only high-certainty duplicates."""
    config = config or CaptionOverlapConfig()
    resolved = deepcopy(regions)
    if not config.enabled:
        return resolved, [], []
    page_map = {int(page["page_number"]): page for page in pages}
    by_page = defaultdict(list)
    for region in resolved:
        by_page[int(region["page_number"])].append(region)
    relationships = []
    duplicate_of: dict[str, str] = {}
    by_id = {str(r["layout_region_id"]): r for r in resolved}
    for page_number, page_regions in by_page.items():
        for index, a in enumerate(page_regions):
            for b in page_regions[index + 1 :]:
                if not (_is_caption_candidate(a) or _is_caption_candidate(b)):
                    continue
                features = overlap_features(
                    a, b, page_map.get(page_number, {"page_number": page_number})
                )
                if features["intersection_area"] <= 0:
                    continue
                kind, reason = _relationship(a, b, features, config)
                relation = {
                    "left_region_id": str(a["layout_region_id"]),
                    "right_region_id": str(b["layout_region_id"]),
                    "page_number": page_number,
                    "kind": kind,
                    "reason": reason,
                    "features": features,
                    "left_raw_class": a.get("docling_label"),
                    "right_raw_class": b.get("docling_label"),
                    "left_score": a.get("score"),
                    "right_score": b.get("score"),
                    "left_bbox": list(a["bbox_px"]),
                    "right_bbox": list(b["bbox_px"]),
                    "status": "analyzed",
                }
                relationships.append(relation)
                if kind == "DUPLICATE":
                    # Prefer available text, then score, then stable source order.
                    source_order = {
                        str(region["layout_region_id"]): index
                        for index, region in enumerate(regions)
                    }

                    def quality(region):
                        return (
                            bool(_text(region)),
                            float(region.get("score") or 0.0),
                            -source_order[str(region["layout_region_id"])],
                        )

                    keep, drop = (a, b) if quality(a) >= quality(b) else (b, a)
                    keep_id, drop_id = str(keep["layout_region_id"]), str(
                        drop["layout_region_id"]
                    )
                    if keep_id not in duplicate_of and drop_id not in duplicate_of:
                        duplicate_of[drop_id] = keep_id
                        relation["status"] = "collapsed"
                        relation["canonical_region_id"] = keep_id
    output = []
    for region in resolved:
        region_id = str(region["layout_region_id"])
        if region_id in duplicate_of:
            continue
        sources = [region_id] + sorted(
            k for k, v in duplicate_of.items() if v == region_id
        )
        region["source_region_ids"] = sources
        region["resolution_action"] = (
            "clear_duplicate_collapsed" if len(sources) > 1 else "preserved"
        )
        output.append(region)
    suppressed = [by_id[region_id] for region_id in duplicate_of]
    return output, relationships, suppressed


def build_caption_groups(regions, logical_tables, relationships, pages, config=None):
    """Create role-aware caption groups after table-context association."""
    config = config or CaptionOverlapConfig()
    by_id = {str(region["layout_region_id"]): region for region in regions}
    relation_by_pair = {
        frozenset((r["left_region_id"], r["right_region_id"])): r for r in relationships
    }
    page_map = {int(page["page_number"]): page for page in pages}
    groups = []
    for table in logical_tables:
        identifier_ids = list(dict.fromkeys(table.get("identifier_region_ids", [])))
        caption_ids = list(dict.fromkeys(table.get("caption_region_ids", [])))
        member_ids = list(dict.fromkeys(identifier_ids + caption_ids))
        group_relations = []
        for i, left in enumerate(member_ids):
            for right in member_ids[i + 1 :]:
                relation = relation_by_pair.get(frozenset((left, right)))
                if relation:
                    contextual = dict(relation)
                    if contextual["kind"] == "NESTED_COMPONENT":
                        contextual["status"] = "preserved_as_nested_component"
                    elif contextual["kind"] == "AMBIGUOUS":
                        contextual["status"] = "kept_ambiguous"
                    group_relations.append(contextual)
                else:
                    features = overlap_features(
                        by_id[left], by_id[right], page_map[int(table["page_number"])]
                    )
                    if (
                        features["horizontal_overlap"] >= 0.5
                        and features["vertical_gap_page_ratio"]
                        <= config.fragment_max_gap_page_ratio
                        and features["text_relation"] == "different"
                    ):
                        group_relations.append(
                            {
                                "left_region_id": left,
                                "right_region_id": right,
                                "page_number": table["page_number"],
                                "kind": "COMPLEMENTARY_FRAGMENT",
                                "reason": "contextual_caption_continuity",
                                "features": features,
                                "status": "grouped",
                            }
                        )
        ordered = sorted(
            member_ids,
            key=lambda rid: (
                int(by_id[rid].get("layout_reading_order") or 10**9),
                float(by_id[rid]["bbox_px"][1]),
                float(by_id[rid]["bbox_px"][0]),
            ),
        )
        # A region listed as both identifier and caption emits once.
        groups.append(
            {
                "resolved_region_id": f"{table['internal_id']}:caption",
                "page_number": table["page_number"],
                "parent_table_id": table["internal_id"],
                "parent_table_region_id": table["table_region_id"],
                "role": "table_caption",
                "identifier_region_ids": identifier_ids,
                "caption_fragment_region_ids": caption_ids,
                "ordered_source_region_ids": ordered,
                "semantic_text_region_ids": ordered,
                "source_region_ids": [
                    sid
                    for rid in ordered
                    for sid in by_id[rid].get("source_region_ids", [rid])
                ],
                "relationships": group_relations,
                "resolution": "context_aware_caption_group",
                "status": (
                    "ambiguous"
                    if any(r["kind"] == "AMBIGUOUS" for r in group_relations)
                    else "resolved"
                ),
            }
        )
    return groups
