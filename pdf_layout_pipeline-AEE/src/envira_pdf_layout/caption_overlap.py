"""Conservative overlap analysis for caption-related layout regions.

Raw and filtered regions are never mutated.  This module collapses only
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
_TEXT_LIKE_TYPES = {"Caption", "Text", "Footnote", "Section-header", "Title", "List"}
_ASSET_TYPES = {"Table", "Figure"}


def _text(region: LayoutRegion) -> str:
    return " ".join(str(region.get("text") or region.get("orig") or "").split())


def _normalized_text(region: LayoutRegion) -> str:
    return re.sub(r"\W+", " ", _text(region).casefold()).strip()


def _tokens(region: LayoutRegion) -> list[str]:
    return _normalized_text(region).split()


def _caption_like(region: LayoutRegion) -> bool:
    return _is_caption_candidate(region) or region.get("type") in {"Caption"}


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
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    set_a, set_b = set(tokens_a), set(tokens_b)
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
        "a_token_coverage": len(set_a & set_b) / len(set_a) if set_a else 0.0,
        "b_token_coverage": len(set_a & set_b) / len(set_b) if set_b else 0.0,
        "token_jaccard": (
            len(set_a & set_b) / len(set_a | set_b) if set_a | set_b else 0.0
        ),
        "center_distance_page_ratio": (
            (
                (((ab[0] + ab[2]) - (bb[0] + bb[2])) / (2 * width)) ** 2
                + (((ab[1] + ab[3]) - (bb[1] + bb[3])) / (2 * height)) ** 2
            )
            ** 0.5
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


def _compatible_text_roles(a, b) -> bool:
    """Whether two text boxes can be alternate representations of one object."""
    types = {a.get("type"), b.get("type")}
    if len(types) == 1:
        return True
    return types <= _TEXT_LIKE_TYPES and (
        _caption_like(a) or _caption_like(b) or features_text_equivalent(a, b)
    )


def features_text_equivalent(a, b) -> bool:
    left, right = _normalized_text(a), _normalized_text(b)
    return bool(left and right and left == right)


def _text_representative(a: LayoutRegion, b: LayoutRegion) -> tuple[str, str] | None:
    """Return ``(covered, representative)`` when one item's text subsumes another."""
    left, right = _normalized_text(a), _normalized_text(b)
    if not left or not right:
        return None
    left_id, right_id = str(a["layout_region_id"]), str(b["layout_region_id"])
    if left == right:
        return None  # Exact alternatives are handled by duplicate canonicalization.
    if left in right:
        return left_id, right_id
    if right in left:
        return right_id, left_id
    return None


