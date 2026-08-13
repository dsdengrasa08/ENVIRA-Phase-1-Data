"""Infer structured page-one metadata without publisher-specific geometry.

The detector remains authoritative for physical regions.  This module adds a
logical layer that identifies metadata containers, fields, labels, and value
continuations before content-policy filtering.  Source ids and boxes are retained
on every logical value region so an inference can always be audited.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from ..config import Page1FilterConfig
from ..types import LayoutRegion, TransformStageResult


_SPACE = re.compile(r"\s+")
_PROSE_END = re.compile(r"[.!?](?:\s|$)")
_BODY_BOUNDARY = re.compile(
    r"^\s*(?:(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\s.)\-:]*)?"
    r"(abstract|summary|introduction|background|methods?|results?|discussion|"
    r"conclusions?|references?)\b",
    re.I,
)

# These are semantic families, not output-triggering exact phrases.  A match only
# proposes a field label; geometry, front-matter context, and child values must also
# agree before any region is grouped or normalized.
_FIELD_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "administrative_history",
        re.compile(
            r"^\s*(?:(?:article|manuscript|publication|submission)\s+)?"
            r"(?:history|information|details?|record|timeline)\s*:?.*$",
            re.I,
        ),
    ),
    (
        "scientific_descriptors",
        re.compile(
            r"^\s*(?:key\s*words?|index\s+terms?|subject\s+(?:terms?|areas?)|"
            r"topic\s+(?:terms?|areas?)|classification\s+(?:codes?|terms?))\s*:?.*$",
            re.I,
        ),
    ),
    (
        "classification",
        re.compile(
            r"^\s*(?:classification|categories|subject\s+classification|"
            r"jel|msc|pacs)\s*(?:codes?)?\s*:?.*$",
            re.I,
        ),
    ),
    (
        "abbreviations",
        re.compile(r"^\s*(?:abbreviations?|acronyms?|nomenclature)\s*:?.*$", re.I),
    ),
    (
        "highlights",
        re.compile(r"^\s*(?:highlights?|key\s+points?|key\s+messages?)\s*:?.*$", re.I),
    ),
    (
        "correspondence",
        re.compile(
            r"^\s*(?:correspond(?:ing|ence)|contact|author\s+information|"
            r"address\s+for\s+correspondence)\s*:?.*$",
            re.I,
        ),
    ),
    (
        "identifiers",
        re.compile(r"^\s*(?:doi|article\s+(?:number|id)|identifier)\s*:?.*$", re.I),
    ),
)

_VALUE_TYPES = {
    "Text",
    "List",
    "Field-item",
    "Field-value",
    "Key-value",
}
_HEADING_TYPES = {"Caption", "Section-header", "Title", "Text", "Field-heading"}


@dataclass(frozen=True)
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


def _page_size(page: Any) -> tuple[float, float]:
    if isinstance(page, dict):
        return (
            float(page.get("image_width_px") or page.get("width_px") or 1),
            float(page.get("image_height_px") or page.get("height_px") or 1),
        )
    return float(page.width_px), float(page.height_px)


def _box(region: LayoutRegion) -> _Box:
    return _Box(*map(float, region["bbox_px"]))


def _text(region: LayoutRegion) -> str:
    return _SPACE.sub(" ", str(region.get("text") or region.get("orig") or "")).strip()


def _field_family(text: str) -> str | None:
    # Label candidates are deliberately compact.  This prevents a paragraph that
    # begins with a metadata term from becoming a field boundary.
    if not text or len(text.split()) > 8 or len(text) > 100:
        return None
    for family, pattern in _FIELD_FAMILIES:
        if pattern.fullmatch(text):
            return family
    return None


def _has_inline_value(text: str) -> bool:
    """Return whether a compact field candidate also carries a value payload."""
    if ":" not in text:
        return False
    _label, value = text.split(":", 1)
    return bool(value.strip())


def _horizontal_affinity(a: _Box, b: _Box, page_width: float) -> tuple[float, float]:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    overlap_ratio = overlap / max(min(a.width, b.width), 1.0)
    left_delta = abs(a.x0 - b.x0) / max(page_width, 1.0)
    return overlap_ratio, left_delta


def _prose_like(text: str) -> bool:
    words = len(text.split())
    return words >= 18 and bool(_PROSE_END.search(text) or words >= 34)


def _heading_style(region: LayoutRegion, text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    uppercase = (
        bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= 0.8
    )
    return (
        region.get("type") in {"Caption", "Section-header", "Field-heading"}
        or uppercase
    )


def _union_box(regions: list[LayoutRegion]) -> list[float]:
    boxes = [_box(region) for region in regions]
    return [
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    ]


def _logical_value_region(
    members: list[LayoutRegion], field_id: str, family: str
) -> LayoutRegion:
    ordered = sorted(members, key=lambda row: (_box(row).y0, _box(row).x0))
    bbox = _union_box(ordered)
    first = deepcopy(ordered[0])
    source_ids = [str(row["layout_region_id"]) for row in ordered]
    texts = [str(row.get("text") or row.get("orig") or "").strip() for row in ordered]
    first.update(
        {
            "layout_region_id": f"{field_id}:value",
            "type": "Text",
            "docling_label": "text",
            "text": "\n".join(text for text in texts if text),
            "orig": "\n".join(text for text in texts if text),
            "bbox_px": bbox,
            "width_px": bbox[2] - bbox[0],
            "height_px": bbox[3] - bbox[1],
            "area_px": (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
            "source_bbox_px": list(map(float, ordered[0]["bbox_px"])),
            "source_member_bboxes_px": [
                list(map(float, row["bbox_px"])) for row in ordered
            ],
            "source_region_ids": source_ids,
            "source_region_types": [row.get("type") for row in ordered],
            "synthetic_region": True,
            "synthetic_detection_method": "page1_metadata_field_grouping",
            "semantic_role": "metadata_field_value",
            "metadata_field_id": field_id,
            "metadata_field_category": family,
            "resolution_action": "semantic_metadata_value_group",
            "geometry_version": max(
                int(row.get("geometry_version", 1)) for row in ordered
            )
            + 1,
        }
    )
    return first


def normalize_page1_metadata_structure(
    regions: list[LayoutRegion],
    page_map: dict[int, Any],
    config: Page1FilterConfig,
) -> TransformStageResult:
    """Return regions with high-confidence metadata roles and value groups.

    Ambiguous candidates are retained byte-for-byte.  Only values associated with
    the same field are consolidated, and source members remain available through
    provenance and diagnostics.
    """
    if not config.metadata_structure_enabled or 1 not in page_map:
        return TransformStageResult(list(regions), {"enabled": False})

    width, height = _page_size(page_map[1])
    page1 = [deepcopy(row) for row in regions if int(row.get("page_number", -1)) == 1]
    other = [row for row in regions if int(row.get("page_number", -1)) != 1]
    ordered = sorted(page1, key=lambda row: (_box(row).y0, _box(row).x0))
    labels: list[dict[str, Any]] = []
    for index, region in enumerate(ordered):
        text = _text(region)
        family = _field_family(text)
        box = _box(region)
        if (
            family
            and region.get("type") in _HEADING_TYPES
            and box.y0 / height <= config.body_anchor_y_max
            and not _prose_like(text)
        ):
            labels.append(
                {
                    "index": index,
                    "region": region,
                    "family": family,
                    "inline_value": _has_inline_value(text),
                }
            )

    assignments: dict[str, list[LayoutRegion]] = defaultdict(list)
    relationships: list[dict[str, Any]] = []
    claimed: set[str] = set()
    for label_number, label in enumerate(labels):
        label_region = label["region"]
        label_box = _box(label_region)
        field_id = f"p0001:metadata:field:{label_number + 1}"
        if label["inline_value"]:
            label_region["semantic_role"] = "metadata_field_label_and_value"
            label_region["metadata_field_id"] = field_id
            label_region["metadata_field_category"] = label["family"]
            label_region["metadata_relationship_confidence"] = 0.88
        previous_box = label_box
        local_line_height = max(label_box.height, 1.0)
        for candidate in ordered[label["index"] + 1 :]:
            candidate_id = str(candidate["layout_region_id"])
            candidate_box = _box(candidate)
            if candidate_box.y0 < label_box.y0:
                continue
            candidate_text = _text(candidate)
            boundary_overlap, boundary_left = _horizontal_affinity(
                label_box, candidate_box, width
            )
            same_label_column = (
                boundary_overlap >= config.metadata_min_horizontal_overlap
                or boundary_left <= config.metadata_max_left_alignment_delta
            )
            if _field_family(candidate_text) or _BODY_BOUNDARY.match(candidate_text):
                if same_label_column:
                    break
                continue
            if candidate.get("type") not in _VALUE_TYPES or candidate_id in claimed:
                continue
            vertical_gap = max(0.0, candidate_box.y0 - previous_box.y1)
            adaptive_gap = min(
                config.metadata_value_max_vertical_gap * height,
                max(
                    config.metadata_value_min_vertical_gap * height,
                    2.5 * local_line_height,
                ),
            )
            overlap, left_delta = _horizontal_affinity(label_box, candidate_box, width)
            continuation_overlap, continuation_left = _horizontal_affinity(
                previous_box, candidate_box, width
            )
            aligned = (
                overlap >= config.metadata_min_horizontal_overlap
                or left_delta <= config.metadata_max_left_alignment_delta
                or continuation_overlap >= config.metadata_min_horizontal_overlap
                or continuation_left <= config.metadata_max_left_alignment_delta
            )
            if (
                vertical_gap > adaptive_gap
                or not aligned
                or _prose_like(candidate_text)
            ):
                break
            assignments[field_id].append(candidate)
            claimed.add(candidate_id)
            previous_box = candidate_box
            local_line_height = (local_line_height + max(candidate_box.height, 1.0)) / 2

        if assignments[field_id]:
            label_region["semantic_role"] = (
                "metadata_field_label_and_value"
                if label["inline_value"]
                else "metadata_field_label"
            )
            label_region["metadata_field_id"] = field_id
            label_region["metadata_field_category"] = label["family"]
            label_region["metadata_relationship_confidence"] = 0.9
            for value in assignments[field_id]:
                relationships.append(
                    {
                        "kind": "VALUE_OF_METADATA_FIELD",
                        "parent_region_id": str(label_region["layout_region_id"]),
                        "child_region_id": str(value["layout_region_id"]),
                        "metadata_field_id": field_id,
                        "metadata_field_category": label["family"],
                        "status": "associated",
                        "evidence": {
                            "same_page": True,
                            "reading_order_continuation": True,
                            "no_intervening_semantic_boundary": True,
                        },
                    }
                )

    # A container heading is inferred from the field structure below it.  Wording is
    # deliberately not consulted: a compact heading must introduce at least two
    # confidently populated fields.
    populated_labels = [
        label
        for label in labels
        if label["inline_value"]
        or label["region"].get("metadata_field_id") in assignments
    ]
    container_headings: list[LayoutRegion] = []
    if len(populated_labels) >= config.metadata_container_min_fields:
        first_label = populated_labels[0]["region"]
        first_box = _box(first_label)
        for candidate in reversed(ordered[: populated_labels[0]["index"]]):
            candidate_box = _box(candidate)
            candidate_text = _text(candidate)
            gap = max(0.0, first_box.y0 - candidate_box.y1) / height
            overlap, left_delta = _horizontal_affinity(candidate_box, first_box, width)
            if gap > config.metadata_heading_max_vertical_gap:
                break
            if (
                candidate.get("type") in _HEADING_TYPES
                and 0 < len(candidate_text.split()) <= config.metadata_heading_max_words
                and not _prose_like(candidate_text)
                and _field_family(candidate_text) is None
                and _heading_style(candidate, candidate_text)
                and (
                    overlap >= config.metadata_min_horizontal_overlap
                    or left_delta <= config.metadata_max_left_alignment_delta
                )
            ):
                candidate["source_type"] = candidate.get("type")
                candidate["type"] = "Caption"
                candidate["semantic_role"] = "metadata_container_heading"
                candidate["metadata_container_id"] = "p0001:metadata:container:1"
                candidate["metadata_relationship_confidence"] = 0.92
                candidate["caption_scope"] = "metadata"
                container_headings.append(candidate)
                for label in populated_labels:
                    relationships.append(
                        {
                            "kind": "FIELD_OF_METADATA_CONTAINER",
                            "parent_region_id": str(candidate["layout_region_id"]),
                            "child_region_id": str(label["region"]["layout_region_id"]),
                            "metadata_container_id": candidate["metadata_container_id"],
                            "status": "associated",
                        }
                    )
                break

    output_page1: list[LayoutRegion] = []
    grouped_source_ids: set[str] = set()
    logical_values: list[LayoutRegion] = []
    for label in populated_labels:
        field_id = str(label["region"]["metadata_field_id"])
        members = assignments.get(field_id, [])
        family = str(label["family"])
        if not members:
            continue
        if len(members) >= 2:
            logical_values.append(_logical_value_region(members, field_id, family))
            grouped_source_ids.update(
                str(member["layout_region_id"]) for member in members
            )
        else:
            member = members[0]
            member["semantic_role"] = "metadata_field_value"
            member["metadata_field_id"] = field_id
            member["metadata_field_category"] = family

    for region in ordered:
        if str(region["layout_region_id"]) not in grouped_source_ids:
            output_page1.append(region)
    output_page1.extend(logical_values)
    output_page1.sort(key=lambda row: (_box(row).y0, _box(row).x0))

    return TransformStageResult(
        other + output_page1,
        {
            "enabled": True,
            "candidate_label_count": len(labels),
            "populated_field_count": len(populated_labels),
            "container_heading_count": len(container_headings),
            "logical_value_group_count": len(logical_values),
            "grouped_source_region_ids": sorted(grouped_source_ids),
            "relationships": relationships,
            "fields": [
                {
                    "metadata_field_id": label["region"].get("metadata_field_id"),
                    "label_region_id": label["region"].get("layout_region_id"),
                    "category": label["family"],
                    "value_region_ids": [
                        str(row["layout_region_id"])
                        for row in assignments.get(
                            str(label["region"].get("metadata_field_id")), []
                        )
                    ]
                    or (
                        [str(label["region"].get("layout_region_id"))]
                        if label["inline_value"]
                        else []
                    ),
                }
                for label in populated_labels
            ],
        },
    )


__all__ = ["normalize_page1_metadata_structure"]
