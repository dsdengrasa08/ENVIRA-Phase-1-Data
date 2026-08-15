"""Infer logical table context without changing physical layout detections."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import re
from typing import Any

from .config import TableContextConfig
from .types import LayoutRegion
from .region_index import RegionIndex
from .orientation import (
    compatible_orientation,
    interval_overlap_ratio,
    local_relation,
    project_bbox,
    reliable_orientation_conflict,
    region_orientation,
)
from .semantic_caption import (
    body_reference_evidence,
    caption_reference_quality,
    find_table_reference_mention,
    leading_table_label_fragment,
    parse_fragmented_table_reference,
    parse_semantic_caption_reference,
)

_NOTE_RE = re.compile(
    r"^\s*(?:notes?|sources?)\s*:|^\s*(?:[*†‡]|[a-z])(?:[.)]|\s{1,3})\s+|"
    r"\b[pP]\s*[<=>]\s*\.?\d+",
    re.IGNORECASE,
)
_TABLE_NOTE_TEXT_RE = re.compile(
    r"^(?:[a-z*†‡][.)]?\s+)?(?:see\s+table\b|means?\s+(?:within|followed)\b|"
    r"values?\s+in\s+parentheses\b|treatment\s+codes?\b)",
    re.IGNORECASE,
)
_BODY_SENTENCE_RE = re.compile(r"^[A-Z][^.!?]{35,}[.!?](?:\s|$)")
_NEW_OBJECT_RE = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|equation|eq\.?|algorithm|listing)\s+\w+",
    re.IGNORECASE,
)
_TEXT_TYPES = {"Text", "Caption", "Footnote", "Section-header", "Title", "List"}
_FRAGMENT_TYPES = {"Text", "Caption", "List"}
_BOUNDARY_TYPES = {"Table", "Figure", "Section-header", "Title"}


def _table_reference(text: Any, *, tolerant: bool = False):
    reference = parse_semantic_caption_reference(text, allow_ocr_tolerance=tolerant)
    return reference if reference and reference.kind == "table" else None


def _explicit_other_asset_reference(text: Any) -> str | None:
    """Return a leading non-table caption kind that must not seed a table caption."""
    reference = parse_semantic_caption_reference(text)
    return reference.kind if reference and reference.kind != "table" else None


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _vertical_overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap / max(1.0, min(a[3] - a[1], b[3] - b[1]))


def _intersection_area(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _column_compatible(
    candidate: LayoutRegion, table: LayoutRegion, page_width: float
) -> bool:
    candidate_column = candidate.get("reading_order_column")
    table_column = table.get("reading_order_column")
    table_width = float(table["bbox_px"][2] - table["bbox_px"][0]) / page_width
    candidate_width = (
        float(candidate["bbox_px"][2] - candidate["bbox_px"][0]) / page_width
    )
    if table_width >= 0.72 or candidate_width >= 0.72:
        return True
    if (
        not candidate_column
        or not table_column
        or "single" in {candidate_column, table_column}
    ):
        return True
    return candidate_column == table_column


def _has_blocker(
    candidate: LayoutRegion, table: LayoutRegion, page_regions: list[LayoutRegion]
) -> str | None:
    cb, tb = candidate["bbox_px"], table["bbox_px"]
    candidate_center = (float(cb[1]) + float(cb[3])) / 2.0
    table_center = (float(tb[1]) + float(tb[3])) / 2.0
    top, bottom = (
        sorted((float(cb[3]), float(tb[1])))
        if candidate_center <= table_center
        else sorted((float(tb[3]), float(cb[1])))
    )
    for region in page_regions:
        if region is candidate or region is table:
            continue
        rb = region["bbox_px"]
        if (
            float(rb[1]) >= top
            and float(rb[3]) <= bottom
            and _overlap_ratio(list(map(float, rb)), list(map(float, tb))) >= 0.18
            and region.get("type") in _BOUNDARY_TYPES
        ):
            return str(region.get("layout_region_id"))
    return None


def _score_edge(
    candidate: LayoutRegion,
    table: LayoutRegion,
    role: str,
    page_regions: list[LayoutRegion],
    page_width: float,
    page_height: float,
    config: TableContextConfig,
) -> dict[str, Any] | None:
    cb, tb = list(map(float, candidate["bbox_px"])), list(map(float, table["bbox_px"]))
    tolerance = config.max_boundary_overlap_page_ratio * max(page_width, page_height)
    sides = {
        "above": (
            cb[3] <= tb[1] + tolerance,
            max(0.0, tb[1] - cb[3]),
            _overlap_ratio(cb, tb),
        ),
        "below": (
            cb[1] >= tb[3] - tolerance,
            max(0.0, cb[1] - tb[3]),
            _overlap_ratio(cb, tb),
        ),
        "left": (
            cb[2] <= tb[0] + tolerance,
            max(0.0, tb[0] - cb[2]),
            _vertical_overlap_ratio(cb, tb),
        ),
        "right": (
            cb[0] >= tb[2] - tolerance,
            max(0.0, cb[0] - tb[2]),
            _vertical_overlap_ratio(cb, tb),
        ),
    }
    possible = [(name, values) for name, values in sides.items() if values[0]]
    if not possible or candidate.get("type") not in _TEXT_TYPES:
        return None
    direction, (_, gap, overlap) = min(possible, key=lambda item: item[1][1])
    signed_gap = {
        "above": tb[1] - cb[3],
        "below": cb[1] - tb[3],
        "left": tb[0] - cb[2],
        "right": cb[0] - tb[2],
    }[direction]
    axis_size = page_height if direction in {"above", "below"} else page_width
    gap_page = gap / axis_size
    if gap_page > config.max_vertical_gap_page_ratio:
        return None
    if overlap < config.min_horizontal_overlap_ratio:
        return None
    # Page-column labels describe normal article flow and are unreliable for a
    # narrow caption running along a rotated table's long edge. Strong parallel
    # overlap on a left/right table-local side is sufficient column evidence.
    rotated_side_compatible = direction in {"left", "right"} and overlap >= 0.70
    if not rotated_side_compatible and not _column_compatible(
        candidate, table, page_width
    ):
        return None
    blocker = _has_blocker(candidate, table, page_regions)
    if blocker:
        return None

    text = str(candidate.get("text") or "").strip()
    orientation = region_orientation(candidate)
    other_asset_kind = _explicit_other_asset_reference(text)
    if role == "caption" and other_asset_kind:
        return None
    label_match = _table_reference(text, tolerant=True)
    reference_quality = caption_reference_quality(text, label_match)
    if role == "caption" and label_match and not reference_quality["authoritative"]:
        return None
    negative_reasons = [] if label_match else body_reference_evidence(text)
    note_match = _NOTE_RE.search(text)
    style = candidate.get("typography") or {}
    is_italic = bool(style.get("italic") or candidate.get("is_italic"))
    has_superscript = bool(style.get("superscript") or candidate.get("has_superscript"))
    order_delta = abs(
        int(
            candidate.get("layout_reading_order")
            or candidate.get("docling_reading_order")
            or 0
        )
        - int(
            table.get("layout_reading_order") or table.get("docling_reading_order") or 0
        )
    )
    direction_ok = role == "caption" or direction == "below"
    components = {
        "proximity": max(
            0.0, 2.4 * (1.0 - gap_page / config.max_vertical_gap_page_ratio)
        ),
        "horizontal_compatibility": 1.8 * overlap,
        "column_compatibility": 1.5,
        "reading_order": (
            1.2 if order_delta <= 2 else (0.5 if order_delta <= 4 else 0.0)
        ),
        "direction": 0.8 if direction_ok else (-0.4 if role == "caption" else -1.0),
        "raw_class": (
            2.0
            if role == "caption" and candidate.get("type") == "Caption"
            else 1.4 if role == "note" and candidate.get("type") == "Footnote" else 0.0
        ),
        "identifier_lexical": 1.8 if label_match and role == "caption" else 0.0,
        "note_lexical": 1.5 if note_match and role == "note" else 0.0,
        "body_paragraph_penalty": -3.2 if _BODY_SENTENCE_RE.search(text) else 0.0,
        "body_reference_penalty": -6.0 if negative_reasons else 0.0,
        "ocr_tolerance_penalty": (
            -0.5 if label_match and label_match.ocr_tolerant else 0.0
        ),
        "typography": (
            0.4 if (role == "note" and (is_italic or has_superscript)) else 0.0
        ),
    }
    score = sum(components.values())
    return {
        "table_region_id": table["layout_region_id"],
        "region_id": candidate["layout_region_id"],
        "proposed_role": role,
        "score": round(score, 4),
        "accepted": False,
        "direction": direction,
        "features": {
            "gap_page_ratio": round(gap_page, 6),
            "boundary_overlap_page_ratio": round(max(0.0, -signed_gap) / axis_size, 6),
            "horizontal_overlap_ratio": round(overlap, 6),
            "reading_order_delta": order_delta,
            "rotated_side_column_override": rotated_side_compatible,
            "orientation": orientation,
            "geometry_space": "page_axes_fallback",
            "components": components,
        },
        "printed_label": label_match.label if label_match else None,
        "printed_label_text": text[: label_match.end].strip() if label_match else None,
        "caption_text_after_label": bool(
            label_match and text[label_match.end :].strip()
        ),
        "semantic_reference": label_match.__dict__ if label_match else None,
        "semantic_reference_quality": reference_quality if label_match else None,
        "negative_reasons": negative_reasons,
    }


def _order(region: LayoutRegion) -> int:
    return int(
        region.get("resolved_reading_order")
        or region.get("layout_reading_order")
        or region.get("docling_reading_order")
        or 10**9
    )


def _fragment_edge(
    candidate: LayoutRegion,
    member: LayoutRegion,
    table: LayoutRegion,
    page_regions: list[LayoutRegion],
    page_width: float,
    page_height: float,
    config: TableContextConfig,
    relationship_kinds: set[str],
) -> dict[str, Any] | None:
    """Score one local caption-continuation edge.

    A fragment is admitted through a caption seed/component, rather than merely
    because it happens to be close to a table. This keeps the decision local and
    permits long captions whose first line is not itself close to the table.
    """
    if candidate.get("type") not in _FRAGMENT_TYPES:
        return None
    text = str(candidate.get("text") or "").strip()
    if (
        not text
        or _table_reference(text)
        or find_table_reference_mention(text)
        or _explicit_other_asset_reference(text)
        or _NEW_OBJECT_RE.match(text)
    ):
        return None
    cb = list(map(float, candidate["bbox_px"]))
    mb = list(map(float, member["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    member_orientation = region_orientation(member)
    angle = member_orientation["angle_degrees"]
    if (
        angle is not None
        and min(abs(angle % 180.0), abs((angle % 180.0) - 180.0)) > 12.0
    ):
        orientation_compatible = compatible_orientation(candidate, member)
        if not reliable_orientation_conflict(candidate, member):
            member_table = local_relation(mb, tb, angle)
            candidate_table = local_relation(cb, tb, angle)
            candidate_member = local_relation(cb, mb, angle)
            same_external_side = (
                member_table["side"] in {"before", "after"}
                and candidate_table["side"] == member_table["side"]
            )
            scale = max(1.0, (page_width**2 + page_height**2) ** 0.5)
            gap_page = float(candidate_member["gap"]) / scale
            alignment = float(candidate_member["overlap"])
            if (
                same_external_side
                and candidate_member["side"] is not None
                and gap_page <= config.fragment_max_gap_page_ratio
                and alignment >= config.fragment_min_horizontal_overlap
                and _intersection_area(cb, tb) == 0
                and not _has_blocker(candidate, member, page_regions)
            ):
                return {
                    "table_region_id": str(table["layout_region_id"]),
                    "region_id": str(candidate["layout_region_id"]),
                    "member_region_id": str(member["layout_region_id"]),
                    "proposed_role": "caption_fragment",
                    "score": round(5.2 + 1.8 * alignment - gap_page, 4),
                    "accepted": False,
                    "direction": "left" if member_table["side"] == "after" else "right",
                    "features": {
                        "geometry_space": "table_local_orientation",
                        "orientation": member_orientation,
                        "orientation_compatible": orientation_compatible,
                        "local_table_side": member_table["side"],
                        "local_fragment_relation": candidate_member["side"],
                        "gap_page_ratio": round(gap_page, 6),
                        "parallel_overlap_ratio": round(alignment, 6),
                        "relationship_kinds": sorted(relationship_kinds),
                    },
                }
    member_above = (mb[1] + mb[3]) / 2 < (tb[1] + tb[3]) / 2
    candidate_above = (cb[1] + cb[3]) / 2 < (tb[1] + tb[3]) / 2
    if member_above != candidate_above:
        return None
    # A caption component must remain on the table-facing side of the asset.
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    if member_above and cb[3] > tb[1] + tolerance:
        return None
    if not member_above and cb[1] < tb[3] - tolerance:
        return None
    if not _column_compatible(candidate, table, page_width):
        return None

    vertical_gap = max(0.0, max(cb[1], mb[1]) - min(cb[3], mb[3]))
    local_height = max(1.0, min(cb[3] - cb[1], mb[3] - mb[1]))
    gap_page = vertical_gap / page_height
    gap_lines = vertical_gap / local_height
    if (
        gap_page > config.fragment_max_gap_page_ratio
        or gap_lines > config.fragment_max_line_gap_ratio
    ):
        return None
    horizontal = _overlap_ratio(cb, mb)
    left_delta = abs(cb[0] - mb[0]) / page_width
    right_delta = abs(cb[2] - mb[2]) / page_width
    aligned = (
        horizontal >= config.fragment_min_horizontal_overlap
        or min(left_delta, right_delta) <= config.fragment_edge_alignment_page_ratio
    )
    if not aligned:
        return None
    blocker = _has_blocker(candidate, member, page_regions)
    if blocker:
        return None

    order_delta = abs(_order(candidate) - _order(member))
    style_a, style_b = candidate.get("typography") or {}, member.get("typography") or {}
    shared_style = bool(style_a and style_b) and all(
        style_a.get(key) == style_b.get(key)
        for key in ("font_family", "font_size", "italic", "bold")
        if key in style_a and key in style_b
    )
    punctuation_continuation = bool(
        text[:1].islower()
        or str(member.get("text") or "").rstrip().endswith((",", ";", ":", "(", "-"))
    )
    paragraph_penalty = 0.0
    if _BODY_SENTENCE_RE.search(text):
        paragraph_penalty -= 2.8
    if len(re.findall(r"[.!?](?:\s|$)", text)) > 1:
        paragraph_penalty -= 1.5
    components = {
        "local_proximity": 2.7
        * max(0.0, 1.0 - gap_lines / config.fragment_max_line_gap_ratio),
        "horizontal_compatibility": 1.8 * horizontal,
        "edge_alignment": (
            1.0
            if min(left_delta, right_delta) <= config.fragment_edge_alignment_page_ratio
            else 0.0
        ),
        "reading_order": (
            1.1 if order_delta <= 1 else (0.5 if order_delta <= 2 else -0.8)
        ),
        "table_corridor": (
            0.8
            if _overlap_ratio(cb, tb) >= config.min_horizontal_overlap_ratio
            else 0.0
        ),
        "detector_class": 0.8 if candidate.get("type") == "Caption" else 0.0,
        "lexical_continuation": 0.5 if punctuation_continuation else 0.0,
        "typography": 0.4 if shared_style else 0.0,
        "overlap_evidence": (
            0.5
            if relationship_kinds & {"FRAGMENT_CANDIDATE", "COMPLEMENTARY_FRAGMENT"}
            else 0.0
        ),
        "conflict_penalty": (
            -2.5
            if relationship_kinds
            & {"INVALID_OCCLUSION", "CLASS_CONFLICT", "AMBIGUOUS_OVERLAP"}
            else 0.0
        ),
        "body_paragraph_penalty": paragraph_penalty,
    }
    score = sum(components.values())
    if score < config.fragment_acceptance_score:
        return None
    return {
        "table_region_id": str(table["layout_region_id"]),
        "region_id": str(candidate["layout_region_id"]),
        "member_region_id": str(member["layout_region_id"]),
        "proposed_role": "caption_fragment",
        "score": round(score, 4),
        "accepted": False,
        "direction": "above" if member_above else "below",
        "features": {
            "vertical_gap_page_ratio": round(gap_page, 6),
            "vertical_gap_line_ratio": round(gap_lines, 4),
            "horizontal_overlap_ratio": round(horizontal, 6),
            "left_alignment_page_ratio": round(left_delta, 6),
            "right_alignment_page_ratio": round(right_delta, 6),
            "reading_order_delta": order_delta,
            "relationship_kinds": sorted(relationship_kinds),
            "components": components,
        },
    }


def _group_bbox(regions: list[LayoutRegion]) -> list[float]:
    boxes = [list(map(float, region["bbox_px"])) for region in regions]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _fragmented_identifier_candidates(
    page_regions: list[LayoutRegion],
    tables: list[LayoutRegion],
    page_width: float,
    page_height: float,
) -> list[LayoutRegion]:
    """Build provenance-only anchors from locally ordered identifier fragments.

    Detector reading order is page-axis based and is therefore only a fallback.
    When a detector-class Caption already exists, search the caption lane in its
    local orientation and reconstruct a bounded semantic prefix there.  Physical
    source regions remain immutable; the returned regions exist only long enough
    to participate in table ownership scoring.
    """
    text_regions = [
        region
        for region in sorted(page_regions, key=_order)
        if region.get("type") in _FRAGMENT_TYPES
        and str(region.get("text") or "").strip()
    ]
    output: list[LayoutRegion] = []
    emitted: set[tuple[str, ...]] = set()
    claimed: set[str] = set()

    def emit(members, reference, combined, *, table_id=None, orientation=None):
        member_ids = tuple(str(member["layout_region_id"]) for member in members)
        key = (str(table_id or ""), *member_ids)
        if key in emitted:
            return
        emitted.add(key)
        boxes = [list(map(float, member["bbox_px"])) for member in members]
        virtual = dict(members[0])
        virtual_id = "fragmented:" + "+".join(member_ids)
        if table_id:
            virtual_id += f":table:{table_id}"
        virtual.update(
            layout_region_id=virtual_id,
            type="Text",
            text=combined,
            bbox_px=_group_bbox(members),
            width_px=max(box[2] for box in boxes) - min(box[0] for box in boxes),
            height_px=max(box[3] for box in boxes) - min(box[1] for box in boxes),
            semantic_source_region_ids=list(member_ids),
            semantic_reference=reference.__dict__,
            semantic_target_table_region_id=table_id,
            semantic_detection_method="orientation_aware_fragmented_identifier",
        )
        if orientation and orientation.get("angle_degrees") is not None:
            virtual["orientation"] = dict(orientation)
        output.append(virtual)

    # Strong contextual path: an existing Caption and a Table define the lane in
    # which otherwise incomplete Text fragments can jointly become an identifier.
    captions = [region for region in page_regions if region.get("type") == "Caption"]
    scale = max(1.0, (page_width**2 + page_height**2) ** 0.5)
    for table in tables:
        tb = list(map(float, table["bbox_px"]))
        for caption in captions:
            cb = list(map(float, caption["bbox_px"]))
            orientation = region_orientation(caption)
            angle = orientation["angle_degrees"]
            if angle is None:
                continue
            caption_table = local_relation(cb, tb, angle)
            if caption_table["side"] not in {"before", "after"}:
                continue
            local_caption = project_bbox(cb, angle)
            bare_caption_label = leading_table_label_fragment(caption.get("text"))
            lane = []
            for region in text_regions:
                if region.get("type") not in {"Text", "List"}:
                    continue
                rb = list(map(float, region["bbox_px"]))
                if _intersection_area(rb, tb) > 0:
                    continue
                if reliable_orientation_conflict(region, caption):
                    continue
                region_table = local_relation(rb, tb, angle)
                if region_table["side"] != caption_table["side"]:
                    continue
                local_region = project_bbox(rb, angle)
                block_overlap = interval_overlap_ratio(
                    local_region.block_min,
                    local_region.block_max,
                    local_caption.block_min,
                    local_caption.block_max,
                )
                inline_overlap = interval_overlap_ratio(
                    local_region.inline_min,
                    local_region.inline_max,
                    local_caption.inline_min,
                    local_caption.inline_max,
                )
                inline_gap = max(
                    0.0,
                    max(local_region.inline_min, local_caption.inline_min)
                    - min(local_region.inline_max, local_caption.inline_max),
                )
                block_gap = max(
                    0.0,
                    max(local_region.block_min, local_caption.block_min)
                    - min(local_region.block_max, local_caption.block_max),
                )
                # The far end of a multi-box identifier can be several short
                # tokens away from the description even though every internal
                # token gap is small. The grammar and bounded path length provide
                # the stricter safeguard after this intentionally broad search.
                same_line = block_overlap >= 0.30 and inline_gap / scale <= 0.18
                adjacent_line = inline_overlap >= 0.30 and block_gap / scale <= 0.025
                if not (same_line or adjacent_line):
                    continue
                lane.append((region, local_region))
            # Limit combinatorics without using global page order: the closest
            # local fragments are the only plausible missing caption prefix.
            lane.sort(
                key=lambda item: min(
                    abs(item[1].inline_max - local_caption.inline_min),
                    abs(local_caption.inline_max - item[1].inline_min),
                )
            )
            lane = lane[:8]
            minimum_size = 1 if bare_caption_label else 2
            for size in range(minimum_size, min(4, len(lane)) + 1):
                for selection in combinations(lane, size):
                    local_sorted = sorted(
                        selection, key=lambda item: item[1].inline_min
                    )
                    directions = [local_sorted]
                    # bbox-axis inference gives a baseline axis, not a reading
                    # direction. Test both directions and let the grammar decide.
                    if orientation.get("source") == "bbox_axis":
                        directions.append(list(reversed(local_sorted)))
                    for ordered_items in directions:
                        members = [item[0] for item in ordered_items]
                        member_locals = [item[1] for item in ordered_items]
                        gaps = [
                            max(0.0, right.inline_min - left.inline_max) / scale
                            for left, right in zip(member_locals, member_locals[1:])
                        ]
                        if gaps and max(gaps) > 0.025:
                            continue
                        fragment_values = [member.get("text") for member in members]
                        if bare_caption_label:
                            fragment_values.insert(0, bare_caption_label)
                        parsed = parse_fragmented_table_reference(
                            fragment_values,
                            allow_ocr_tolerance=True,
                        )
                        if not parsed or any(
                            _table_reference(member.get("text")) for member in members
                        ):
                            continue
                        reference, combined = parsed
                        # Contextual reconstruction owns only the identifier. The
                        # detector-class Caption remains the description anchor.
                        if combined[reference.end :].strip():
                            continue
                        cluster_same_line = any(
                            interval_overlap_ratio(
                                item.block_min,
                                item.block_max,
                                local_caption.block_min,
                                local_caption.block_max,
                            )
                            >= 0.30
                            for item in member_locals
                        )
                        if (
                            cluster_same_line
                            and not bare_caption_label
                            and orientation.get("source") != "bbox_axis"
                            and max(item.inline_max for item in member_locals)
                            > local_caption.inline_min + scale * 0.008
                        ):
                            continue
                        emit(
                            members,
                            reference,
                            combined,
                            table_id=str(table["layout_region_id"]),
                            orientation=orientation,
                        )

    # Page-axis fallback supports ordinary horizontal pages and documents without
    # orientation metadata. It is deliberately bounded but no longer the sole
    # mechanism used for fragmented identifiers.
    for size in (3, 2):
        for start in range(len(text_regions) - size + 1):
            members = text_regions[start : start + size]
            member_ids = {str(member["layout_region_id"]) for member in members}
            if member_ids & claimed:
                continue
            if any(
                _order(right) - _order(left) > 1
                for left, right in zip(members, members[1:])
            ):
                continue
            boxes = [list(map(float, member["bbox_px"])) for member in members]
            union_bbox = _group_bbox(members)
            # Never synthesize one semantic anchor from detections on opposite
            # sides of a table. Its union would paint a caption across the asset.
            if any(
                _intersection_area(union_bbox, list(map(float, table["bbox_px"]))) > 0
                and not any(
                    _intersection_area(box, list(map(float, table["bbox_px"]))) > 0
                    for box in boxes
                )
                for table in tables
            ):
                continue
            vertical_gap = max(box[1] for box in boxes) - min(box[3] for box in boxes)
            horizontal_gap = max(box[0] for box in boxes) - min(box[2] for box in boxes)
            if (
                vertical_gap > page_height * 0.025
                and horizontal_gap > page_width * 0.025
            ):
                continue
            parsed = parse_fragmented_table_reference(
                [member.get("text") for member in members], allow_ocr_tolerance=True
            )
            if not parsed or any(
                _table_reference(member.get("text")) for member in members
            ):
                continue
            reference, combined = parsed
            if combined[reference.end :].strip():
                continue
            emit(members, reference, combined)
            claimed.update(member_ids)
    # Prefer the most complete contextual interpretation when, for example,
    # ``Table`` + ``S`` is a valid label but ``Table`` + ``S`` + ``3`` is the
    # actual identifier. This also prevents overlapping virtual candidates from
    # independently claiming the same physical prefix components.
    contextual = [
        item for item in output if item.get("semantic_target_table_region_id")
    ]
    contextual_sources = {
        tuple(item["semantic_source_region_ids"]) for item in contextual
    }
    superseded: set[str] = set()
    for candidate in contextual:
        candidate_ids = set(candidate["semantic_source_region_ids"])
        for other in contextual:
            if candidate is other or candidate.get(
                "semantic_target_table_region_id"
            ) != other.get("semantic_target_table_region_id"):
                continue
            other_ids = set(other["semantic_source_region_ids"])
            if candidate_ids < other_ids:
                superseded.add(str(candidate["layout_region_id"]))
                break
    return [
        item
        for item in output
        if str(item["layout_region_id"]) not in superseded
        and (
            item.get("semantic_target_table_region_id")
            or tuple(item["semantic_source_region_ids"]) not in contextual_sources
        )
    ]


def _caption_edge_has_identifier_neighbor(
    edge: dict[str, Any],
    regions_by_id: dict[str, LayoutRegion],
    page_regions: list[LayoutRegion],
    table: LayoutRegion,
    page_width: float,
    page_height: float,
) -> bool:
    """Whether a short Text identifier continues a rotated Caption lane."""
    caption = regions_by_id[str(edge["region_id"])]
    side = str(edge["direction"])
    if caption.get("type") != "Caption" or side not in {"left", "right"}:
        return False
    cb = list(map(float, caption["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    for region in page_regions:
        if region.get("type") not in {"Text", "List"}:
            continue
        if not _table_reference(region.get("text"), tolerant=True):
            continue
        rb = list(map(float, region["bbox_px"]))
        same_side = (side == "left" and rb[2] <= tb[0] + page_width * 0.008) or (
            side == "right" and rb[0] >= tb[2] - page_width * 0.008
        )
        lane_overlap = _overlap_ratio(cb, rb)
        axis_gap = max(0.0, max(cb[1], rb[1]) - min(cb[3], rb[3])) / page_height
        if same_side and lane_overlap >= 0.30 and axis_gap <= 0.035:
            return True
    return False


def _retain_one_caption_side(
    edges: list[dict[str, Any]],
    page_regions: list[LayoutRegion],
    tables: list[LayoutRegion],
    page_width: float,
    page_height: float,
    config: TableContextConfig,
) -> list[dict[str, Any]]:
    """Keep one coherent caption lane per table while retaining independent notes.

    Rotated tables commonly have a caption on one long edge and notes on the
    opposite edge. Combining detector-class Caption boxes from both sides makes
    the semantic union cross the table. Score each complete side hypothesis using
    identifier quality, reconstructed-fragment evidence, detector class, and note
    semantics; never let one weak lexical parse categorically select a lane.
    Source detections on other sides remain untouched and ungrouped.
    """
    captions_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if edge["proposed_role"] == "caption":
            captions_by_table[str(edge["table_region_id"])].append(edge)

    regions_by_id = {str(region["layout_region_id"]): region for region in page_regions}
    tables_by_id = {str(table["layout_region_id"]): table for table in tables}
    selected_side: dict[str, str | None] = {}
    selected_orientation_anchor: dict[str, LayoutRegion] = {}
    for table_id, caption_edges in captions_by_table.items():
        by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in caption_edges:
            by_side[str(edge["direction"])].append(edge)
        hypotheses: list[dict[str, Any]] = []
        for side, side_edges in by_side.items():
            identifier_edges = [
                edge for edge in side_edges if edge.get("printed_label")
            ]
            identifier_quality = max(
                (
                    float(
                        (edge.get("semantic_reference_quality") or {}).get("score", 1.0)
                    )
                    for edge in identifier_edges
                ),
                default=0.0,
            )
            reconstructed = any(
                regions_by_id[str(edge["region_id"])].get("semantic_detection_method")
                == "orientation_aware_fragmented_identifier"
                for edge in identifier_edges
            )
            detector_captions = sum(
                regions_by_id[str(edge["region_id"])].get("type") == "Caption"
                for edge in side_edges
            )
            note_like = sum(
                bool(
                    _TABLE_NOTE_TEXT_RE.match(
                        str(regions_by_id[str(edge["region_id"])].get("text") or "")
                    )
                )
                for edge in side_edges
            )
            neighboring_identifier = any(
                _caption_edge_has_identifier_neighbor(
                    edge,
                    regions_by_id,
                    page_regions,
                    tables_by_id[table_id],
                    page_width,
                    page_height,
                )
                for edge in side_edges
            )
            components = {
                "strongest_edge": max(float(edge["score"]) for edge in side_edges),
                "identifier_quality": 1.8 * identifier_quality,
                "reconstructed_identifier": 1.6 if reconstructed else 0.0,
                "neighboring_identifier": 0.8 if neighboring_identifier else 0.0,
                "detector_caption": min(1.0, 0.5 * detector_captions),
                "note_penalty": -2.5 * note_like,
            }
            hypotheses.append(
                {
                    "side": side,
                    "score": sum(components.values()),
                    "components": components,
                    "edges": side_edges,
                    "anchor": max(
                        identifier_edges or side_edges,
                        key=lambda edge: (edge["score"], edge["region_id"]),
                    ),
                }
            )
        hypotheses.sort(key=lambda item: (-item["score"], item["side"]))
        winner = hypotheses[0]
        ambiguous = (
            len(hypotheses) > 1
            and winner["score"] - hypotheses[1]["score"]
            < config.fragment_ambiguity_margin
        )
        selected_side[table_id] = None if ambiguous else str(winner["side"])
        if ambiguous:
            continue
        for hypothesis in hypotheses:
            for edge in hypothesis["edges"]:
                edge.setdefault("features", {})["caption_side_hypothesis"] = {
                    "side": hypothesis["side"],
                    "score": round(hypothesis["score"], 4),
                    "components": hypothesis["components"],
                    "selected": hypothesis is winner,
                }
        anchor_edge = winner["anchor"]
        selected_orientation_anchor[table_id] = regions_by_id[
            str(anchor_edge["region_id"])
        ]

    return [
        edge
        for edge in edges
        if edge["proposed_role"] != "caption"
        or (
            edge["direction"] == selected_side.get(str(edge["table_region_id"]))
            and not reliable_orientation_conflict(
                regions_by_id[str(edge["region_id"])],
                selected_orientation_anchor[str(edge["table_region_id"])],
            )
        )
    ]


def _reference_fragment_edge(
    candidate: LayoutRegion,
    member: LayoutRegion,
    table: LayoutRegion,
    caption_side: str,
    page_width: float,
    page_height: float,
) -> dict[str, Any] | None:
    """Join a Text table-number fragment to a Caption without merging geometry."""
    if candidate.get("type") not in {"Text", "List"} or member.get("type") != "Caption":
        return None
    reference = parse_semantic_caption_reference(
        candidate.get("text"), allow_ocr_tolerance=True
    )
    if not reference:
        return None
    reference_quality = caption_reference_quality(candidate.get("text"), reference)
    if not reference_quality["authoritative"]:
        return None
    negative_reasons = body_reference_evidence(candidate.get("text"))
    if negative_reasons:
        return None
    orientation_compatible = compatible_orientation(candidate, member)
    if reliable_orientation_conflict(candidate, member):
        return None
    cb = list(map(float, candidate["bbox_px"]))
    mb = list(map(float, member["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    tolerance_x = page_width * 0.008
    tolerance_y = page_height * 0.008
    side_checks = {
        "left": cb[2] <= tb[0] + tolerance_x and mb[2] <= tb[0] + tolerance_x,
        "right": cb[0] >= tb[2] - tolerance_x and mb[0] >= tb[2] - tolerance_x,
        "above": cb[3] <= tb[1] + tolerance_y and mb[3] <= tb[1] + tolerance_y,
        "below": cb[1] >= tb[3] - tolerance_y and mb[1] >= tb[3] - tolerance_y,
    }
    same_side = side_checks.get(caption_side, False)

    if same_side:
        orientation = region_orientation(member)
        angle = orientation["angle_degrees"]
        if angle is None:
            angle = region_orientation(candidate)["angle_degrees"] or 0.0
        relation = local_relation(cb, mb, angle)
        scale = max(1.0, (page_width**2 + page_height**2) ** 0.5)
        gap = float(relation["gap"]) / scale
        alignment = float(relation["overlap"])
        orientation_relation = "normalized_axis_continuation"
        # Detector fragments at a caption boundary frequently overlap by a few
        # pixels on both local axes.  Such boxes have no strict before/after
        # relation, but are still one continuous external caption lane.  Measure
        # both local-axis overlaps rather than dropping the semantic identifier.
        if relation["side"] is None:
            local_candidate = project_bbox(cb, angle)
            local_member = project_bbox(mb, angle)
            inline_overlap = interval_overlap_ratio(
                local_candidate.inline_min,
                local_candidate.inline_max,
                local_member.inline_min,
                local_member.inline_max,
            )
            block_overlap = interval_overlap_ratio(
                local_candidate.block_min,
                local_candidate.block_max,
                local_member.block_min,
                local_member.block_max,
            )
            alignment = max(inline_overlap, block_overlap)
            orientation_relation = "normalized_boundary_overlap"
    else:
        opposite_long_sides = (
            caption_side == "left"
            and mb[2] <= tb[0] + tolerance_x
            and cb[0] >= tb[2] - tolerance_x
        ) or (
            caption_side == "right"
            and mb[0] >= tb[2] - tolerance_x
            and cb[2] <= tb[0] + tolerance_x
        )
        if not opposite_long_sides:
            return None
        gap = 0.0
        alignment = _vertical_overlap_ratio(cb, mb)
        orientation_relation = "opposite_long_edges"
    if (same_side and gap > 0.035) or alignment < (0.30 if same_side else 0.70):
        return None
    return {
        "table_region_id": str(table["layout_region_id"]),
        "region_id": str(candidate["layout_region_id"]),
        "member_region_id": str(member["layout_region_id"]),
        "proposed_role": "caption_fragment",
        "score": round(
            6.0 + 2.0 * alignment - gap - (0.4 if not same_side else 0.0), 4
        ),
        "accepted": False,
        "direction": caption_side,
        "printed_label": reference.label,
        "printed_label_text": str(candidate.get("text") or "")[: reference.end].strip(),
        "semantic_reference": reference.__dict__,
        "semantic_reference_quality": reference_quality,
        "features": {
            "rule": (
                "same_side_table_reference_next_to_caption"
                if same_side
                else "opposite_side_table_reference_same_caption"
            ),
            "gap_page_ratio": round(gap, 6),
            "parallel_overlap_ratio": round(alignment, 6),
            "orientation_relation": orientation_relation,
            "orientation_compatible": orientation_compatible,
            "candidate_orientation": region_orientation(candidate),
            "caption_orientation": region_orientation(member),
            "geometry_space": "table_local_orientation",
            "crosses_table": not same_side,
            "negative_reasons": negative_reasons,
            "preserve_separate_geometry": True,
        },
    }


def _caption_table_corridor_edge(
    candidate: LayoutRegion,
    seed: LayoutRegion,
    table: LayoutRegion,
    page_width: float,
    page_height: float,
    config: TableContextConfig,
    relationship_kinds: set[str],
) -> dict[str, Any] | None:
    """Associate text physically sandwiched between a caption and its table.

    Once a caption seed has been unambiguously assigned to a table, geometry is
    authoritative for the intervening area.  In particular, paragraph-like
    wording must not prevent a detector-split caption continuation from being
    included.  This is intentionally distinct from speculative graph growth
    beyond the seed-to-table corridor, where the stricter semantic safeguards
    still apply.
    """
    if candidate.get("type") not in _TEXT_TYPES:
        return None
    text = str(candidate.get("text") or "").strip()
    if not text:
        return None
    # A Figure/Fig. caption is a hard semantic boundary even when a detector
    # emits one large box spanning the space between a Table caption and Table.
    # Geometry must never absorb an explicitly identified different asset.
    other_asset_kind = _explicit_other_asset_reference(text)
    if other_asset_kind:
        return None

    cb = list(map(float, candidate["bbox_px"]))
    sb = list(map(float, seed["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    seed_above = (sb[1] + sb[3]) / 2.0 < (tb[1] + tb[3]) / 2.0
    if seed_above:
        between = cb[1] >= sb[3] - tolerance and cb[3] <= tb[1] + tolerance
    else:
        between = cb[1] >= tb[3] - tolerance and cb[3] <= sb[1] + tolerance
    if not between or not _column_compatible(candidate, table, page_width):
        return None

    table_overlap = _overlap_ratio(cb, tb)
    seed_overlap = _overlap_ratio(cb, sb)
    if max(table_overlap, seed_overlap) < config.min_horizontal_overlap_ratio:
        return None

    return {
        "table_region_id": str(table["layout_region_id"]),
        "region_id": str(candidate["layout_region_id"]),
        "member_region_id": str(seed["layout_region_id"]),
        "proposed_role": "caption_fragment",
        "score": 10.0,
        "accepted": False,
        "direction": "above" if seed_above else "below",
        "features": {
            "rule": "text_between_associated_caption_and_table",
            "horizontal_overlap_with_table": round(table_overlap, 6),
            "horizontal_overlap_with_caption_seed": round(seed_overlap, 6),
            "body_text_semantics_ignored": True,
            "relationship_kinds": sorted(relationship_kinds),
            "components": {
                "overlap_evidence": (
                    0.5
                    if relationship_kinds
                    & {"FRAGMENT_CANDIDATE", "COMPLEMENTARY_FRAGMENT"}
                    else 0.0
                )
            },
        },
    }


def associate_table_context(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    *,
    document_id: str,
    config: TableContextConfig | None = None,
    relationships: list[dict[str, Any]] | None = None,
    index: RegionIndex | None = None,
    metrics: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Create table groups using constrained, explainable relationship scoring.

    Raw regions are referenced by ID and are never reclassified or resized.
    Candidate regions have exclusive ownership; uncertain competing assignments
    are deliberately left unattached.
    """
    config = config or TableContextConfig()
    relationship_kinds: dict[frozenset[str], set[str]] = defaultdict(set)
    for relationship in relationships or []:
        left = relationship.get("left_region_id") or relationship.get("child_region_id")
        right = relationship.get("right_region_id") or relationship.get(
            "parent_region_id"
        )
        if left and right:
            relationship_kinds[frozenset((str(left), str(right)))].add(
                str(relationship.get("kind") or "")
            )
    index = index or RegionIndex.build(regions, pages)
    metrics = metrics if metrics is not None else {}
    metrics.update(tables=0, candidate_role_pairs=0, scored_edges=0)

    groups: list[dict[str, Any]] = []
    for page_number in sorted(index.by_page):
        source_page_regions = list(index.by_page[page_number])
        tables = sorted(
            (region for region in source_page_regions if region.get("type") == "Table"),
            key=lambda region: (
                int(region.get("layout_reading_order") or 10**9),
                float(region["bbox_px"][1]),
                float(region["bbox_px"][0]),
            ),
        )
        width, height = index.page_sizes.get(page_number, (1.0, 1.0))
        page_regions = source_page_regions + _fragmented_identifier_candidates(
            source_page_regions, tables, width, height
        )
        metrics["tables"] += len(tables)
        page_groups: dict[str, dict[str, Any]] = {}
        for ordinal, table in enumerate(tables, 1):
            internal_id = f"{document_id}:p{page_number:04d}:t{ordinal:02d}"
            page_groups[table["layout_region_id"]] = {
                "internal_id": internal_id,
                "page_number": page_number,
                "table_region_id": table["layout_region_id"],
                "table_bbox": list(table["bbox_px"]),
                "identifier_region_ids": [],
                "caption_region_ids": [],
                "caption_side": None,
                "note_region_ids": [],
                "printed_label": None,
                "printed_label_text": None,
                "associations": [],
                "confidence": 0.0,
                "group_bbox": list(table["bbox_px"]),
                "continuation_group_id": None,
                "continuation_status": "page_local",
            }

        edges: list[dict[str, Any]] = []
        for table in tables:
            for candidate in page_regions:
                if candidate is table:
                    continue
                target_table = candidate.get("semantic_target_table_region_id")
                if target_table and str(table["layout_region_id"]) != str(target_table):
                    continue
                for role in ("caption", "note"):
                    metrics["candidate_role_pairs"] += 1
                    if role == "caption" and not (
                        candidate.get("type") == "Caption"
                        or _table_reference(
                            str(candidate.get("text") or ""), tolerant=True
                        )
                    ):
                        continue
                    if role == "caption" and _explicit_other_asset_reference(
                        str(candidate.get("text") or "")
                    ):
                        continue
                    if role == "note" and not (
                        candidate.get("type") == "Footnote"
                        or _NOTE_RE.search(str(candidate.get("text") or ""))
                        or bool((candidate.get("typography") or {}).get("superscript"))
                        or candidate.get("has_superscript")
                    ):
                        continue
                    edge = _score_edge(
                        candidate, table, role, page_regions, width, height, config
                    )
                    if edge and edge["score"] >= config.acceptance_score:
                        edges.append(edge)
                        metrics["scored_edges"] += 1

        edges = _retain_one_caption_side(
            edges, page_regions, tables, width, height, config
        )

        candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            candidates[edge["region_id"]].append(edge)
        region_by_id = {region["layout_region_id"]: region for region in page_regions}
        for region_id, alternatives in candidates.items():
            alternatives.sort(key=lambda edge: edge["score"], reverse=True)
            winner = alternatives[0]
            if (
                len(alternatives) > 1
                and winner["score"] - alternatives[1]["score"] < config.ambiguity_margin
            ):
                continue
            winner["accepted"] = True
            winner["alternative_count"] = len(alternatives) - 1
            group = page_groups[winner["table_region_id"]]
            source_ids = region_by_id[region_id].get(
                "semantic_source_region_ids", [region_id]
            )
            if winner["proposed_role"] == "caption":
                group["caption_side"] = winner["direction"]
                if winner["printed_label"]:
                    group["identifier_region_ids"].extend(source_ids)
                    group["printed_label"] = (
                        group["printed_label"] or winner["printed_label"]
                    )
                    group["printed_label_text"] = (
                        group["printed_label_text"]
                        or winner.get("printed_label_text")
                        or winner["printed_label"]
                    )
                    if winner["caption_text_after_label"]:
                        group["caption_region_ids"].extend(source_ids)
                else:
                    group["caption_region_ids"].extend(source_ids)
            else:
                group["note_region_ids"].append(region_id)
            group["associations"].append(winner)

        # Virtual split-label candidates are association-only; graph growth and
        # output always use their immutable physical source regions.
        page_regions = source_page_regions

        # Grow captions from accepted label/class seeds using local adjacency.
        # Each round uses the current component as its frontier and assigns a
        # fragment only when one table wins by a clear margin.
        owned = {
            region_id
            for group in page_groups.values()
            for key in (
                "identifier_region_ids",
                "caption_region_ids",
                "note_region_ids",
            )
            for region_id in group[key]
        }
        tables_by_id = {str(table["layout_region_id"]): table for table in tables}

        # A detector may put the descriptive caption in a Caption box and the
        # table-number phrase in an adjacent Text box. Attach that Text only when
        # boxes are adjacent on one side or occupy aligned opposite long edges.
        # The latter is a semantic link only; display geometry stays separate.
        reference_proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for table_id, group in page_groups.items():
            caption_side = group.get("caption_side")
            if not caption_side:
                continue
            caption_seeds = [
                region_by_id[region_id]
                for region_id in dict.fromkeys(
                    group["identifier_region_ids"] + group["caption_region_ids"]
                )
                if region_by_id[region_id].get("type") == "Caption"
            ]
            for candidate in page_regions:
                candidate_id = str(candidate.get("layout_region_id"))
                if candidate_id in owned or candidate_id == table_id:
                    continue
                for seed in caption_seeds:
                    edge = _reference_fragment_edge(
                        candidate,
                        seed,
                        tables_by_id[table_id],
                        str(caption_side),
                        width,
                        height,
                    )
                    if edge:
                        reference_proposals[candidate_id].append(edge)
        for region_id, alternatives in reference_proposals.items():
            best_by_table: dict[str, dict[str, Any]] = {}
            for edge in alternatives:
                table_id = edge["table_region_id"]
                if (
                    table_id not in best_by_table
                    or edge["score"] > best_by_table[table_id]["score"]
                ):
                    best_by_table[table_id] = edge
            ranked = sorted(
                best_by_table.values(), key=lambda edge: edge["score"], reverse=True
            )
            if (
                len(ranked) > 1
                and ranked[0]["score"] - ranked[1]["score"]
                < config.fragment_ambiguity_margin
            ):
                continue
            winner = ranked[0]
            winner["accepted"] = True
            winner["alternative_count"] = len(ranked) - 1
            group = page_groups[winner["table_region_id"]]
            group["identifier_region_ids"].append(region_id)
            group["caption_region_ids"].append(region_id)
            group["printed_label"] = group["printed_label"] or winner["printed_label"]
            group["printed_label_text"] = (
                group["printed_label_text"]
                or winner.get("printed_label_text")
                or winner["printed_label"]
            )
            group["associations"].append(winner)
            owned.add(region_id)

        # A detector frequently emits only the short "Table N." label as a
        # Caption and emits the description as ordinary Text.  Include every
        # text region physically between an accepted caption seed and its table
        # before attempting conservative graph growth outside that corridor.
        corridor_proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for table_id, group in page_groups.items():
            seeds = list(
                dict.fromkeys(
                    group["identifier_region_ids"] + group["caption_region_ids"]
                )
            )
            for seed_id in seeds:
                for candidate in page_regions:
                    candidate_id = str(candidate.get("layout_region_id"))
                    if candidate_id in owned or candidate_id == table_id:
                        continue
                    edge = _caption_table_corridor_edge(
                        candidate,
                        region_by_id[seed_id],
                        tables_by_id[table_id],
                        width,
                        height,
                        config,
                        relationship_kinds.get(
                            frozenset((candidate_id, seed_id)), set()
                        ),
                    )
                    if edge:
                        corridor_proposals[candidate_id].append(edge)
        for region_id, alternatives in corridor_proposals.items():
            table_ids = {edge["table_region_id"] for edge in alternatives}
            # Do not guess when the same physical text lies in corridors for
            # multiple tables. Within one table, the closest seed is sufficient.
            if len(table_ids) != 1:
                continue
            winner = min(
                alternatives,
                key=lambda edge: abs(
                    _order(region_by_id[edge["member_region_id"]])
                    - _order(region_by_id[region_id])
                ),
            )
            winner["accepted"] = True
            winner["alternative_count"] = len(alternatives) - 1
            group = page_groups[winner["table_region_id"]]
            group["caption_region_ids"].append(region_id)
            group["associations"].append(winner)
            owned.add(region_id)

        while True:
            proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for table_id, group in page_groups.items():
                members = list(
                    dict.fromkeys(
                        group["identifier_region_ids"] + group["caption_region_ids"]
                    )
                )
                if not members:
                    continue
                for candidate in page_regions:
                    candidate_id = str(candidate.get("layout_region_id"))
                    if candidate_id in owned or candidate_id == table_id:
                        continue
                    for member_id in members:
                        evidence = relationship_kinds.get(
                            frozenset((candidate_id, member_id)), set()
                        )
                        edge = _fragment_edge(
                            candidate,
                            region_by_id[member_id],
                            tables_by_id[table_id],
                            page_regions,
                            width,
                            height,
                            config,
                            evidence,
                        )
                        if edge:
                            proposals[candidate_id].append(edge)
            accepted_any = False
            for region_id, alternatives in proposals.items():
                # Retain the strongest path per table before comparing parents.
                best_by_table: dict[str, dict[str, Any]] = {}
                for edge in alternatives:
                    table_id = edge["table_region_id"]
                    if (
                        table_id not in best_by_table
                        or edge["score"] > best_by_table[table_id]["score"]
                    ):
                        best_by_table[table_id] = edge
                ranked = sorted(
                    best_by_table.values(), key=lambda item: item["score"], reverse=True
                )
                winner = ranked[0]
                if (
                    len(ranked) > 1
                    and winner["score"] - ranked[1]["score"]
                    < config.fragment_ambiguity_margin
                ):
                    continue
                winner["accepted"] = True
                winner["alternative_count"] = len(ranked) - 1
                group = page_groups[winner["table_region_id"]]
                group["caption_region_ids"].append(region_id)
                group["associations"].append(winner)
                owned.add(region_id)
                accepted_any = True
            if not accepted_any:
                break

        for table in tables:
            group = page_groups[table["layout_region_id"]]
            for key in (
                "identifier_region_ids",
                "caption_region_ids",
                "note_region_ids",
            ):
                group[key].sort(
                    key=lambda region_id: (
                        int(
                            region_by_id[region_id].get("layout_reading_order") or 10**9
                        ),
                        float(region_by_id[region_id]["bbox_px"][1]),
                    )
                )
            associated_regions = [table] + [
                region_by_id[region_id]
                for key in (
                    "identifier_region_ids",
                    "caption_region_ids",
                    "note_region_ids",
                )
                for region_id in group[key]
            ]
            group["group_bbox"] = _group_bbox(associated_regions)
            scores = [item["score"] for item in group["associations"]]
            group["confidence"] = (
                round(min(1.0, sum(scores) / max(1, len(scores)) / 8.0), 4)
                if scores
                else 1.0
            )
            group["caption_fragment_association"] = {
                "strategy": "caption_table_corridor_then_seeded_local_graph",
                "semantic_role": "table_caption",
                "fragment_region_ids": list(group["caption_region_ids"]),
                "source_geometry_preserved": True,
            }
            orientation_members = [
                region_by_id[region_id]
                for region_id in dict.fromkeys(
                    group["identifier_region_ids"] + group["caption_region_ids"]
                )
            ]
            group["caption_orientation"] = next(
                (
                    region_orientation(region)
                    for region in orientation_members
                    if region_orientation(region)["angle_degrees"] is not None
                ),
                {"angle_degrees": None, "confidence": 0.0, "source": "unknown"},
            )
            group["relationship_coordinate_space"] = (
                "table_local_orientation"
                if group["caption_orientation"]["angle_degrees"] is not None
                else "page_axes_fallback"
            )
            groups.append(group)
    return groups
