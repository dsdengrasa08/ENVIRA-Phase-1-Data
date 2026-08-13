"""Typed data contracts for the PDF layout pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NotRequired, Required, TypedDict

BBox = tuple[float, float, float, float]


class LayoutRegion(TypedDict, total=False):
    region_schema_version: Required[int]
    layout_region_id: Required[str]
    page_number: Required[int]
    type: Required[str]
    bbox_px: Required[list[float]]
    source_bbox_px: NotRequired[list[float]]
    resolved_bbox_px: NotRequired[list[float]]
    physical_bbox_px: NotRequired[list[float]]
    visual_crop_bbox_px: NotRequired[list[float]]
    semantic_group_bbox_px: NotRequired[list[float]]
    geometry_version: NotRequired[int]
    geometry_history: NotRequired[list[dict[str, Any]]]


@dataclass(frozen=True)
class ArtifactPaths:
    project_dir: Path
    document_dir: Path
    input_pdf: Path
    page_pdf_dir: Path
    page_image_dir: Path
    overlay_dir: Path
    raw_json: Path
    raw_markdown: Path
    page_records_jsonl: Path
    regions_jsonl: Path
    post_body_assets_jsonl: Path
    post_body_asset_regions_jsonl: Path
    logical_tables_jsonl: Path
    raw_regions_jsonl: Path
    resolved_regions_jsonl: Path
    caption_relationships_jsonl: Path
    caption_groups_jsonl: Path
    layout_relationships_jsonl: Path
    resolution_decisions_jsonl: Path
    suppressed_regions_jsonl: Path
    effective_config_json: Path
    diagnostics_json: Path
    physical_regions_jsonl: Path
    top_level_regions_jsonl: Path
    nested_regions_jsonl: Path
    figure_completion_proposals_jsonl: Path
    stage_trace_jsonl: Path
    page_diagnostics_jsonl: Path
    artifact_manifest_json: Path
    summary_csv: Path


@dataclass(frozen=True)
class DocumentIdentity:
    source_pdf: Path
    pdf_path: Path
    original_name: str
    pdf_hash: str
    pdf_sha256: str
    doc_id: str
    total_pages: int
    page_start: int
    page_end: int
    artifacts: ArtifactPaths


@dataclass(frozen=True)
class PageRecord:
    page_number: int
    page_pdf_path: Path
    page_image_path: Path
    width_px: int
    height_px: int
    width_pt: float
    height_pt: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {k: str(v) if isinstance(v, Path) else v for k, v in value.items()}


@dataclass
class PageSet:
    document: DocumentIdentity
    pages: list[PageRecord]

    @property
    def by_number(self) -> dict[int, PageRecord]:
        return {page.page_number: page for page in self.pages}


@dataclass
class FilterStageResult:
    kept: list[LayoutRegion]
    excluded: list[LayoutRegion] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformStageResult:
    regions: list[LayoutRegion]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    document: DocumentIdentity
    pages: list[dict[str, Any]]
    raw_regions: list[LayoutRegion]
    final_regions: list[LayoutRegion]
    excluded_by_stage: dict[str, list[LayoutRegion]]
    post_body_assets: list[dict[str, Any]]
    post_body_asset_regions: list[LayoutRegion]
    diagnostics: dict[str, Any]
    raw_document: dict[str, Any]
    raw_markdown: str = ""
    logical_tables: list[dict[str, Any]] = field(default_factory=list)
    resolved_regions: list[LayoutRegion] = field(default_factory=list)
    caption_overlap_relationships: list[dict[str, Any]] = field(default_factory=list)
    caption_groups: list[dict[str, Any]] = field(default_factory=list)
    layout_relationships: list[dict[str, Any]] = field(default_factory=list)
    resolution_decisions: list[dict[str, Any]] = field(default_factory=list)
    suppressed_regions: list[LayoutRegion] = field(default_factory=list)
    physical_regions: list[LayoutRegion] = field(default_factory=list)
    top_level_regions: list[LayoutRegion] = field(default_factory=list)
    nested_regions: list[LayoutRegion] = field(default_factory=list)
    filtered_regions: list[LayoutRegion] = field(default_factory=list)
    semantic_groups: list[dict[str, Any]] = field(default_factory=list)
    stage_trace: list[dict[str, Any]] = field(default_factory=list)
    status: str = "complete"
    failed_pages: list[int] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    failed_stages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExportManifest:
    files: tuple[Path, ...]
