"""Serialization of pipeline results without detection side effects."""

from __future__ import annotations
import json
from .results import summary_dataframe
from .types import ExportManifest


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def export_pipeline_result(run):
    paths = run.document.artifacts
    paths.raw_json.write_text(
        json.dumps(run.raw_document, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    paths.raw_markdown.write_text(run.raw_markdown, encoding="utf-8")
    _write_jsonl(paths.page_records_jsonl, run.pages)
    _write_jsonl(paths.regions_jsonl, run.final_regions)
    _write_jsonl(paths.raw_regions_jsonl, run.raw_regions)
    _write_jsonl(paths.resolved_regions_jsonl, run.resolved_regions)
    _write_jsonl(paths.caption_relationships_jsonl, run.caption_overlap_relationships)
    _write_jsonl(paths.caption_groups_jsonl, run.caption_groups)
    _write_jsonl(paths.post_body_assets_jsonl, run.post_body_assets)
    _write_jsonl(paths.post_body_asset_regions_jsonl, run.post_body_asset_regions)
    _write_jsonl(paths.logical_tables_jsonl, run.logical_tables)
    summary_dataframe(run).to_csv(paths.summary_csv, index=False)
    return ExportManifest(
        (
            paths.raw_json,
            paths.raw_markdown,
            paths.page_records_jsonl,
            paths.regions_jsonl,
            paths.post_body_assets_jsonl,
            paths.post_body_asset_regions_jsonl,
            paths.logical_tables_jsonl,
            paths.raw_regions_jsonl,
            paths.resolved_regions_jsonl,
            paths.caption_relationships_jsonl,
            paths.caption_groups_jsonl,
            paths.summary_csv,
        )
    )
