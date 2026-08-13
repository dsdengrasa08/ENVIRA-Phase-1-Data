"""General, provenance-preserving layout relationship resolution.

The resolver deliberately separates observations (immutable source geometry),
relationship classification, and emission actions.  It is class-family driven:
unknown detector labels therefore receive the same conservative treatment as
known labels instead of falling through a destructive special case.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Iterable

from .config import ContainmentConfig, OverlapResolutionConfig
from .geometry import bbox_area, intersection_area
from .types import LayoutRegion


TEXT_FAMILY = {
    "Caption",
    "Text",
    "Footnote",
    "Section-header",
    "Title",
    "List",
    "Reference",
    "Page-header",
    "Page-footer",
    "Code",
}
ASSET_FAMILY = {"Table", "Figure"}
FORMULA_FAMILY = {"Formula", "Equation"}
FURNITURE_FAMILY = {"Page-header", "Page-footer", "Page-number"}


def class_family(region: LayoutRegion) -> str:
    """Return an extensible semantic family with a conservative fallback."""
    kind = str(region.get("type") or "Unknown")
    if kind in ASSET_FAMILY:
        return "asset"
    if kind in FORMULA_FAMILY:
        return "formula"
    if kind in FURNITURE_FAMILY:
        return "furniture"
    if kind in TEXT_FAMILY:
        return "text"
    return "unknown"


def _text(region: LayoutRegion) -> str:
    return " ".join(str(region.get("text") or region.get("orig") or "").split())


def _normalized_text(region: LayoutRegion) -> str:
    return re.sub(r"\W+", " ", _text(region).casefold()).strip()


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def overlap_features(
    a: LayoutRegion, b: LayoutRegion, page: dict[str, Any]
) -> dict[str, Any]:
    """Compute symmetric and directional geometric and semantic evidence."""
    ab, bb = tuple(map(float, a["bbox_px"])), tuple(map(float, b["bbox_px"]))
    area_a, area_b = bbox_area(ab), bbox_area(bb)
    intersection = intersection_area(ab, bb)
    union = area_a + area_b - intersection
    width, height = _page_size(page)
    aw, ah = max(0.0, ab[2] - ab[0]), max(0.0, ab[3] - ab[1])
    bw, bh = max(0.0, bb[2] - bb[0]), max(0.0, bb[3] - bb[1])
    iw = max(0.0, min(ab[2], bb[2]) - max(ab[0], bb[0]))
    ih = max(0.0, min(ab[3], bb[3]) - max(ab[1], bb[1]))
    ta, tb = _normalized_text(a), _normalized_text(b)
    sa, sb = set(ta.split()), set(tb.split())
    if ta and tb:
        text_relation = (
            "equal"
            if ta == tb
            else "a_in_b"
            if ta in tb
            else "b_in_a"
            if tb in ta
            else "different"
        )
    else:
        text_relation = "unavailable"
    ac = ((ab[0] + ab[2]) / 2, (ab[1] + ab[3]) / 2)
    bc = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    return {
        "intersection_area": intersection,
        "iou": intersection / union if union else 0.0,
        "a_containment": intersection / area_a if area_a else 0.0,
        "b_containment": intersection / area_b if area_b else 0.0,
        "intersection_over_smaller": intersection / min(area_a, area_b)
        if min(area_a, area_b)
        else 0.0,
        "intersection_over_larger": intersection / max(area_a, area_b)
        if max(area_a, area_b)
        else 0.0,
        "a_horizontal_coverage": iw / aw if aw else 0.0,
        "b_horizontal_coverage": iw / bw if bw else 0.0,
        "horizontal_overlap": iw / min(aw, bw) if min(aw, bw) else 0.0,
        "a_vertical_coverage": ih / ah if ah else 0.0,
        "b_vertical_coverage": ih / bh if bh else 0.0,
        "vertical_overlap": ih / min(ah, bh) if min(ah, bh) else 0.0,
        "area_ratio": min(area_a, area_b) / max(area_a, area_b)
        if max(area_a, area_b)
        else 0.0,
        "a_center_inside_b": bb[0] <= ac[0] <= bb[2] and bb[1] <= ac[1] <= bb[3],
        "b_center_inside_a": ab[0] <= bc[0] <= ab[2] and ab[1] <= bc[1] <= ab[3],
        "a_token_coverage": len(sa & sb) / len(sa) if sa else 0.0,
        "b_token_coverage": len(sa & sb) / len(sb) if sb else 0.0,
        "token_jaccard": len(sa & sb) / len(sa | sb) if sa | sb else 0.0,
        "center_distance_page_ratio": (
            ((ac[0] - bc[0]) / width) ** 2 + ((ac[1] - bc[1]) / height) ** 2
        )
        ** 0.5,
        "edge_delta_page_ratio": max(
            abs(ab[0] - bb[0]) / width,
            abs(ab[2] - bb[2]) / width,
            abs(ab[1] - bb[1]) / height,
            abs(ab[3] - bb[3]) / height,
        ),
        "horizontal_gap_page_ratio": max(0.0, max(ab[0], bb[0]) - min(ab[2], bb[2]))
        / width,
        "vertical_gap_page_ratio": max(0.0, max(ab[1], bb[1]) - min(ab[3], bb[3]))
        / height,
        "left_alignment_page_ratio": abs(ab[0] - bb[0]) / width,
        "right_alignment_page_ratio": abs(ab[2] - bb[2]) / width,
        "text_relation": text_relation,
        "same_class": a.get("type") == b.get("type"),
        "left_family": class_family(a),
        "right_family": class_family(b),
    }


def _candidate_pairs(
    regions: list[LayoutRegion], page_height: float, near_ratio: float
) -> Iterable[tuple[LayoutRegion, LayoutRegion]]:
    """Sweep-line candidate generation for intersecting and nearby fragments."""
    margin = max(0.0, page_height * near_ratio)
    ordered = sorted(
        regions, key=lambda r: (float(r["bbox_px"][1]), float(r["bbox_px"][0]))
    )
    active: list[LayoutRegion] = []
    for region in ordered:
        top = float(region["bbox_px"][1])
        active = [item for item in active if float(item["bbox_px"][3]) + margin >= top]
        for item in active:
            yield item, region
        active.append(region)


def _compatible_duplicate_roles(
    a: LayoutRegion, b: LayoutRegion, f: dict[str, Any]
) -> bool:
    if f["same_class"]:
        return True
    families = {f["left_family"], f["right_family"]}
    return families <= {"text"} and f["text_relation"] == "equal"


def _classify(
    a: LayoutRegion,
    b: LayoutRegion,
    f: dict[str, Any],
    config: OverlapResolutionConfig,
    containment: ContainmentConfig,
) -> tuple[str, str, str]:
    duplicate_geometry = (
        f["iou"] >= config.duplicate_iou
        and f["area_ratio"] >= config.duplicate_area_ratio
        and f["edge_delta_page_ratio"] <= config.duplicate_edge_page_ratio
    )
    if (
        duplicate_geometry
        and _compatible_duplicate_roles(a, b, f)
        and f["text_relation"] in {"equal", "unavailable"}
    ):
        return "DUPLICATE", "near_identical_extent", "canonicalize"
    if duplicate_geometry and not f["same_class"]:
        return "CLASS_CONFLICT", "near_identical_extent_different_class", "flag"
    center_containment = (
        f["a_containment"] >= containment.center_child_coverage
        and f["a_center_inside_b"]
    ) or (
        f["b_containment"] >= containment.center_child_coverage
        and f["b_center_inside_a"]
    )
    if (
        f["intersection_over_smaller"] >= containment.strong_child_coverage
        or center_containment
    ):
        return "CONTAINMENT_CANDIDATE", "directional_containment_observed", "observe"
    if f["intersection_area"] > 0:
        families = {f["left_family"], f["right_family"]}
        smaller_h = min(
            float(a["bbox_px"][3]) - float(a["bbox_px"][1]),
            float(b["bbox_px"][3]) - float(b["bbox_px"][1]),
        )
        penetration = min(
            max(0.0, float(a["bbox_px"][3]) - float(b["bbox_px"][1])),
            max(0.0, float(b["bbox_px"][3]) - float(a["bbox_px"][1])),
        )
        if (
            "asset" in families
            and penetration / max(1.0, smaller_h) <= config.boundary_overlap_ratio
        ):
            return "ACCIDENTAL_INTERSECTION", "limited_boundary_penetration", "retain"
        if not f["same_class"]:
            return "CLASS_CONFLICT", "material_cross_role_overlap", "flag"
        return "AMBIGUOUS_OVERLAP", "overlap_without_duplicate_evidence", "flag"
    text_like = {f["left_family"], f["right_family"]} <= {"text"}
    aligned = f["horizontal_overlap"] >= config.fragment_horizontal_overlap
    near = f["vertical_gap_page_ratio"] <= config.fragment_max_gap_page_ratio
    if text_like and aligned and near and f["text_relation"] == "different":
        return "FRAGMENT_CANDIDATE", "aligned_nearby_unique_text", "retain"
    return "INDEPENDENT", "no_material_relationship", "retain"


@dataclass
class ResolutionResult:
    regions: list[LayoutRegion]
    relationships: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    suppressed: list[LayoutRegion]
    diagnostics: dict[str, Any]


def resolve_layout_overlaps(
    regions,
    pages,
    config: OverlapResolutionConfig | None = None,
    containment: ContainmentConfig | None = None,
) -> ResolutionResult:
    """Resolve a page graph while retaining immutable source geometry and audit data."""
    config = config or OverlapResolutionConfig()
    containment = containment or ContainmentConfig()
    working = deepcopy(regions)
    for region in working:
        region.setdefault("source_region_ids", [str(region["layout_region_id"])])
        region.setdefault("source_bbox_px", list(region["bbox_px"]))
        region.setdefault("resolved_bbox_px", list(region["bbox_px"]))
        region.setdefault("resolution_action", "preserved")
        region.setdefault("emission_policy", "emit_canonical")
        region.setdefault("geometry_version", 1)
    if not config.enabled:
        return ResolutionResult(
            working, [], [], [], {"candidate_pairs": 0, "pairs_scored": 0}
        )
    page_map = {int(p["page_number"]): p for p in pages}
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in working:
        by_page[int(region["page_number"])].append(region)
    relationships: list[dict[str, Any]] = []
    duplicate_edges: list[tuple[str, str]] = []
    candidate_pairs = 0
    pairs_scored = 0
    by_id = {str(r["layout_region_id"]): r for r in working}
    for page_number, page_regions in by_page.items():
        page = page_map.get(page_number, {"page_number": page_number})
        _, height = _page_size(page)
        for a, b in _candidate_pairs(
            page_regions, height, config.fragment_max_gap_page_ratio
        ):
            candidate_pairs += 1
            f = overlap_features(a, b, page)
            pairs_scored += 1
            kind, reason, proposed_action = _classify(a, b, f, config, containment)
            if kind == "INDEPENDENT":
                continue
            left, right = str(a["layout_region_id"]), str(b["layout_region_id"])
            relation: dict[str, Any] = {
                "relationship_id": f"p{page_number}:{left}:{right}",
                "left_region_id": left,
                "right_region_id": right,
                "page_number": page_number,
                "kind": kind,
                "reason": reason,
                "proposed_action": proposed_action,
                "status": "observed",
                "features": f,
                "left_class": a.get("type"),
                "right_class": b.get("type"),
                "left_raw_class": a.get("docling_label"),
                "right_raw_class": b.get("docling_label"),
                "left_score": a.get("score"),
                "right_score": b.get("score"),
                "left_bbox": list(a["bbox_px"]),
                "right_bbox": list(b["bbox_px"]),
            }
            if kind == "DUPLICATE":
                duplicate_edges.append((left, right))
            elif kind == "CONTAINMENT_CANDIDATE":
                a_inside = f["a_containment"] >= f["b_containment"]
                relation["candidate_parent_region_id"] = right if a_inside else left
                relation["candidate_child_region_id"] = left if a_inside else right
                relation["status"] = "observed_for_hierarchy_validation"
            elif kind in {"CLASS_CONFLICT", "AMBIGUOUS_OVERLAP"}:
                relation["status"] = "unresolved_conflict"
            else:
                relation["status"] = "preserved"
            relationships.append(relation)

    # Duplicate components are accepted only when every member pair satisfies
    # the duplicate rule.  This complete-link guard prevents transitive drift.
    parent = {rid: rid for rid in by_id}

    def find(rid):
        while parent[rid] != rid:
            parent[rid] = parent[parent[rid]]
            rid = parent[rid]
        return rid

    for left, right in duplicate_edges:
        lr, rr = find(left), find(right)
        if lr != rr:
            parent[rr] = lr
    components: dict[str, list[str]] = defaultdict(list)
    for rid in by_id:
        components[find(rid)].append(rid)
    duplicate_pairs = {frozenset(edge) for edge in duplicate_edges}
    accepted_components = []
    for members in components.values():
        if len(members) > 1 and all(
            frozenset((a, b)) in duplicate_pairs
            for i, a in enumerate(members)
            for b in members[i + 1 :]
        ):
            accepted_components.append(members)
    source_order = {str(r["layout_region_id"]): i for i, r in enumerate(working)}

    def quality(rid):
        r = by_id[rid]
        score = r.get("score")
        return (
            bool(_text(r)),
            len(_normalized_text(r)),
            score is not None,
            float(score) if score is not None else 0.0,
            -source_order[rid],
        )

    duplicate_of: dict[str, str] = {}
    decisions: list[dict[str, Any]] = []
    for members in accepted_components:
        canonical = max(members, key=quality)
        for member in members:
            if member != canonical:
                duplicate_of[member] = canonical
        decisions.append(
            {
                "action": "canonicalize",
                "canonical_region_id": canonical,
                "source_region_ids": sorted(members),
                "reason": "complete_link_duplicate_component",
                "confidence": "high",
            }
        )
    relation_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rel in relationships:
        relation_by_id[rel["left_region_id"]].append(rel)
        relation_by_id[rel["right_region_id"]].append(rel)
        if rel["kind"] == "DUPLICATE":
            canonical = duplicate_of.get(
                rel["left_region_id"], duplicate_of.get(rel["right_region_id"])
            )
            if canonical:
                rel.update(status="collapsed", canonical_region_id=canonical)
            else:
                rel.update(
                    status="retained_nontransitive_duplicate_chain",
                    proposed_action="flag",
                )
    output = []
    for region in working:
        rid = str(region["layout_region_id"])
        if rid in duplicate_of:
            continue
        sources = [rid] + sorted(
            member for member, canonical in duplicate_of.items() if canonical == rid
        )
        region["source_region_ids"] = list(
            dict.fromkeys(region["source_region_ids"] + sources)
        )
        if len(sources) > 1:
            region["resolution_action"] = "clear_duplicate_collapsed"
        conflicts = sorted(
            rel["relationship_id"]
            for rel in relation_by_id[rid]
            if rel["status"] == "unresolved_conflict"
        )
        if conflicts:
            region["unresolved_conflict_ids"] = conflicts
            region["resolution_status"] = "ambiguous"
        else:
            region["resolution_status"] = "resolved"
        output.append(region)
    # Stable provisional order only; hierarchy owns child emission and local order.
    out_pages: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in output:
        out_pages[int(region["page_number"])].append(region)
    for page_regions in out_pages.values():
        page_regions.sort(
            key=lambda r: (
                int(r.get("layout_reading_order") or 10**9),
                float(r["bbox_px"][1]),
                float(r["bbox_px"][0]),
            )
        )
        top_order = 0
        for region in page_regions:
            top_order += 1
            region["resolved_reading_order"] = top_order
    suppressed = [deepcopy(by_id[rid]) for rid in duplicate_of]
    return ResolutionResult(
        output,
        relationships,
        decisions,
        suppressed,
        {
            "candidate_pairs": candidate_pairs,
            "pairs_scored": pairs_scored,
            "relationships_emitted": len(relationships),
            "duplicate_edges": len(duplicate_edges),
        },
    )


def associate_attachable_context(
    regions, pages, *, ambiguity_margin: float = 0.15
) -> list[dict[str, Any]]:
    """Compatibility wrapper for the authoritative caption-association stage."""
    from .caption_association import associate_captions
    from .config import CaptionAssociationConfig

    return associate_captions(
        regions,
        pages,
        config=CaptionAssociationConfig(ambiguity_margin=ambiguity_margin),
    )
