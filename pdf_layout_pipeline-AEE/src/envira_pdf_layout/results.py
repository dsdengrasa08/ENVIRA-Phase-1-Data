"""Stable DataFrame views for notebook inspection."""

from __future__ import annotations
import pandas as pd


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
    return pd.DataFrame(run.final_regions)


def resolved_regions_dataframe(run):
    """Return duplicate-resolved regions without hiding authoritative regions."""
    return pd.DataFrame(run.resolved_regions)


def caption_groups_dataframe(run):
    return pd.DataFrame(run.caption_groups)


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
