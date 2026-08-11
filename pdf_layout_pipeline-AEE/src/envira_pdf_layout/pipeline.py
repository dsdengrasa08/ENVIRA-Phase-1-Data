"""Public layout pipeline entry point."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .authoritative import run_authoritative_pipeline
from .caption_overlap import build_caption_groups, resolve_caption_overlaps
from .table_context import associate_table_context


def run_layout_pipeline(conversion, page_set, config):
    """Run authoritative layout processing, then infer logical table groups."""
    result = run_authoritative_pipeline(conversion, page_set, config)
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
    (
        result.resolved_regions,
        result.caption_overlap_relationships,
        suppressed_duplicates,
    ) = resolve_caption_overlaps(
        result.final_regions, result.pages, config.caption_overlap
    )
    result.diagnostics["caption_overlap"] = {
        "relationship_count": len(result.caption_overlap_relationships),
        "suppressed_duplicate_region_ids": [
            region["layout_region_id"] for region in suppressed_duplicates
        ],
        "relationships": result.caption_overlap_relationships,
    }
    if config.table_context.enabled:
        result.logical_tables = associate_table_context(
            result.resolved_regions,
            result.pages,
            document_id=result.document.doc_id,
            config=config.table_context,
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
            result.caption_overlap_relationships,
            result.pages,
            config.caption_overlap,
        )
    return result
