"""Infer logical table context without changing physical layout detections."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from .config import TableContextConfig
from .types import LayoutRegion

_TABLE_LABEL_RE = re.compile(
    r"^\s*(?P<label>(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?:table|tab\.)\s+(?:[A-Z](?:[.\-]?\d+)?|[IVXLCDM]+|\d+(?:[.\-]\w+)?))"
    r"(?:\s*[:.\-])?(?:\s+|$)",
    re.IGNORECASE,
)
_NOTE_RE = re.compile(
    r"^\s*(?:notes?|sources?)\s*:|^\s*(?:[*†‡]|[a-z])(?:[.)]|\s{1,3})\s+|"
    r"\b[pP]\s*[<=>]\s*\.?\d+",
    re.IGNORECASE,
)
_BODY_SENTENCE_RE = re.compile(r"^[A-Z][^.!?]{35,}[.!?](?:\s|$)")
_TEXT_TYPES = {"Text", "Caption", "Footnote", "Section-header", "Title", "List"}
_BOUNDARY_TYPES = {"Table", "Figure", "Section-header", "Title"}


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


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
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    above = cb[3] <= tb[1] + tolerance and cb[1] < tb[1]
    below = cb[1] >= tb[3] - tolerance and cb[3] > tb[3]
    if not (above or below) or candidate.get("type") not in _TEXT_TYPES:
        return None
    gap = (tb[1] - cb[3]) if above else (cb[1] - tb[3])
    gap_page = max(0.0, gap) / page_height
    overlap = _overlap_ratio(cb, tb)
    if gap_page > config.max_vertical_gap_page_ratio:
        return None
    if overlap < config.min_horizontal_overlap_ratio:
        return None
    if not _column_compatible(candidate, table, page_width):
        return None
    blocker = _has_blocker(candidate, table, page_regions)
    if blocker:
        return None

    text = str(candidate.get("text") or "").strip()
    label_match = _TABLE_LABEL_RE.match(text)
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
    direction_ok = (role == "caption" and above) or (role == "note" and below)
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
        "direction": "above" if above else "below",
        "features": {
            "gap_page_ratio": round(gap_page, 6),
            "boundary_overlap_page_ratio": round(max(0.0, -gap) / page_height, 6),
            "horizontal_overlap_ratio": round(overlap, 6),
            "reading_order_delta": order_delta,
            "components": components,
        },
        "printed_label": label_match.group("label").strip() if label_match else None,
        "caption_text_after_label": bool(
            label_match and text[label_match.end() :].strip()
        ),
    }


def _group_bbox(regions: list[LayoutRegion]) -> list[float]:
    boxes = [list(map(float, region["bbox_px"])) for region in regions]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def associate_table_context(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    *,
    document_id: str,
    config: TableContextConfig | None = None,
) -> list[dict[str, Any]]:
    """Create table groups using constrained, explainable relationship scoring.

    Raw regions are referenced by ID and are never reclassified or resized.
    Candidate regions have exclusive ownership; uncertain competing assignments
    are deliberately left unattached.
    """
    config = config or TableContextConfig()
    page_sizes = {int(page["page_number"]): _page_size(page) for page in pages}
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in regions:
        by_page[int(region["page_number"])].append(region)

    groups: list[dict[str, Any]] = []
    for page_number in sorted(by_page):
        page_regions = by_page[page_number]
        tables = sorted(
            (region for region in page_regions if region.get("type") == "Table"),
            key=lambda region: (
                int(region.get("layout_reading_order") or 10**9),
                float(region["bbox_px"][1]),
                float(region["bbox_px"][0]),
            ),
        )
        width, height = page_sizes.get(page_number, (1.0, 1.0))
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
                "note_region_ids": [],
                "printed_label": None,
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
                for role in ("caption", "note"):
                    edge = _score_edge(
                        candidate, table, role, page_regions, width, height, config
                    )
                    if edge and edge["score"] >= config.acceptance_score:
                        edges.append(edge)

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
            region = region_by_id[region_id]
            if winner["proposed_role"] == "caption":
                if winner["printed_label"]:
                    group["identifier_region_ids"].append(region_id)
                    group["printed_label"] = (
                        group["printed_label"] or winner["printed_label"]
                    )
                    if winner["caption_text_after_label"]:
                        group["caption_region_ids"].append(region_id)
                else:
                    group["caption_region_ids"].append(region_id)
            else:
                group["note_region_ids"].append(region_id)
            group["associations"].append(winner)

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
            groups.append(group)
    return groups
