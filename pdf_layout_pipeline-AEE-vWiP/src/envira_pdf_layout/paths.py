"""Stable document identity and output-path derivation."""

from __future__ import annotations
import re
import shutil
from pathlib import Path
from .config import PipelineConfig
from .types import ArtifactPaths, DocumentIdentity
from .security import secure_directory, secure_file, sha256_file


def file_sha256_short(path: Path, length: int = 12) -> str:
    return sha256_file(path)[:length]


def safe_name(value: str) -> str:
    cleaned = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9._-]+", "_", str(value))).strip(
        "._-"
    )
    return cleaned or "document"


def prepare_document_context(config: PipelineConfig) -> DocumentIdentity:
    import fitz

    source = config.document.source_pdf.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"PDF not found: {source}")
    if source.stat().st_size > config.security.max_input_pdf_bytes:
        raise ValueError("input PDF exceeds security.max_input_pdf_bytes")
    pdf_sha256 = sha256_file(source, max_bytes=config.security.max_input_pdf_bytes)
    pdf_hash = pdf_sha256[:12]
    doc_id = f"{safe_name(source.stem)}__{pdf_hash}"
    input_dir = config.runtime.project_dir / "input_pdfs"
    secure_directory(input_dir, config.security.secure_directory_mode)
    persistent = input_dir / f"{doc_id}.pdf"
    if (
        not persistent.exists()
        or not config.document.prefer_persistent_copy
        or sha256_file(persistent, max_bytes=config.security.max_input_pdf_bytes)
        != pdf_sha256
    ):
        shutil.copy2(source, persistent)
    secure_file(persistent, config.security.secure_file_mode)
    with fitz.open(persistent) as pdf:
        total = int(pdf.page_count)
    if total > config.security.max_page_count:
        raise ValueError("input PDF exceeds security.max_page_count")
    start = config.document.page_start
    end = min(config.document.page_end or total, total)
    if start > total or end < start:
        raise ValueError(f"Invalid page range {start}-{end} for {total}-page PDF")
    output_root = config.runtime.project_dir / "outputs" / "docling_layout_only"
    secure_directory(output_root, config.security.secure_directory_mode)
    document_dir = output_root / doc_id
    if config.document.run_id:
        document_dir /= safe_name(config.document.run_id)
    artifacts = ArtifactPaths(
        project_dir=config.runtime.project_dir,
        document_dir=document_dir,
        input_pdf=persistent,
        page_pdf_dir=document_dir / "page_pdfs",
        page_image_dir=document_dir / "page_images",
        overlay_dir=document_dir / "overlays",
        raw_json=document_dir / "docling_raw.json",
        raw_markdown=document_dir / "docling_raw.md",
        page_records_jsonl=document_dir / "page_records.jsonl",
        regions_jsonl=document_dir / "docling_regions.jsonl",
        post_body_assets_jsonl=document_dir / "post_body_assets.jsonl",
        post_body_asset_regions_jsonl=document_dir / "post_body_asset_regions.jsonl",
        logical_tables_jsonl=document_dir / "logical_tables.jsonl",
        raw_regions_jsonl=document_dir / "raw_layout_regions.jsonl",
        resolved_regions_jsonl=document_dir / "resolved_layout_regions.jsonl",
        caption_relationships_jsonl=document_dir
        / "caption_overlap_relationships.jsonl",
        caption_groups_jsonl=document_dir / "caption_groups.jsonl",
        layout_relationships_jsonl=document_dir / "layout_relationships.jsonl",
        resolution_decisions_jsonl=document_dir / "resolution_decisions.jsonl",
        suppressed_regions_jsonl=document_dir / "suppressed_layout_regions.jsonl",
        effective_config_json=document_dir / "effective_config.json",
        diagnostics_json=document_dir / "pipeline_diagnostics.json",
        physical_regions_jsonl=document_dir / "physical_layout_regions.jsonl",
        top_level_regions_jsonl=document_dir / "top_level_layout_regions.jsonl",
        nested_regions_jsonl=document_dir / "nested_layout_regions.jsonl",
        figure_completion_proposals_jsonl=document_dir
        / "figure_completion_proposals.jsonl",
        stage_trace_jsonl=document_dir / "stage_trace.jsonl",
        page_diagnostics_jsonl=document_dir / "page_diagnostics.jsonl",
        artifact_manifest_json=document_dir / "artifact_manifest.json",
        summary_csv=document_dir / "summary.csv",
    )
    for directory in (
        document_dir,
        artifacts.page_pdf_dir,
        artifacts.page_image_dir,
        artifacts.overlay_dir,
    ):
        secure_directory(directory, config.security.secure_directory_mode)
    sentinel = document_dir / ".envira-run-root"
    if not sentinel.exists():
        sentinel.write_text(doc_id + "\n", encoding="utf-8")
        secure_file(sentinel, config.security.secure_file_mode)
    return DocumentIdentity(
        source, persistent, source.name, pdf_hash, pdf_sha256, doc_id, total, start, end, artifacts
    )
