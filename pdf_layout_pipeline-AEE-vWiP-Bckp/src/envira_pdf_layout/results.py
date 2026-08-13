"""Stable DataFrame views for notebook inspection."""

from __future__ import annotations
import pandas as pd
from .stage_trace import tabular_trace


def page_records_dataframe(page_set):
    return pd.DataFrame([p.to_dict() for p in page_set.pages])


def raw_label_counts_dataframe(regions):
    return pd.DataFrame(
        [
            {"docling_label": k, "count": v}
            for k, v in pd.Series([r["docling_label"] for r in regions])
            .value_counts()
            .items()
        ]
    )


def regions_dataframe(run):
    """Compatibility view of core-filtered regions; prefer explicit hierarchy views."""
    return pd.DataFrame(run.final_regions)


def resolved_regions_dataframe(run):
    """Return duplicate-resolved regions without hiding authoritative regions."""
    return pd.DataFrame(run.resolved_regions)


def top_level_regions_dataframe(run):
    """Return the hierarchy-resolved linear reading stream."""
    return pd.DataFrame(run.top_level_regions)


def nested_regions_dataframe(run):
    """Return accepted children with parent-local order."""
    return pd.DataFrame(run.nested_regions)


def hierarchy_counts_dataframe(run):
    """Return physical/top-level/nested counts for consistency inspection."""
    return pd.DataFrame(
        [
            {
                "physical_regions": len(run.physical_regions),
                "top_level_regions": len(run.top_level_regions),
                "nested_regions": len(run.nested_regions),
                "partition_valid": len(run.physical_regions)
                == len(run.top_level_regions) + len(run.nested_regions),
            }
        ]
    )


def stage_trace_dataframe(run):
    """Show region deltas and validation state across major pipeline stages."""
    return pd.DataFrame(tabular_trace(run.stage_trace))


def figure_completion_proposals_dataframe(run):
    """Return accepted, rejected, and ambiguous completion proposals."""
    return pd.DataFrame(
        run.diagnostics.get("figure_completion", {})
        .get("validation", {})
        .get("proposals", [])
    )


def figure_completion_geometry_summary_dataframe(run):
    proposals = figure_completion_proposals_dataframe(run)
    if not len(proposals):
        return proposals
    return proposals[
        [
            "page_number",
            "figure_region_id",
            "decision",
            "reason",
            "confidence",
            "growth",
            "newly_captured_region_ids",
            "barrier_region_ids",
            "competing_asset_ids",
        ]
    ]


def layout_relationships_dataframe(run):
    """Return every generalized duplicate, hierarchy, conflict, and association edge."""
    return pd.DataFrame(run.layout_relationships)


def resolution_decisions_dataframe(run):
    """Return auditable actions separately from pairwise observations."""
    return pd.DataFrame(run.resolution_decisions)


def suppressed_regions_dataframe(run):
    """Return source detections omitted from the canonical physical view."""
    return pd.DataFrame(run.suppressed_regions)


def caption_groups_dataframe(run):
    return pd.DataFrame(run.caption_groups)


def semantic_captions_dataframe(run):
    """Return one row and one consumer-facing text value per logical caption."""
    columns = [
        "resolved_region_id",
        "page_number",
        "parent_table_id",
        "parent_table_region_id",
        "text",
        "semantic_text_region_ids",
        "ordered_source_region_ids",
        "status",
    ]
    frame = pd.DataFrame(run.caption_groups)
    return frame.reindex(columns=columns)


def region_type_counts_dataframe(run):
    df = regions_dataframe(run)
    return (
        df.groupby(["page_number", "type"]).size().reset_index(name="count")
        if len(df)
        else pd.DataFrame(columns=["page_number", "type", "count"])
    )


def formula_candidates_dataframe(run):
    df = regions_dataframe(run)
    return df[df["type"].isin(["Formula", "Code"])] if len(df) else df


def summary_dataframe(run):
    return pd.DataFrame(
        [
            {
                "doc_id": run.document.doc_id,
                "page_number": p["page_number"],
                **p["counts"],
                "page_image_path": p["page_image_path"],
            }
            for p in run.pages
        ]
    )
