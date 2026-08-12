"""Public layout pipeline entry point."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .caption_overlap import build_caption_groups
from .caption_association import associate_captions
from .independent_core import run_independent_core
from .layout_overlap import resolve_layout_overlaps
from .nested_containment import analyze_nested_containment, resolve_nested_hierarchy
from .table_context import associate_table_context


def run_layout_pipeline(conversion, page_set, config):
    """Run the independent layout core, then infer logical table groups."""
    result = run_independent_core(conversion, page_set, config)
    result.filtered_regions = result.final_regions
    result.diagnostics["effective_config"] = config.to_dict()
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
    resolution = resolve_layout_overlaps(
        resolution_input,
        result.pages,
        config.overlap_resolution,
        config.containment,
    )
    result.resolved_regions = resolution.regions
    result.layout_relationships = list(resolution.relationships)
    result.resolution_decisions = resolution.decisions
    result.suppressed_regions = resolution.suppressed
    proposals = analyze_nested_containment(
        result.resolved_regions,
        result.layout_relationships,
        config=config.containment,
    )
    hierarchy = resolve_nested_hierarchy(
        result.resolved_regions, proposals, config.containment
    )
    result.resolved_regions = hierarchy.regions
    result.physical_regions = hierarchy.regions
    result.top_level_regions = hierarchy.top_level_regions
    result.nested_regions = hierarchy.nested_regions
    # Replace observational candidates with exactly one authoritative outcome.
    result.layout_relationships = [
        relation
        for relation in result.layout_relationships
        if relation.get("kind") != "CONTAINMENT_CANDIDATE"
    ]
    result.layout_relationships.extend(hierarchy.relationships)
    result.resolution_decisions.extend(hierarchy.decisions)
    # Backward-compatible caption inspection now receives authoritative rather
    # than provisional containment outcomes.
    result.caption_overlap_relationships = list(result.layout_relationships)
    semantic_associations = associate_captions(
        result.resolved_regions, result.pages, config=config.caption_association
    )
    result.layout_relationships.extend(semantic_associations)
    result.diagnostics["caption_association"] = {
        "candidate_count": len(semantic_associations),
        "associated_count": sum(
            relation["status"] == "associated" for relation in semantic_associations
        ),
        "ambiguous_count": sum(
            relation["status"] == "unresolved_conflict"
            for relation in semantic_associations
        ),
        "unattached_count": sum(
            relation["status"] == "no_compatible_parent"
            for relation in semantic_associations
        ),
        "relationships": semantic_associations,
    }
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
        "recovered_nested_region_count": 0,
        "relationships": result.layout_relationships,
        "decisions": result.resolution_decisions,
    }
    previous_ids = {
        str(decision.get("region_id"))
        for decision in result.diagnostics.get("nested_assets", {}).get("decisions", [])
        if decision.get("region_id")
    }
    proposal_ids = {str(proposal["child_region_id"]) for proposal in proposals}
    result.diagnostics["nested_hierarchy"] = {
        **hierarchy.diagnostics,
        "relationships": hierarchy.relationships,
        "decisions": hierarchy.decisions,
        "top_level_count": len(result.top_level_regions),
        "nested_count": len(result.nested_regions),
        "legacy_comparison": {
            "previous_candidate_ids": sorted(previous_ids),
            "current_candidate_ids": sorted(proposal_ids),
            "matched_ids": sorted(previous_ids & proposal_ids),
            "missing_from_current_ids": sorted(previous_ids - proposal_ids),
            "new_candidate_ids": sorted(proposal_ids - previous_ids),
        },
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
            result.caption_overlap_relationships,
            result.pages,
            config.caption_overlap,
        )
        result.semantic_groups = result.caption_groups
    return result
