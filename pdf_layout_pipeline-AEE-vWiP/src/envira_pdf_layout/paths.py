"""Stable document identity and output-path derivation."""

from __future__ import annotations
import hashlib
import re
import shutil
from pathlib import Path
from .config import PipelineConfig
from .types import ArtifactPaths, DocumentIdentity


def file_sha256_short(path: Path, length: int = 12) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


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
    pdf_hash = file_sha256_short(source)
    doc_id = f"{safe_name(source.stem)}__{pdf_hash}"
    input_dir = config.runtime.project_dir / "input_pdfs"
    input_dir.mkdir(parents=True, exist_ok=True)
    persistent = input_dir / f"{doc_id}.pdf"
    if not persistent.exists() or not config.document.prefer_persistent_copy:
        shutil.copy2(source, persistent)
    with fitz.open(persistent) as pdf:
        total = int(pdf.page_count)
    start = config.document.page_start
    end = min(config.document.page_end or total, total)
    if start > total or end < start:
        raise ValueError(f"Invalid page range {start}-{end} for {total}-page PDF")
    document_dir = (
        config.runtime.project_dir / "outputs" / "docling_layout_only" / doc_id
    )
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
        summary_csv=document_dir / "summary.csv",
    )
    for directory in (
        document_dir,
        artifacts.page_pdf_dir,
        artifacts.page_image_dir,
        artifacts.overlay_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return DocumentIdentity(
        source, persistent, source.name, pdf_hash, doc_id, total, start, end, artifacts
    )
