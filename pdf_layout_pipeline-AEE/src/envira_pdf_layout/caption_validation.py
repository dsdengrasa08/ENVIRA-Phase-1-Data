"""Semantic validation and conservative splitting of merged caption detections.

The detector observation is never mutated.  Accepted splits are derived regions
which retain the source ID and box; rejected hypotheses remain in diagnostics.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from itertools import product
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
    confidence: float | None = None
    paragraph_start: bool | None = None


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
                        _float_or_none(value.get("confidence")),
                        value.get("paragraph_start"),
                    )
                )
        if lines:
            return sorted(lines, key=lambda line: (line.bbox_px[1], line.bbox_px[0]))
    return []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _median(values: list[float], default: float = 0.0) -> float:
    values = sorted(values)
    if not values:
        return default
    middle = len(values) // 2
    return (
        values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    )


def _line_quality(lines: list[CaptionLine], source_box) -> float:
    """Estimate whether extracted lines are trustworthy enough for segmentation."""
    if not lines:
        return 0.0
    ordered = all(a.bbox_px[1] <= b.bbox_px[1] for a, b in zip(lines, lines[1:]))
    source_area = max(
        1.0, (source_box[2] - source_box[0]) * (source_box[3] - source_box[1])
    )
    inside = 0.0
    for line in lines:
        x0, y0, x1, y1 = line.bbox_px
        inside += max(0.0, min(x1, source_box[2]) - max(x0, source_box[0])) * max(
            0.0, min(y1, source_box[3]) - max(y0, source_box[1])
        )
    confidences = [line.confidence for line in lines if line.confidence is not None]
    confidence = _median(confidences, 0.8)
    coverage = min(1.0, inside / source_area * 3.0)
    return 0.45 * confidence + 0.35 * coverage + (0.20 if ordered else 0.0)


def _lines_fit_source(lines: list[CaptionLine], source_box, tolerance: float) -> bool:
    for line in lines:
        x0, y0, x1, y1 = line.bbox_px
        area = max(1.0, (x1 - x0) * (y1 - y0))
        inside = max(0.0, min(x1, source_box[2]) - max(x0, source_box[0])) * max(
            0.0, min(y1, source_box[3]) - max(y0, source_box[1])
        )
        if 1.0 - inside / area > tolerance:
            return False
    return True


def _boundary_features(
    lines: list[CaptionLine], index: int, config: CaptionValidationConfig
) -> dict[str, Any]:
    previous, current = lines[index - 1], lines[index]
    heights = [max(1.0, line.bbox_px[3] - line.bbox_px[1]) for line in lines]
    typical_height = _median(heights, 1.0)
    gaps = [max(0.0, b.bbox_px[1] - a.bbox_px[3]) for a, b in zip(lines, lines[1:])]
    typical_gap = _median(gaps, 0.0)
    gap = max(0.0, current.bbox_px[1] - previous.bbox_px[3])
    gap_ratio = gap / typical_height
    relative_gap = gap / max(1.0, typical_gap) if typical_gap else gap_ratio
    indent_reset = current.bbox_px[0] <= previous.bbox_px[0] + typical_height * 0.35
    style_before, style_after = previous.typography or {}, current.typography or {}
    style_reset = bool(style_before and style_after and style_before != style_after)
    paragraph = (
        current.paragraph_start is True
        or gap_ratio >= config.min_boundary_gap_line_ratio
        or indent_reset
    )
    return {
        "gap_px": round(gap, 4),
        "gap_line_ratio": round(gap_ratio, 4),
        "relative_gap": round(relative_gap, 4),
        "indent_reset": indent_reset,
        "typography_reset": style_reset,
        "logical_paragraph_start": paragraph,
    }


def _compatible_parent_types(
    config: CaptionValidationConfig, object_type: str
) -> set[str]:
    return next(
        (set(types) for kind, types in config.parent_types if kind == object_type),
        set(),
    )


def _same_column(segment_column, parent) -> bool:
    parent_column = parent.get("reading_order_column")
    return segment_column in {None, "single", parent_column} or parent_column in {
        None,
        "single",
    }


def _has_blocker(segment_box, parent, page_regions) -> bool:
    pb = parent["bbox_px"]
    corridor_top, corridor_bottom = (
        sorted((segment_box[3], pb[1]))
        if segment_box[3] <= pb[1]
        else sorted((pb[3], segment_box[1]))
    )
    for region in page_regions:
        if region is parent or region.get("type") not in {
            "Figure",
            "Table",
            "Formula",
            "Equation",
            "Algorithm",
            "Listing",
            "Code",
        }:
            continue
        rb = region["bbox_px"]
        if (
            rb[1] < corridor_bottom
            and rb[3] > corridor_top
            and _horizontal_overlap(segment_box, rb) >= 0.35
        ):
            return True
    return False


def _best_distinct_assignment(segments):
    """Return the best one-to-one segment/parent assignment and its margin."""
    if not segments or any(not item[3] for item in segments):
        return None, 0.0
    hypotheses = []
    for choices in product(*(item[3] for item in segments)):
        parent_ids = [str(parent["layout_region_id"]) for _, parent in choices]
        if len(set(parent_ids)) != len(parent_ids):
            continue
        hypotheses.append((sum(score for score, _ in choices), choices))
    hypotheses.sort(key=lambda item: item[0], reverse=True)
    if not hypotheses:
        return None, 0.0
    margin = (
        hypotheses[0][0] - hypotheses[1][0] if len(hypotheses) > 1 else float("inf")
    )
    return hypotheses[0][1], margin


def _parent_score(
    segment, object_type, parent, page, config, page_regions=(), segment_column=None
):
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
    compatible = parent_type in _compatible_parent_types(config, object_type)
    if not compatible:
        return None
    if not _same_column(segment_column, parent):
        return None
    if _has_blocker(cb, parent, page_regions):
        return None
    direction = next(
        (value for kind, value in config.preferred_directions if kind == object_type),
        "either",
    )
    caption_below = cb[1] >= pb[3]
    caption_above = cb[3] <= pb[1]
    expected = (
        direction == "either"
        or (direction == "below" and caption_below)
        or (direction == "above" and caption_above)
    )
    score = (
        2.0 * overlap
        + 2.0 * (1.0 - gap / config.max_parent_gap_page_ratio)
        + config.type_match_bonus
        + (
            config.expected_direction_bonus
            if expected
            else -config.expected_direction_bonus / 2
        )
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
        score = _parent_score(leading_box, object_type, parent, page, config, parents)
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
        if (
            score := _parent_score(
                later_box, later_type, candidate, page, config, parents
            )
        )
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
    line_provider: (
        Callable[[LayoutRegion, dict[str, Any]], list[CaptionLine]] | None
    ) = None,
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
    attachable_parent_types = {
        parent_type
        for _, parent_types in config.parent_types
        for parent_type in parent_types
    }
    output: list[LayoutRegion] = []
    decisions: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []

    for region in regions:
        if region.get("type") != "Caption":
            output.append(deepcopy(region))
            continue
        page = page_map[int(region["page_number"])]
        lines = _coerce_lines(region)
        initial_line_source = "structured" if lines else None
        if not lines and config.use_pdf_text_lines:
            lines = _pdf_lines(region, page, pdf_path)
            initial_line_source = "pdf_text" if lines else None
        nearby_assets = [
            candidate
            for candidate in by_page[int(region["page_number"])]
            if candidate.get("type") in attachable_parent_types
            and _horizontal_overlap(region["bbox_px"], candidate["bbox_px"])
            >= config.min_parent_horizontal_overlap
        ]
        quality = _line_quality(lines, region["bbox_px"])
        provider_reason = None
        if (
            line_provider
            and config.use_selective_line_provider
            and len(nearby_assets) >= 2
            and (not lines or quality < config.provider_quality_threshold)
        ):
            # Selective OCR/GLM adapters plug in here and must return line boxes.
            provider_lines = sorted(
                line_provider(region, page),
                key=lambda line: (line.bbox_px[1], line.bbox_px[0]),
            )
            provider_quality = _line_quality(provider_lines, region["bbox_px"])
            if provider_lines and (not lines or provider_quality > quality):
                lines, quality = provider_lines, provider_quality
                provider_reason = (
                    "missing_lines" if not initial_line_source else "low_quality_lines"
                )
        geometry_valid = _lines_fit_source(
            lines, region["bbox_px"], config.max_line_outside_source_ratio
        )
        anchors: list[tuple[int, str, str | None]] = []
        boundary_evidence: dict[int, dict[str, Any]] = {}
        for index, line in enumerate(lines):
            for object_type, pattern in patterns:
                match = pattern.match(line.text)
                if match:
                    if index == 0:
                        anchors.append((index, object_type, match.group("label")))
                    else:
                        evidence = _boundary_features(lines, index, config)
                        boundary_evidence[index] = evidence
                        if evidence["logical_paragraph_start"]:
                            anchors.append((index, object_type, match.group("label")))
                    break
        source_id = str(region["layout_region_id"])
        parents = [
            candidate
            for candidate in by_page[int(region["page_number"])]
            if candidate.get("type") in attachable_parent_types
        ]
        implicit = _implicit_leading_anchor(lines, anchors, parents, page, config)
        if implicit:
            anchors.insert(0, implicit)
        invalid_split_geometry = not geometry_valid and len(anchors) >= 2
        if invalid_split_geometry or len(anchors) < 2 or anchors[0][0] != 0:
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
                        "reason": (
                            "line_geometry_outside_source"
                            if invalid_split_geometry
                            else "first_anchor_not_at_region_start"
                        ),
                        "anchors": anchors,
                        "line_quality": round(quality, 4),
                        "provider_reason": provider_reason,
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
                if (
                    score := _parent_score(
                        bbox,
                        anchor[1],
                        p,
                        page,
                        config,
                        by_page[int(region["page_number"])],
                        region.get("reading_order_column"),
                    )
                )
                is not None
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            segments.append((anchor, member_lines, bbox, scored))

        assignment, assignment_margin = _best_distinct_assignment(segments)
        if assignment:
            # Downstream emission expects the selected parent first while retaining
            # every alternative for diagnostics.
            segments = [
                (
                    anchor,
                    member_lines,
                    bbox,
                    [selected]
                    + [candidate for candidate in scored if candidate != selected],
                )
                for (anchor, member_lines, bbox, scored), selected in zip(
                    segments, assignment
                )
            ]
        parent_unambiguous = bool(
            assignment
            and all(selected[0] > 0 for selected in assignment)
            and assignment_margin >= config.parent_ambiguity_margin
        )
        independent = len(segments) == len(anchors) and parent_unambiguous
        distinct_parents = len(
            {str(item[3][0][1]["layout_region_id"]) for item in segments if item[3]}
        ) == len(segments)
        boundary_score = 0.0
        for anchor in anchors[1:]:
            evidence = boundary_evidence.get(anchor[0], {})
            boundary_score += 1.2
            boundary_score += min(1.2, float(evidence.get("gap_line_ratio", 0.0)))
            boundary_score += (
                0.4
                if float(evidence.get("gap_line_ratio", 0.0))
                >= config.strong_boundary_gap_line_ratio
                else 0.0
            )
            boundary_score += 0.4 if evidence.get("indent_reset") else 0.0
            boundary_score += 0.4 if evidence.get("typography_reset") else 0.0
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
            "reason": (
                "multiple_independent_caption_starts"
                if accepted
                else "insufficient_joint_semantic_spatial_evidence"
            ),
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
            "line_quality": round(quality, 4),
            "provider_reason": provider_reason,
            "boundary_evidence": boundary_evidence,
            "parent_assignment_unambiguous": parent_unambiguous,
            "parent_assignment_margin": (
                None
                if assignment_margin == float("inf")
                else round(assignment_margin, 4)
            ),
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
                caption_line_source=sorted({line.source for line in member_lines}),
                caption_line_count=len(member_lines),
                caption_parent_confidence_margin=(
                    round(scored[0][0] - scored[1][0], 4) if len(scored) > 1 else None
                ),
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
    # Replace each source caption's existing order slot without globally sorting
    # the page and damaging an already-established multi-column reading stream.
    ordered_by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in output:
        ordered_by_page[int(region["page_number"])].append(region)
    for page_regions in ordered_by_page.values():
        page_regions.sort(
            key=lambda item: (
                int(
                    item.get("layout_reading_order")
                    or item.get("resolved_reading_order")
                    or 10**9
                ),
                int(item.get("caption_segment_index") or 0),
                float(item["bbox_px"][1]),
            )
        )
        order = 0
        for item in page_regions:
            if not item.get("nested_parent_region_ids"):
                order += 1
                item["resolved_reading_order"] = order
    return output, decisions, associations