def _relationship(a, b, features, config):
    same_class = a.get("type") == b.get("type")
    compatible_roles = _compatible_text_roles(a, b)
    duplicate_geometry = (
        features["iou"] >= config.duplicate_iou
        and features["area_ratio"] >= config.duplicate_area_ratio
        and features["edge_delta_page_ratio"] <= config.duplicate_edge_page_ratio
    )
    text_supports_duplicate = features["text_relation"] in {"equal", "unavailable"}
    if compatible_roles and duplicate_geometry and text_supports_duplicate:
        return "DUPLICATE", "near_identical_extent"
    # Unique, aligned text fragments take precedence over containment. A long
    # line box can be geometrically contained in a merged caption while still
    # contributing text that the merged item does not contain.
    if (
        compatible_roles
        and features["horizontal_overlap"] >= 0.5
        and features["text_relation"] == "different"
    ):
        return "COMPLEMENTARY_FRAGMENT", "overlapping_unique_text"
    if features["intersection_over_smaller"] >= config.nested_containment:
        return "NESTED_COMPONENT", "directional_containment"
    types = {a.get("type"), b.get("type")}
    if types & _ASSET_TYPES and types & _TEXT_LIKE_TYPES:
        smaller_height = min(
            float(a["bbox_px"][3] - a["bbox_px"][1]),
            float(b["bbox_px"][3] - b["bbox_px"][1]),
        )
        penetration = min(
            max(0.0, float(a["bbox_px"][3]) - float(b["bbox_px"][1])),
            max(0.0, float(b["bbox_px"][3]) - float(a["bbox_px"][1])),
        )
        if (
            smaller_height
            and penetration / smaller_height <= config.boundary_overlap_ratio
        ):
            return "BOUNDARY_TOUCH", "limited_cross_role_penetration"
        return "CROSS_ROLE_BOUNDARY_OVERLAP", "different_semantic_classes"
    if not same_class:
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
    duplicate_edges: list[tuple[str, str]] = []
    by_id = {str(r["layout_region_id"]): r for r in resolved}
    for page_number, page_regions in by_page.items():
        for index, a in enumerate(page_regions):
            for b in page_regions[index + 1 :]:
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
                if kind == "NESTED_COMPONENT":
                    a_inside = features["a_containment"] >= features["b_containment"]
                    relation["parent_region_id"] = str(
                        b["layout_region_id"] if a_inside else a["layout_region_id"]
                    )
                    relation["child_region_id"] = str(
                        a["layout_region_id"] if a_inside else b["layout_region_id"]
                    )
                    relation["status"] = "preserved_as_nested_component"
                elif kind in {"BOUNDARY_TOUCH", "COMPLEMENTARY_FRAGMENT"}:
                    relation["status"] = "preserved_for_grouping"
                representative = _text_representative(a, b)
                if (
                    kind != "DUPLICATE"
                    and representative
                    and _compatible_text_roles(a, b)
                ):
                    covered_id, representative_id = representative
                    relation["semantic_covered_region_id"] = covered_id
                    relation["semantic_representative_region_id"] = representative_id
                    relation["status"] = "preserved_without_duplicate_emission"
                relationships.append(relation)
                if kind == "DUPLICATE":
                    duplicate_edges.append(
                        (str(a["layout_region_id"]), str(b["layout_region_id"]))
                    )

    # Resolve duplicate connected components in one deterministic pass. This
    # avoids order-dependent A/B/C chains and always points provenance directly
    # at the final canonical region.
    parent = {region_id: region_id for region_id in by_id}

    def find(region_id):
        while parent[region_id] != region_id:
            parent[region_id] = parent[parent[region_id]]
            region_id = parent[region_id]
        return region_id

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in duplicate_edges:
        union(left, right)
    components = defaultdict(list)
    for region_id in by_id:
        components[find(region_id)].append(region_id)
    source_order = {
        str(region["layout_region_id"]): index for index, region in enumerate(regions)
    }

    def quality(region_id):
        region = by_id[region_id]
        return (
            bool(_text(region)),
            len(_normalized_text(region)),
            float(region.get("score") or 0.0),
            -source_order[region_id],
        )

    duplicate_of: dict[str, str] = {}
    for members in components.values():
        if len(members) < 2:
            continue
        canonical = max(members, key=quality)
        for member in members:
            if member != canonical:
                duplicate_of[member] = canonical
    for relation in relationships:
        if relation["kind"] != "DUPLICATE":
            continue
        canonical = duplicate_of.get(
            relation["left_region_id"],
            duplicate_of.get(relation["right_region_id"], relation["left_region_id"]),
        )
        relation["status"] = "collapsed"
        relation["canonical_region_id"] = canonical
    output = []
    relations_by_id = defaultdict(list)
    for relation in relationships:
        relations_by_id[relation["left_region_id"]].append(relation)
        relations_by_id[relation["right_region_id"]].append(relation)
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
        region["emission_policy"] = "emit_canonical"
        nested_parents = sorted(
            {
                relation["parent_region_id"]
                for relation in relations_by_id[region_id]
                if relation.get("kind") == "NESTED_COMPONENT"
                and relation.get("child_region_id") == region_id
            }
        )
        if nested_parents:
            region["nested_parent_region_ids"] = nested_parents
            # Preserve the region and its text, but tell flattened consumers that
            # hierarchy-aware emission is preferable to treating it as a peer.
            region["emission_policy"] = "emit_as_nested_child"
        semantic_representatives = sorted(
            {
                relation["semantic_representative_region_id"]
                for relation in relations_by_id[region_id]
                if relation.get("semantic_covered_region_id") == region_id
            }
        )
        if semantic_representatives:
            region["semantic_duplicate_of_region_ids"] = semantic_representatives
            region["emission_policy"] = "suppress_duplicate_text_emission"
        output.append(region)
    resolved_by_page = defaultdict(list)
    for region in output:
        resolved_by_page[int(region["page_number"])].append(region)
    for page_regions in resolved_by_page.values():
        page_regions.sort(
            key=lambda region: (
                int(region.get("layout_reading_order") or 10**9),
                float(region["bbox_px"][1]),
                float(region["bbox_px"][0]),
            )
        )
        for order, region in enumerate(page_regions, 1):
            region["resolved_reading_order"] = order
    suppressed = [by_id[region_id] for region_id in duplicate_of]
    return output, relationships, suppressed


