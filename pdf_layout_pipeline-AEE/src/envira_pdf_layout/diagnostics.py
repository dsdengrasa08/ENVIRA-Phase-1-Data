"""Convert stored detector decisions into notebook-displayable DataFrames."""

from __future__ import annotations
import pandas as pd


def stage_exclusions(run, stage):
    return pd.DataFrame(run.excluded_by_stage.get(stage, []))


def stage_diagnostics(run, stage):
    value = run.diagnostics.get(stage, {})
    rows = value.get("decisions", []) if isinstance(value, dict) else []
    return pd.DataFrame(rows) if rows else pd.DataFrame([value])


def page1_diagnostics(run):
    return stage_diagnostics(run, "page1")


def header_diagnostics(run):
    return stage_diagnostics(run, "later_headers")


def figure_completion_diagnostics(run):
    return stage_diagnostics(run, "figure_completion")


def footer_diagnostics(run):
    return stage_diagnostics(run, "footer_furniture")


def tail_diagnostics(run):
    return stage_diagnostics(run, "document_tail")


def reading_order_diagnostics(run, page_number):
    return pd.DataFrame(
        [r for r in run.final_regions if r["page_number"] == page_number]
    ).sort_values("layout_reading_order")


def table_context_diagnostics(run, page_number=None):
    """Return accepted table relationships with their explainable features."""
    rows = [
        {
            "internal_id": group["internal_id"],
            "page_number": group["page_number"],
            **association,
        }
        for group in run.logical_tables
        if page_number is None or group["page_number"] == page_number
        for association in group["associations"]
    ]
    return pd.DataFrame(rows)
