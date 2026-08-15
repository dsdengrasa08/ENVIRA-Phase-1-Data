"""Validate figure-completion geometry before it affects downstream stages."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from .geometry import bbox_area, intersection_area
from .types import LayoutRegion
from .schema import (
    COMPLETION_PROPOSAL_SCHEMA_VERSION,
    apply_geometry_change,
    initialize_region_schema,
)

HARD_BARRIER_TYPES = {"Table", "Figure", "Section-header", "Title"}
SOFT_CONTENT_TYPES = {"Formula", "Equation", "Code"}


@dataclass(frozen=True)
class FigureCompletionProposal:
    proposal_schema_version: int
    proposal_id: str
    figure_region_id: str
    page_number: int
    source_bbox_px: list[float]
    proposed_bbox_px: list[float]
    visual_crop_bbox_px: list[float]
    semantic_group_bbox_px: list[float]
    caption_region_id: str | None
    caption_assignment_score: float
    newly_captured_region_ids: tuple[str, ...]
    newly_captured_classes: tuple[str, ...]
    barrier_region_ids: tuple[str, ...]
    competing_asset_ids: tuple[str, ...]
    crosses_column_gutter: bool
    growth: dict[str, float]
    decision: str
    reason: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FigureCompletionResult:
    regions: list[LayoutRegion]
    proposals: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def _coverage(inner: list[float], outer: list[float]) -> float:
    area = bbox_area(tuple(inner))
    return intersection_area(tuple(inner), tuple(outer)) / area if area else 0.0


def _newly_captured(
    figure: LayoutRegion,
    regions: list[LayoutRegion],
    source_bbox: list[float],
    proposed_bbox: list[float],
) -> list[LayoutRegion]:
    result = []
    figure_id = str(figure["layout_region_id"])
    caption_id = str(figure.get("figure_completion_caption_region_id") or "")
    for region in regions:
        region_id = str(region.get("layout_region_id"))
        if region_id in {figure_id, caption_id} or region.get(
            "page_number"
        ) != figure.get("page_number"):
            continue
        bbox = list(map(float, region.get("bbox_px", [])))
        if len(bbox) != 4:
            continue
        if _coverage(bbox, proposed_bbox) >= 0.5 and _coverage(bbox, source_bbox) < 0.5:
            result.append(region)
    return result


def _is_hard_barrier(region: LayoutRegion, paragraph_min_chars: int) -> bool:
    kind = str(region.get("type") or "Unknown")
    text = " ".join(str(region.get("text") or region.get("orig") or "").split())
    if kind in HARD_BARRIER_TYPES:
        return True
    if kind == "Caption":
        return True
    return kind in {"Text", "List", "Reference"} and len(text) >= paragraph_min_chars


def validate_figure_completions(
    regions: list[LayoutRegion],
    context_regions: list[LayoutRegion],
    *,
    max_area_multiplier: float = 4.0,
    max_page_area_ratio: float = 0.65,
    max_edge_growth_ratio: float = 0.45,
    paragraph_min_chars: int = 80,
    min_assignment_score: float = 7.0,
    pages: list[dict[str, Any]] | None = None,
) -> FigureCompletionResult:
    """Promote safe proposals and restore source geometry for unsafe proposals."""
    working = deepcopy(regions)
    proposals: list[dict[str, Any]] = []
    page_map = {int(page["page_number"]): page for page in pages or []}
    for figure in working:
        source = figure.get("figure_completion_original_bbox_px")
        proposed = figure.get("bbox_px")
        if not source or not proposed:
            initialize_region_schema(
                figure, page_record=page_map.get(int(figure["page_number"]))
            )
            continue
        source = list(map(float, source))
        proposed = list(map(float, proposed))
        source_area = bbox_area(tuple(source))
        page = page_map.get(int(figure["page_number"]), {})
        page_width = float(page.get("image_width_px") or page.get("width_px") or 0)
        page_height = float(page.get("image_height_px") or page.get("height_px") or 0)
        if page_width <= 0 or page_height <= 0:
            page_width = max(
                [
                    float(r["bbox_px"][2])
                    for r in context_regions
                    if r.get("page_number") == figure.get("page_number")
                ]
                + [proposed[2], 1.0]
            )
            page_height = max(
                [
                    float(r["bbox_px"][3])
                    for r in context_regions
                    if r.get("page_number") == figure.get("page_number")
                ]
                + [proposed[3], 1.0]
            )
        proposed = [
            max(0.0, min(page_width, proposed[0])),
            max(0.0, min(page_height, proposed[1])),
            max(0.0, min(page_width, proposed[2])),
            max(0.0, min(page_height, proposed[3])),
        ]
        proposed_area = bbox_area(tuple(proposed))
        growth = {
            "left": max(0.0, source[0] - proposed[0]) / page_width,
            "top": max(0.0, source[1] - proposed[1]) / page_height,
            "right": max(0.0, proposed[2] - source[2]) / page_width,
            "bottom": max(0.0, proposed[3] - source[3]) / page_height,
            "area_multiplier": proposed_area / source_area
            if source_area
            else float("inf"),
            "page_area_ratio": proposed_area / max(page_width * page_height, 1.0),
        }
        captured = _newly_captured(figure, context_regions, source, proposed)
        barriers = [r for r in captured if _is_hard_barrier(r, paragraph_min_chars)]
        competing = [r for r in captured if r.get("type") in {"Figure", "Table"}]
        assignment_score = float(
            figure.get("figure_completion_assignment_score") or 0.0
        )
        page_text = [
            r
            for r in context_regions
            if r.get("page_number") == figure.get("page_number")
            and r.get("type") == "Text"
            and len(str(r.get("text") or "")) >= paragraph_min_chars
        ]
        left_column = any(
            float(r["bbox_px"][2]) <= page_width * 0.55 for r in page_text
        )
        right_column = any(
            float(r["bbox_px"][0]) >= page_width * 0.45 for r in page_text
        )
        crosses_column_gutter = bool(
            left_column
            and right_column
            and source[2] <= page_width * 0.60
            and proposed[2] >= page_width * 0.70
        )
        excessive = (
            growth["area_multiplier"] > max_area_multiplier
            or growth["page_area_ratio"] > max_page_area_ratio
            or max(growth[k] for k in ("left", "top", "right", "bottom"))
            > max_edge_growth_ratio
        )
        if assignment_score < min_assignment_score:
            decision, reason, confidence = (
                "ambiguous_visual_evidence",
                "caption_assignment_below_threshold",
                "low",
            )
        elif competing:
            decision, reason, confidence = (
                "ambiguous_competing_asset",
                "proposal_captures_competing_asset",
                "low",
            )
        elif barriers or crosses_column_gutter:
            decision = "rejected_barrier_crossing"
            reason = (
                "proposal_crosses_column_gutter"
                if crosses_column_gutter
                else "proposal_captures_structural_barrier"
            )
            confidence = "high"
        elif excessive:
            decision, reason, confidence = (
                "rejected_excessive_growth",
                "proposal_exceeds_growth_limits",
                "high",
            )
        else:
            compatible = bool(captured) and all(
                r.get("type") in SOFT_CONTENT_TYPES
                or len(str(r.get("text") or "")) < paragraph_min_chars
                for r in captured
            )
            decision = "accepted_with_nested_content" if compatible else "accepted"
            reason, confidence = "validated_completion_geometry", "high"

        accepted = decision.startswith("accepted")
        resolved = proposed if accepted else source
        visual_crop = list(
            figure.get("figure_completion_candidate_bbox_px") or resolved
        )
        semantic_group = proposed if accepted else source
        figure["bbox_px"] = source
        figure["resolved_bbox_px"] = source
        figure["physical_bbox_px"] = source
        figure["source_bbox_px"] = source
        initialize_region_schema(figure, page_record=page)
        apply_geometry_change(
            figure,
            proposed,
            stage="figure_completion",
            reason=reason,
            accepted=accepted,
            page_record=page,
        )
        figure["visual_crop_bbox_px"] = visual_crop
        figure["semantic_group_bbox_px"] = semantic_group
        figure["figure_completion_decision"] = decision
        figure["figure_completion_decision_reason"] = reason
        proposal = FigureCompletionProposal(
            proposal_schema_version=COMPLETION_PROPOSAL_SCHEMA_VERSION,
            proposal_id=f"p{int(figure['page_number'])}:{figure['layout_region_id']}:completion",
            figure_region_id=str(figure["layout_region_id"]),
            page_number=int(figure["page_number"]),
            source_bbox_px=source,
            proposed_bbox_px=proposed,
            visual_crop_bbox_px=visual_crop,
            semantic_group_bbox_px=semantic_group,
            caption_region_id=figure.get("figure_completion_caption_region_id"),
            caption_assignment_score=assignment_score,
            newly_captured_region_ids=tuple(
                str(r["layout_region_id"]) for r in captured
            ),
            newly_captured_classes=tuple(
                str(r.get("type") or "Unknown") for r in captured
            ),
            barrier_region_ids=tuple(str(r["layout_region_id"]) for r in barriers),
            competing_asset_ids=tuple(str(r["layout_region_id"]) for r in competing),
            crosses_column_gutter=crosses_column_gutter,
            growth=growth,
            decision=decision,
            reason=reason,
            confidence=confidence,
        ).to_dict()
        proposals.append(proposal)
    diagnostics = {
        "proposal_count": len(proposals),
        "accepted_count": sum(p["decision"].startswith("accepted") for p in proposals),
        "rejected_count": sum(p["decision"].startswith("rejected") for p in proposals),
        "ambiguous_count": sum(
            p["decision"].startswith("ambiguous") for p in proposals
        ),
        "proposals": proposals,
    }
    return FigureCompletionResult(working, proposals, diagnostics)