def build_caption_groups(regions, logical_tables, relationships, pages, config=None):
    """Create table-aware and standalone semantic caption groups."""
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
        covered_ids = {
            relation["semantic_covered_region_id"]
            for relation in group_relations
            if relation.get("semantic_covered_region_id") in member_ids
            and relation.get("semantic_representative_region_id") in member_ids
        }
        for left_index, left_id in enumerate(ordered):
            left_text = _normalized_text(by_id[left_id])
            if not left_text:
                continue
            for right_id in ordered[left_index + 1 :]:
                right_text = _normalized_text(by_id[right_id])
                if not right_text:
                    continue
                if left_text == right_text:
                    covered_ids.add(right_id)
                elif left_text in right_text:
                    covered_ids.add(left_id)
                elif right_text in left_text:
                    covered_ids.add(right_id)
        semantic_ids = [
            region_id for region_id in ordered if region_id not in covered_ids
        ]
        source_boxes = [
            list(map(float, by_id[region_id]["bbox_px"])) for region_id in ordered
        ]
        union_bbox = (
            [
                min(box[0] for box in source_boxes),
                min(box[1] for box in source_boxes),
                max(box[2] for box in source_boxes),
                max(box[3] for box in source_boxes),
            ]
            if source_boxes
            else None
        )

        # Create one consumer-facing caption string. Source fragments and their
        # geometry remain separate, but overlapping boundary tokens are emitted
        # once (for example, "Table 3" plus "Table 3. Stalk yield ...").
        semantic_tokens: list[str] = []
        for region_id in semantic_ids:
            fragment_tokens = _text(by_id[region_id]).split()
            if not fragment_tokens:
                continue
            normalized_existing = [
                re.sub(r"\W+", "", t.casefold()) for t in semantic_tokens
            ]
            normalized_fragment = [
                re.sub(r"\W+", "", token.casefold()) for token in fragment_tokens
            ]
            max_overlap = min(len(normalized_existing), len(normalized_fragment))
            overlap = next(
                (
                    size
                    for size in range(max_overlap, 0, -1)
                    if normalized_existing[-size:] == normalized_fragment[:size]
                ),
                0,
            )
            semantic_tokens.extend(fragment_tokens[overlap:])
        # A region listed as both identifier and caption emits once.
        groups.append(
            {
                "resolved_region_id": f"{table['internal_id']}:caption",
                "page_number": table["page_number"],
                "parent_table_id": table["internal_id"],
                "parent_table_region_id": table["table_region_id"],
                "role": "table_caption",
                "type": "Table Caption",
                "bbox_px": union_bbox,
                "identifier_region_ids": identifier_ids,
                "caption_fragment_region_ids": caption_ids,
                "ordered_source_region_ids": ordered,
                "semantic_text_region_ids": semantic_ids,
                "text": " ".join(semantic_tokens).strip(),
                "source_region_ids": [
                    sid
                    for rid in ordered
                    for sid in by_id[rid].get("source_region_ids", [rid])
                ],
                "children": [
                    {
                        "region_id": region_id,
                        "semantic_role": (
                            "table_caption_identifier"
                            if region_id in identifier_ids
                            else "table_caption_fragment"
                        ),
                        "source_type": by_id[region_id].get("type"),
                        "source_bbox_px": list(by_id[region_id]["bbox_px"]),
                        "detector_score": by_id[region_id].get("score"),
                    }
                    for region_id in ordered
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
    grouped = {
        str(region_id)
        for group in groups
        for region_id in group["ordered_source_region_ids"]
    }
    parent_by_child = {
        str(relation.get("child_region_id")): str(relation.get("parent_region_id"))
        for relation in relationships
        if relation.get("child_region_id") and relation.get("parent_region_id")
    }
    for region in regions:
        region_id = str(region["layout_region_id"])
        if region.get("type") != "Caption" or region_id in grouped:
            continue
        parent_id = parent_by_child.get(region_id)
        parent = by_id.get(parent_id) if parent_id else None
        groups.append(
            {
                "resolved_region_id": f"{region_id}:caption",
                "page_number": region["page_number"],
                "parent_table_id": None,
                "parent_table_region_id": None,
                "parent_region_id": parent_id,
                "role": f"{str((parent or {}).get('type', 'unattached')).lower()}_caption",
                "type": "Caption",
                "bbox_px": list(region["bbox_px"]),
                "identifier_region_ids": [],
                "caption_fragment_region_ids": [region_id],
                "ordered_source_region_ids": [region_id],
                "semantic_text_region_ids": [region_id],
                "text": _text(region),
                "source_region_ids": region.get("source_region_ids", [region_id]),
                "children": [
                    {
                        "region_id": region_id,
                        "semantic_role": "caption_fragment",
                        "source_type": region.get("type"),
                        "source_bbox_px": list(region["bbox_px"]),
                        "detector_score": region.get("score"),
                    }
                ],
                "relationships": [],
                "resolution": "standalone_caption_group",
                "status": "resolved" if parent_id else "unattached",
            }
        )
    return groups
