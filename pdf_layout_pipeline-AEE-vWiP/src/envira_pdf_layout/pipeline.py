"""Public layout pipeline entry point."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import platform
from time import perf_counter

from .caption_overlap import build_caption_groups
from .caption_association import associate_captions
from .artifact_validation import validate_relationship_graph
from .failures import (
    PipelineIssue,
    PipelineStageError,
    derive_run_status,
    execute_stage,
    page_failure_budget_exceeded,
)
from .figure_decomposition import FigureDecompositionResult, decompose_oversized_figures
from .independent_core import run_independent_core
from .layout_overlap import ResolutionResult, resolve_layout_overlaps
from .nested_containment import (
    HierarchyResult,
    analyze_nested_containment,
    resolve_nested_hierarchy,
)
from .stage_trace import snapshot, validate_trace
from .table_context import associate_table_context
from .region_index import RegionIndex
from .reading_order import assign_document_reading_order
from .schema import initialize_region_schema, normalize_relationship_schema


def run_layout_pipeline(conversion, page_set, config):
    """Run the independent layout core, then infer logical table groups."""
    from .observability import check_cancellation, current_recorder

    recorder = current_recorder()
    check_cancellation()
    if recorder:
        recorder.emit("stage_started", stage="independent_core", status="running")
    started = perf_counter()
    result = run_independent_core(conversion, page_set, config)
    _collect_core_page_failures(result, config)
    if recorder:
        for page_number in result.failed_pages:
            recorder.emit(
                "page_failed",
                stage="independent_core",
                page_number=int(page_number),
                status="failed",
            )
    page_map = {int(page["page_number"]): page for page in result.pages}
    for collection in (result.raw_regions, result.final_regions):
        for region in collection:
            initialize_region_schema(
                region, page_record=page_map.get(int(region["page_number"]))
            )
    core_snapshot = snapshot(
        "independent_core",
        result.final_regions,
        elapsed_ms=(perf_counter() - started) * 1000,
    )
    result.stage_trace = [core_snapshot]
    if recorder:
        recorder.emit(
            "stage_completed",
            stage="independent_core",
            status="completed",
            elapsed_ms=core_snapshot["elapsed_ms"],
        )
    result.filtered_regions = result.final_regions
    result.diagnostics["effective_config"] = config.to_dict()
    result.diagnostics["document"] = {
        "doc_id": result.document.doc_id,
        "pdf_hash": result.document.pdf_hash,
        "page_start": result.document.page_start,
        "page_end": result.document.page_end,
    }
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
        "python_version": platform.python_version(),
        "dependency_versions": {
            package: _package_version(package)
            for package in ("PyMuPDF", "numpy", "opencv-python-headless", "pandas")
        },
    }
    resolution_input = list(result.final_regions)
    resolution_run = execute_stage(
        name="overlap_resolution",
        operation=lambda: resolve_layout_overlaps(
            resolution_input,
            result.pages,
            config.overlap_resolution,
            config.containment,
        ),
        fallback=lambda: ResolutionResult(
            list(resolution_input), [], [], [], {"fallback": "retain_core_regions"}
        ),
        fallback_name="retain_core_regions",
        mode=config.error_policy.mode,
    )
    resolution = resolution_run.value
    result.resolved_regions = resolution.regions
    result.layout_relationships = list(resolution.relationships)
    result.resolution_decisions = resolution.decisions
    result.suppressed_regions = resolution.suppressed
    overlap_snapshot = snapshot(
        "overlap_resolution",
        result.resolved_regions,
        previous=core_snapshot,
        relationships=result.layout_relationships,
        decisions=result.resolution_decisions,
        elapsed_ms=resolution_run.elapsed_ms,
        status=resolution_run.status,
    )
    overlap_snapshot["fallback"] = resolution_run.fallback
    if resolution_run.issue:
        result.issues.append(resolution_run.issue.to_dict())
        result.failed_stages.append("overlap_resolution")
    else:
        result.completed_stages.append("overlap_resolution")
    result.stage_trace.append(overlap_snapshot)
    decomposition_input = list(result.resolved_regions)
    decomposition_run = execute_stage(
        name="figure_decomposition",
        operation=lambda: decompose_oversized_figures(
            decomposition_input,
            result.pages,
            config.figures,
            associate_captions(
                decomposition_input,
                result.pages,
                config=config.caption_association,
            ),
        ),
        fallback=lambda: FigureDecompositionResult(
            list(decomposition_input), [], []
        ),
        fallback_name="preserve_original_figures",
        mode=config.error_policy.mode,
    )
    decomposition = decomposition_run.value
    if decomposition.replaced_regions:
        # Topology changed: rebuild overlap observations and duplicate outcomes from
        # the derived physical regions rather than retaining relationships to a
        # replaced parent.
        reordered, _ = assign_document_reading_order(
            decomposition.regions,
            {int(page["page_number"]): page for page in result.pages},
            config.reading_order,
        )
        rerun = resolve_layout_overlaps(
            reordered,
            result.pages,
            config.overlap_resolution,
            config.containment,
        )
        result.resolved_regions = rerun.regions
        result.layout_relationships = list(rerun.relationships)
        result.resolution_decisions = rerun.decisions
        result.suppressed_regions = list(resolution.suppressed) + list(
            decomposition.replaced_regions
        ) + list(rerun.suppressed)
        effective_resolution = rerun
    else:
        result.resolved_regions = decomposition.regions
        effective_resolution = resolution
    result.diagnostics["figure_decomposition"] = decomposition.diagnostics
    decomposition_snapshot = snapshot(
        "figure_decomposition",
        result.resolved_regions,
        previous=overlap_snapshot,
        decisions=decomposition.proposals,
        elapsed_ms=decomposition_run.elapsed_ms,
        status=decomposition_run.status,
    )
    decomposition_snapshot["fallback"] = decomposition_run.fallback
    result.stage_trace.append(decomposition_snapshot)
    if decomposition_run.issue:
        result.issues.append(decomposition_run.issue.to_dict())
        result.failed_stages.append("figure_decomposition")
    else:
        result.completed_stages.append("figure_decomposition")
    region_index = RegionIndex.build(result.resolved_regions, result.pages)
    containment_metrics: dict[str, int] = {}
    hierarchy_run = execute_stage(
        name="nested_hierarchy",
        operation=lambda: _run_hierarchy(
            result.resolved_regions,
            result.layout_relationships,
            config,
            region_index,
            containment_metrics,
        ),
        fallback=lambda: (
            [],
            HierarchyResult(
                list(result.resolved_regions),
                [],
                [],
                list(result.resolved_regions),
                [],
                {"fallback": "retain_all_top_level"},
            ),
        ),
        fallback_name="retain_all_top_level",
        mode=config.error_policy.mode,
    )
    proposals, hierarchy = hierarchy_run.value
    result.resolved_regions = hierarchy.regions
    result.physical_regions = hierarchy.regions
    result.top_level_regions = hierarchy.top_level_regions
    result.nested_regions = hierarchy.nested_regions
    hierarchy_snapshot = snapshot(
        "nested_hierarchy",
        result.resolved_regions,
        previous=decomposition_snapshot,
        relationships=hierarchy.relationships,
        decisions=hierarchy.decisions,
        elapsed_ms=hierarchy_run.elapsed_ms,
        status=hierarchy_run.status,
    )
    hierarchy_snapshot["fallback"] = hierarchy_run.fallback
    if hierarchy_run.issue:
        result.issues.append(hierarchy_run.issue.to_dict())
        result.failed_stages.append("nested_hierarchy")
    else:
        result.completed_stages.append("nested_hierarchy")
    hierarchy_snapshot["top_level_count"] = len(result.top_level_regions)
    hierarchy_snapshot["nested_count"] = len(result.nested_regions)
    hierarchy_snapshot["invariants"]["partition_valid"] = len(
        result.physical_regions
    ) == len(result.top_level_regions) + len(result.nested_regions)
    result.stage_trace.append(hierarchy_snapshot)
    hierarchy_snapshot["work"] = containment_metrics
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
    caption_metrics: dict[str, int] = {}
    caption_run = execute_stage(
        name="caption_association",
        operation=lambda: associate_captions(
            result.resolved_regions,
            result.pages,
            config=config.caption_association,
            index=region_index,
            metrics=caption_metrics,
        ),
        fallback=lambda: [],
        fallback_name="retain_captions_unattached",
        mode=config.error_policy.mode,
    )
    semantic_associations = caption_run.value
    result.layout_relationships.extend(semantic_associations)
    for relationship in result.layout_relationships:
        normalize_relationship_schema(relationship)
    caption_snapshot = snapshot(
        "caption_association",
        result.resolved_regions,
        previous=hierarchy_snapshot,
        relationships=semantic_associations,
        elapsed_ms=caption_run.elapsed_ms,
        status=caption_run.status,
    )
    caption_snapshot["fallback"] = caption_run.fallback
    if caption_run.issue:
        result.issues.append(caption_run.issue.to_dict())
        result.failed_stages.append("caption_association")
    else:
        result.completed_stages.append("caption_association")
    result.stage_trace.append(caption_snapshot)
    caption_snapshot["work"] = caption_metrics
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
            region["layout_region_id"] for region in result.suppressed_regions
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
        "work": effective_resolution.diagnostics,
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
    started = perf_counter()
    if config.table_context.enabled:
        table_metrics: dict[str, int] = {}
        table_run = execute_stage(
            name="table_context",
            operation=lambda: associate_table_context(
                result.resolved_regions,
                result.pages,
                document_id=result.document.doc_id,
                config=config.table_context,
                relationships=result.layout_relationships,
                index=region_index,
                metrics=table_metrics,
            ),
            fallback=lambda: [],
            fallback_name="omit_logical_tables",
            mode=config.error_policy.mode,
        )
        result.logical_tables = table_run.value
        if table_run.issue:
            result.issues.append(table_run.issue.to_dict())
            result.failed_stages.append("table_context")
        else:
            result.completed_stages.append("table_context")
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
            "work": table_metrics,
        }
        table_elapsed_ms = table_run.elapsed_ms
        caption_group_run = execute_stage(
            name="caption_grouping",
            operation=lambda: build_caption_groups(
                result.resolved_regions,
                result.logical_tables,
                result.caption_overlap_relationships,
                result.pages,
                config.caption_overlap,
            ),
            fallback=lambda: [],
            fallback_name="omit_caption_groups",
            mode=config.error_policy.mode,
        )
        result.caption_groups = caption_group_run.value
        result.semantic_groups = result.caption_groups
        caption_group_elapsed_ms = caption_group_run.elapsed_ms
        if caption_group_run.issue:
            result.issues.append(caption_group_run.issue.to_dict())
            result.failed_stages.append("caption_grouping")
        else:
            result.completed_stages.append("caption_grouping")
    else:
        table_elapsed_ms = 0.0
        caption_group_elapsed_ms = 0.0
        table_run = caption_group_run = None
    semantic_status = (
        "failed_recovered"
        if any(run and run.issue for run in (table_run, caption_group_run))
        else "completed"
    )
    final_snapshot = snapshot(
        "semantic_grouping",
        result.resolved_regions,
        previous=caption_snapshot,
        relationships=result.layout_relationships,
        elapsed_ms=table_elapsed_ms + caption_group_elapsed_ms,
        status=semantic_status,
    )
    final_snapshot["logical_table_count"] = len(result.logical_tables)
    final_snapshot["caption_group_count"] = len(result.caption_groups)
    final_snapshot["table_context_elapsed_ms"] = round(table_elapsed_ms, 3)
    final_snapshot["caption_grouping_elapsed_ms"] = round(caption_group_elapsed_ms, 3)
    graph_validation = validate_relationship_graph(
        result.resolved_regions, result.layout_relationships
    )
    final_snapshot["invariants"]["relationship_graph_valid"] = graph_validation["valid"]
    result.stage_trace.append(final_snapshot)
    result.diagnostics["relationship_graph_validation"] = graph_validation
    result.diagnostics["stage_trace"] = {
        "validation": validate_trace(result.stage_trace),
        "stages": result.stage_trace,
    }
    result.status = derive_run_status(
        [_issue_from_dict(issue) for issue in result.issues], result.failed_pages
    )
    result.diagnostics["run_completeness"] = {
        "run_status": result.status,
        "failed_pages": result.failed_pages,
        "completed_stages": result.completed_stages,
        "failed_stages": result.failed_stages,
        "issues": result.issues,
        "artifacts_complete": result.status in {"complete", "complete_with_warnings"},
    }
    return result


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _run_hierarchy(regions, relationships, config, index, metrics):
    proposals = analyze_nested_containment(
        regions,
        relationships,
        config=config.containment,
        index=index,
        metrics=metrics,
    )
    return proposals, resolve_nested_hierarchy(regions, proposals, config.containment)


def _issue_from_dict(value):
    return PipelineIssue(**{**value, "region_ids": tuple(value.get("region_ids", ()))})


def _collect_core_page_failures(result, config):
    failures = result.diagnostics.get("later_headers", {}).get(
        "pdf_roi_ocr_error_pages", []
    )
    for failure in failures:
        page_number = int(failure["page_number"])
        if page_number not in result.failed_pages:
            result.failed_pages.append(page_number)
        result.issues.append(
            PipelineIssue(
                severity="error",
                category="page_ocr_failure",
                stage="header_roi_ocr",
                page_number=page_number,
                message=str(failure.get("error") or "ROI OCR failed"),
                retryable=True,
            ).to_dict()
        )
    if page_failure_budget_exceeded(
        result.failed_pages,
        len(result.pages),
        max_pages=config.error_policy.max_failed_pages,
        max_ratio=config.error_policy.max_failed_page_ratio,
    ):
        issue = PipelineIssue(
            severity="fatal",
            category="page_failure_budget_exceeded",
            stage="independent_core",
            message="page failure budget exceeded",
            retryable=False,
        )
        if config.error_policy.mode == "strict":
            raise PipelineStageError(issue)
        result.issues.append(issue.to_dict())
        result.failed_stages.append("independent_core")
