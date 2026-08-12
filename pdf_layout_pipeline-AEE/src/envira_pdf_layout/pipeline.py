"""Public layout pipeline entry point."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .modular_pipeline import run_modular_pipeline
from copy import deepcopy

from .caption_overlap import build_caption_groups
from .caption_validation import validate_and_segment_captions
from .layout_overlap import associate_attachable_context, resolve_layout_overlaps
from .table_context import associate_table_context


def run_layout_pipeline(conversion, page_set, config, *, caption_line_provider=None):
    """Run layout processing and infer semantic groups.

    ``caption_line_provider`` is an optional selective OCR/GLM adapter. It is
    called only when a caption has neither structured lines nor usable native PDF
    text, and must return line text with page-pixel bounding boxes.
    """
    result = run_modular_pipeline(conversion, page_set, config)
    try:
        docling_version = version("docling")
    except PackageNotFoundError:
        docling_version = "unknown"
    result.diagnostics["layout_backend"] = {
        "name": "docling",
        "version": docling_version,
        "region_boundary": "docling_document_items",
        "detector_proposals_available": False,
        "detector_confidence_available": any(
            region.get("score") is not None for region in result.raw_regions
        ),
        "nms_configuration": "not_exposed_by_pipeline",
    }
    resolution_input = list(result.final_regions)
    if config.overlap_resolution.preserve_filtered_nested_regions:
        existing_ids = {str(region["layout_region_id"]) for region in resolution_input}
        for excluded in result.excluded_by_stage.get("nested_assets", []):
            region_id = str(excluded.get("layout_region_id"))
            if not region_id or region_id in existing_ids:
                continue
            recovered = deepcopy(excluded)
            recovered["filter_disposition"] = "recovered_for_hierarchy"
            recovered["emission_policy"] = "emit_as_nested_child"
            resolution_input.append(recovered)
            existing_ids.add(region_id)
    resolution = resolve_layout_overlaps(
        resolution_input, result.pages, config.overlap_resolution
    )
    result.resolved_regions = resolution.regions
    result.layout_relationships = list(resolution.relationships)
    # Backward-compatible name used by notebook caption inspection.  The value
    # now contains the complete geometric, class-aware relationship graph.
    result.caption_overlap_relationships = list(resolution.relationships)
    result.resolution_decisions = resolution.decisions
    result.suppressed_regions = resolution.suppressed
    validated, caption_decisions, segment_associations = validate_and_segment_captions(
        result.resolved_regions,
        result.pages,
        config.caption_validation,
        pdf_path=result.document.pdf_path,
        line_provider=caption_line_provider,
    )
    result.resolved_regions = validated
    result.resolution_decisions.extend(caption_decisions)
    result.diagnostics["caption_validation"] = {
        "candidate_count": len(caption_decisions),
        "split_count": sum(item["action"] == "split" for item in caption_decisions),
        "decisions": caption_decisions,
    }
    semantic_associations = associate_attachable_context(
        result.resolved_regions, result.pages
    )
    segmented_ids = {item["child_region_id"] for item in segment_associations}
    semantic_associations = [
        item
        for item in semantic_associations
        if item.get("child_region_id") not in segmented_ids
    ]
    semantic_associations = segment_associations + semantic_associations
    result.layout_relationships.extend(semantic_associations)
    result.diagnostics["caption_overlap"] = {
        "relationship_count": len(result.caption_overlap_relationships),
        "suppressed_duplicate_region_ids": [
            region["layout_region_id"] for region in resolution.suppressed
        ],
        "relationships": result.caption_overlap_relationships,
    }
    result.diagnostics["overlap_resolution"] = {
        "relationship_count": len(result.layout_relationships),
        "decision_count": len(result.resolution_decisions),
        "suppressed_region_count": len(result.suppressed_regions),
        "recovered_nested_region_count": sum(
            region.get("filter_disposition") == "recovered_for_hierarchy"
            for region in result.resolved_regions
        ),
        "relationships": result.layout_relationships,
        "decisions": result.resolution_decisions,
    }
    if config.table_context.enabled:
        result.logical_tables = associate_table_context(
            result.resolved_regions,
            result.pages,
            document_id=result.document.doc_id,
            config=config.table_context,
            relationships=result.layout_relationships,
        )
        groups_by_page: dict[int, list[dict]] = {}
        for group in result.logical_tables:
            groups_by_page.setdefault(group["page_number"], []).append(group)
        for page in result.pages:
            page["logical_tables"] = groups_by_page.get(page["page_number"], [])
        result.diagnostics["table_context"] = {
            "table_count": len(result.logical_tables),
            "associations": [
                association
                for group in result.logical_tables
                for association in group["associations"]
            ],
        }
    result.caption_groups = build_caption_groups(
        result.resolved_regions,
        result.logical_tables,
        result.layout_relationships,
        result.pages,
        config.caption_overlap,
    )
    return result
