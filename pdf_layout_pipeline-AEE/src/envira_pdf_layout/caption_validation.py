"""Semantic validation and conservative splitting of merged caption detections.

The detector observation is never mutated.  Accepted splits are derived regions
which retain the source ID and box; rejected hypotheses remain in diagnostics.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Callable

from .config import CaptionValidationConfig
from .types import LayoutRegion


_IDENTIFIER = r"(?:[A-Z](?:[.\-]?\d+)?|[IVXLCDM]+|\d+(?:[.\-][A-Za-z0-9]+)*)"


@dataclass(frozen=True)
class CaptionLine:
    text: str
    bbox_px: tuple[float, float, float, float]
    typography: dict[str, Any] | None = None
    source: str = "region"


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _anchor_patterns(config: CaptionValidationConfig):
    patterns = []
    for object_type, aliases in config.prefixes:
        alias_pattern = "|".join(
            sorted((re.escape(alias) for alias in aliases), key=len, reverse=True)
        )
        patterns.append(
            (
                object_type,
                re.compile(
                    rf"^\s*(?P<label>(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
                    rf"(?:{alias_pattern})\s+{_IDENTIFIER})(?:\s*[:.\-])?(?:\s+|$)",
                    re.IGNORECASE,
                ),
            )
        )
    return patterns


def _coerce_lines(region: LayoutRegion) -> list[CaptionLine]:
    """Reuse structured extraction attached by Docling/OCR integrations."""
    for key in ("text_lines", "ocr_lines", "lines"):
        values = region.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines = []
        for value in values:
            if not isinstance(value, dict):
                continue
            bbox = value.get("bbox_px") or value.get("bbox")
            text = str(value.get("text") or "").strip()
            if text and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                lines.append(
                    CaptionLine(
                        text,
                        tuple(map(float, bbox)),
                        value.get("typography"),
                        str(value.get("source") or key),
                    )
                )
        if lines:
            return sorted(lines, key=lambda line: (line.bbox_px[1], line.bbox_px[0]))
    return []


def _pdf_lines(
    region: LayoutRegion, page: dict[str, Any], pdf_path
) -> list[CaptionLine]:
    """Extract native PDF words in a caption crop; do not run duplicate OCR."""
    if not pdf_path:
        return []
    try:
        import fitz

        page_number = int(region["page_number"])
        document = fitz.open(str(pdf_path))
        pdf_page = document.load_page(page_number - 1)
        width_px, height_px = _page_size(page)
        sx, sy = width_px / pdf_page.rect.width, height_px / pdf_page.rect.height
        box = list(map(float, region["bbox_px"]))
        clip = fitz.Rect(box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy)
        words = pdf_page.get_text("words", clip=clip, sort=True)
        document.close()
    except Exception:
        return []
    grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for word in words:
        grouped[(int(word[5]), int(word[6]))].append(word)
    lines = []
    for words_in_line in grouped.values():
        words_in_line.sort(key=lambda word: word[0])
        lines.append(
            CaptionLine(
                " ".join(str(word[4]) for word in words_in_line),
                (
                    min(word[0] for word in words_in_line) * sx,
                    min(word[1] for word in words_in_line) * sy,
                    max(word[2] for word in words_in_line) * sx,
                    max(word[3] for word in words_in_line) * sy,
                ),
                source="pdf_text",
            )
        )
    return sorted(lines, key=lambda line: (line.bbox_px[1], line.bbox_px[0]))


def _horizontal_overlap(a, b) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _union(lines: list[CaptionLine]) -> list[float]:
    return [
        min(line.bbox_px[0] for line in lines),
        min(line.bbox_px[1] for line in lines),
        max(line.bbox_px[2] for line in lines),
        max(line.bbox_px[3] for line in lines),
    ]


def _parent_score(segment, object_type, parent, page, config):
    cb, pb = segment, list(map(float, parent["bbox_px"]))
    _, height = _page_size(page)
    overlap = _horizontal_overlap(cb, pb)
    gap = max(0.0, max(cb[1], pb[1]) - min(cb[3], pb[3])) / height
    if (
        overlap < config.min_parent_horizontal_overlap
        or gap > config.max_parent_gap_page_ratio
    ):
        return None
    parent_type = str(parent.get("type") or "")
    compatible = object_type == parent_type or (
        object_type == "Formula" and parent_type in {"Formula", "Equation"}
    )
    caption_below = cb[1] >= pb[3]
    expected = caption_below if object_type == "Figure" else cb[3] <= pb[1]
    score = (
        2.0 * overlap
        + 2.0 * (1.0 - gap / config.max_parent_gap_page_ratio)
        + (config.type_match_bonus if compatible else -config.type_mismatch_penalty)
        + (config.expected_direction_bonus if expected else 0.0)
    )
    return score


def _implicit_leading_anchor(
    lines: list[CaptionLine],
    anchors: list[tuple[int, str, str | None]],
    parents: list[LayoutRegion],
    page: dict[str, Any],
    config: CaptionValidationConfig,
) -> tuple[int, str, None] | None:
    """Infer a missing first label only from strong independent object geometry.

    PDF extraction can omit a small bold/italic ``Fig. N`` span even though the
    detector correctly classified the enclosing region as Caption.  A later
    explicit anchor must still exist, and the leading lines must have a positive,
    type-compatible parent which differs from that later anchor's best parent.
    This is deliberately not a text-keyword fallback.
    """
    if not anchors or anchors[0][0] <= 0:
        return None
    leading_box = _union(lines[: anchors[0][0]])
    scored = []
    for parent in parents:
        parent_type = str(parent.get("type") or "")
        object_type = "Formula" if parent_type == "Equation" else parent_type
        score = _parent_score(leading_box, object_type, parent, page, config)
        if score is not None and score > 0:
            scored.append((score, object_type, parent))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    _, object_type, parent = scored[0]

    later_index, later_type, _ = anchors[0]
    later_box = _union(lines[later_index:])
    later = [
        (score, candidate)
        for candidate in parents
        if (score := _parent_score(later_box, later_type, candidate, page, config))
        is not None
    ]
    later.sort(key=lambda item: item[0], reverse=True)
    if not later or later[0][0] <= 0:
        return None
    if str(parent["layout_region_id"]) == str(later[0][1]["layout_region_id"]):
        return None
    return (0, object_type, None)


def validate_and_segment_captions(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    config: CaptionValidationConfig | None = None,
    *,
    pdf_path=None,
    line_provider: Callable[[LayoutRegion, dict[str, Any]], list[CaptionLine]]
    | None = None,
) -> tuple[list[LayoutRegion], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return semantic regions, segmentation decisions, and parent associations."""
    config = config or CaptionValidationConfig()
    if not config.enabled:
        return deepcopy(regions), [], []
    page_map = {int(page["page_number"]): page for page in pages}
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in regions:
        by_page[int(region["page_number"])].append(region)
    patterns = _anchor_patterns(config)
    output: list[LayoutRegion] = []
    decisions: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []

    for region in regions:
        if region.get("type") != "Caption":
            output.append(deepcopy(region))
            continue
        page = page_map[int(region["page_number"])]
        lines = _coerce_lines(region)
        if not lines and config.use_pdf_text_lines:
            lines = _pdf_lines(region, page, pdf_path)
        nearby_assets = [
            candidate
            for candidate in by_page[int(region["page_number"])]
            if candidate.get("type") in {"Figure", "Table", "Formula", "Equation"}
            and _horizontal_overlap(region["bbox_px"], candidate["bbox_px"])
            >= config.min_parent_horizontal_overlap
        ]
        if not lines and line_provider and len(nearby_assets) >= 2:
            # Selective OCR/GLM adapters plug in here and must return line boxes.
            lines = line_provider(region, page)
        anchors: list[tuple[int, str, str | None]] = []
        for index, line in enumerate(lines):
            for object_type, pattern in patterns:
                match = pattern.match(line.text)
                if match:
                    anchors.append((index, object_type, match.group("label")))
                    break
        source_id = str(region["layout_region_id"])
        parents = [
            candidate
            for candidate in by_page[int(region["page_number"])]
            if candidate.get("type") in {"Figure", "Table", "Formula", "Equation"}
        ]
        implicit = _implicit_leading_anchor(lines, anchors, parents, page, config)
        if implicit:
            anchors.insert(0, implicit)
        if len(anchors) < 2 or anchors[0][0] != 0:
            kept = deepcopy(region)
            kept["caption_validation_status"] = (
                "single" if len(anchors) <= 1 else "ambiguous"
            )
            output.append(kept)
            if len(anchors) > 1:
                decisions.append(
                    {
                        "source_region_id": source_id,
                        "action": "retain",
                        "reason": "first_anchor_not_at_region_start",
                        "anchors": anchors,
                    }
                )
            continue

        segments = []
        for position, anchor in enumerate(anchors):
            start = anchor[0]
            end = (
                anchors[position + 1][0] if position + 1 < len(anchors) else len(lines)
            )
            member_lines = lines[start:end]
            if len(member_lines) < config.min_segment_lines:
                continue
            bbox = _union(member_lines)
            scored = [
                (score, p)
                for p in parents
                if (score := _parent_score(bbox, anchor[1], p, page, config))
                is not None
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            segments.append((anchor, member_lines, bbox, scored))

        independent = len(segments) == len(anchors) and all(
            item[3] and item[3][0][0] > 0 for item in segments
        )
        distinct_parents = len(
            {str(item[3][0][1]["layout_region_id"]) for item in segments if item[3]}
        ) == len(segments)
        boundary_score = 2.0 * (len(segments) - 1)
        parent_score = sum(min(4.0, item[3][0][0]) for item in segments if item[3])
        split_score = boundary_score + parent_score + (1.0 if distinct_parents else 0.0)
        null_score = max(
            (score for item in segments for score, _ in item[3]), default=0.0
        )
        accepted = (
            independent
            and distinct_parents
            and split_score >= config.split_acceptance_score
            and split_score - null_score >= config.split_margin
        )
        decision = {
            "source_region_id": source_id,
            "action": "split" if accepted else "retain",
            "reason": "multiple_independent_caption_starts"
            if accepted
            else "insufficient_joint_semantic_spatial_evidence",
            "split_score": round(split_score, 4),
            "null_score": round(null_score, 4),
            "anchors": [
                {
                    "line_index": a[0],
                    "object_type": a[1],
                    "label": a[2],
                    "implicit": a[2] is None,
                }
                for a in anchors
            ],
            "text_source": sorted({line.source for line in lines}),
        }
        decisions.append(decision)
        if not accepted:
            kept = deepcopy(region)
            kept["caption_validation_status"] = (
                "ambiguous" if split_score >= config.review_score else "single"
            )
            kept["caption_split_candidate"] = decision
            output.append(kept)
            continue

        for ordinal, (anchor, member_lines, bbox, scored) in enumerate(segments, 1):
            parent_score_value, parent = scored[0]
            derived_id = f"{source_id}:caption:{ordinal}"
            derived = deepcopy(region)
            derived.update(
                layout_region_id=derived_id,
                type="Caption",
                text=" ".join(line.text.strip() for line in member_lines).strip(),
                bbox_px=bbox,
                resolved_bbox_px=bbox,
                width_px=bbox[2] - bbox[0],
                height_px=bbox[3] - bbox[1],
                area_px=(bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
                source_region_ids=list(
                    dict.fromkeys(
                        region.get("source_region_ids", [source_id]) + [source_id]
                    )
                ),
                source_bbox_px=list(region["bbox_px"]),
                derived_from_region_id=source_id,
                caption_segment_index=ordinal,
                caption_object_type=anchor[1],
                caption_identifier=anchor[2],
                caption_validation_status="split",
                resolution_action="semantic_caption_split",
                geometry_version=int(region.get("geometry_version", 1)) + 1,
            )
            output.append(derived)
            associations.append(
                {
                    "relationship_id": f"p{region['page_number']}:caption-segment:{derived_id}",
                    "page_number": region["page_number"],
                    "kind": "CAPTION_OF",
                    "child_region_id": derived_id,
                    "parent_region_id": str(parent["layout_region_id"]),
                    "candidate_parent_region_ids": [
                        str(candidate["layout_region_id"]) for _, candidate in scored
                    ],
                    "confidence": round(parent_score_value, 4),
                    "status": "associated",
                    "proposed_action": "associate",
                    "features": {
                        "caption_object_type": anchor[1],
                        "source_region_id": source_id,
                    },
                }
            )
    # Reconstruct stable page-local resolved order after one-to-many replacement.
    ordered_by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in output:
        ordered_by_page[int(region["page_number"])].append(region)
    for page_regions in ordered_by_page.values():
        page_regions.sort(
            key=lambda item: (float(item["bbox_px"][1]), float(item["bbox_px"][0]))
        )
        for order, item in enumerate(page_regions, 1):
            if not item.get("nested_parent_region_ids"):
                item["resolved_reading_order"] = order
    return output, decisions, associations
