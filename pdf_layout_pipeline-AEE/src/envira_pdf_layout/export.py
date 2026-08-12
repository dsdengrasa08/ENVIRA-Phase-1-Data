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
    config = getattr(run, "config", None)
    options = getattr(config, "export", None)
    write_raw = True if options is None else options.write_raw
    write_regions = True if options is None else options.write_regions
    write_overlays = True if options is None else options.write_overlays
    files = []
    if write_raw:
        paths.raw_json.write_text(
            json.dumps(run.raw_document, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        paths.raw_markdown.write_text(run.raw_markdown, encoding="utf-8")
        _write_jsonl(paths.raw_regions_jsonl, run.raw_regions)
        files.extend((paths.raw_json, paths.raw_markdown, paths.raw_regions_jsonl))
    _write_jsonl(paths.page_records_jsonl, run.pages)
    files.append(paths.page_records_jsonl)
    if write_regions:
        for path, rows in (
            (paths.regions_jsonl, run.final_regions),
            (paths.resolved_regions_jsonl, run.resolved_regions),
            (paths.caption_relationships_jsonl, run.caption_overlap_relationships),
            (paths.caption_groups_jsonl, run.caption_groups),
            (paths.layout_relationships_jsonl, run.layout_relationships),
            (paths.resolution_decisions_jsonl, run.resolution_decisions),
            (paths.suppressed_regions_jsonl, run.suppressed_regions),
            (paths.post_body_assets_jsonl, run.post_body_assets),
            (paths.post_body_asset_regions_jsonl, run.post_body_asset_regions),
            (paths.logical_tables_jsonl, run.logical_tables),
        ):
            _write_jsonl(path, rows)
            files.append(path)
    summary_dataframe(run).to_csv(paths.summary_csv, index=False)
    files.append(paths.summary_csv)
    if write_overlays:
        files.extend(sorted(paths.overlay_dir.glob("*.png")))
    return ExportManifest(tuple(files))
