"""Configuration loading and validation without filesystem side effects."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
import os
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class RuntimeConfig:
    use_google_drive: bool = True
    drive_mount_point: Path = Path("/content/drive")
    project_dir: Path = Path(
        "/content/drive/MyDrive/00-ENVIRA/01-LayoutParser/phase1_docling"
    )
    offline: bool = False
    skip_pip_install: bool = False


@dataclass(frozen=True)
class DocumentConfig:
    source_pdf: Path = Path("/content/1-s2.0-S0167880921000803-main.pdf")
    page_start: int = 1
    page_end: int | None = None
    render_dpi: int = 180
    run_id: str = ""
    prefer_persistent_copy: bool = True


@dataclass(frozen=True)
class DoclingConfig:
    artifacts_dir: Path | None = None
    use_local_artifacts: bool = True
    require_saved_models: bool = True
    auto_download_models: bool = False
    force_redownload_models: bool = False
    min_model_size_mb: float = 100.0
    do_ocr: bool = False
    do_table_structure: bool = True
    do_formula_enrichment: bool = True
    do_code_enrichment: bool = False
    code_formula_preset: str = "codeformulav2"


@dataclass(frozen=True)
class Page1FilterConfig:
    enabled: bool = True
    abstract_aliases: tuple[str, ...] = ("Abstract", "Summary")
    recover_abstract_heading: bool = True
    title_y_min: float = 0.15
    title_y_max: float = 0.42
    body_anchor_y_max: float = 0.70
    lower_metadata_min_y: float = 0.68
    hard_footer_y: float = 0.92


@dataclass(frozen=True)
class HeaderFilterConfig:
    enabled: bool = True
    top_band_ratio: float = 0.14
    min_repeat_pages: int = 2


@dataclass(frozen=True)
class FigureFilterConfig:
    complete_caption_anchored: bool = True
    require_multipanel_hint: bool = True
    filter_small_edge_figures: bool = True
    header_y1_max: float = 0.12
    footer_y0_min: float = 0.90


@dataclass(frozen=True)
class FooterFilterConfig:
    enabled: bool = True
    compact_enabled: bool = True
    min_repeat_pages: int = 2
    y0_min: float = 0.88


@dataclass(frozen=True)
class TailFilterConfig:
    enabled: bool = True
    direct_backmatter_fallback: bool = True


@dataclass(frozen=True)
class ReadingOrderConfig:
    column_gap_ratio: float = 0.04
    min_column_width_ratio: float = 0.20


@dataclass(frozen=True)
class TableContextConfig:
    """Publisher-independent controls for logical table association."""

    enabled: bool = True
    max_vertical_gap_page_ratio: float = 0.10
    min_horizontal_overlap_ratio: float = 0.18
    acceptance_score: float = 4.5
    ambiguity_margin: float = 0.6
    max_boundary_overlap_page_ratio: float = 0.008
    fragment_max_gap_page_ratio: float = 0.018
    fragment_max_line_gap_ratio: float = 1.8
    fragment_min_horizontal_overlap: float = 0.30
    fragment_edge_alignment_page_ratio: float = 0.025
    fragment_acceptance_score: float = 4.5
    fragment_ambiguity_margin: float = 0.75


@dataclass(frozen=True)
class CaptionOverlapConfig:
    """Conservative, publisher-independent caption relationship controls."""

    enabled: bool = True
    duplicate_iou: float = 0.90
    duplicate_edge_page_ratio: float = 0.003
    duplicate_area_ratio: float = 0.85
    nested_containment: float = 0.92
    fragment_max_gap_page_ratio: float = 0.012
    boundary_overlap_page_ratio: float = 0.008
    # Maximum penetration relative to the smaller region height that is treated
    # as harmless contact between unlike semantic roles.
    boundary_overlap_ratio: float = 0.20


@dataclass(frozen=True)
class OverlapResolutionConfig:
    """Class-aware controls for the generalized relationship graph.

    Destructive actions intentionally use stricter thresholds than relationship
    observation.  Values are page-relative where their names end in ``ratio``.
    """

    enabled: bool = True
    duplicate_iou: float = 0.90
    duplicate_edge_page_ratio: float = 0.003
    duplicate_area_ratio: float = 0.85
    nested_containment: float = 0.92
    fragment_horizontal_overlap: float = 0.50
    fragment_max_gap_page_ratio: float = 0.012
    boundary_overlap_ratio: float = 0.20
    preserve_filtered_nested_regions: bool = True


@dataclass(frozen=True)
class CaptionValidationConfig:
    """Controls for decomposing detector captions into semantic captions."""

    enabled: bool = True
    prefixes: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Figure", ("fig", "fig.", "figure")),
        ("Table", ("table", "tab", "tab.")),
        ("Formula", ("equation", "eq", "eq.")),
        ("Algorithm", ("algorithm",)),
        ("Listing", ("listing",)),
    )
    parent_types: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Figure", ("Figure",)),
        ("Table", ("Table",)),
        ("Formula", ("Formula", "Equation")),
        ("Algorithm", ("Algorithm",)),
        ("Listing", ("Listing", "Code")),
    )
    preferred_directions: tuple[tuple[str, str], ...] = (
        ("Figure", "below"),
        ("Table", "above"),
        ("Formula", "either"),
        ("Algorithm", "above"),
        ("Listing", "above"),
    )
    split_acceptance_score: float = 6.0
    split_margin: float = 1.5
    review_score: float = 4.0
    max_parent_gap_page_ratio: float = 0.12
    min_parent_horizontal_overlap: float = 0.18
    expected_direction_bonus: float = 1.2
    type_match_bonus: float = 2.5
    type_mismatch_penalty: float = 2.5
    min_segment_lines: int = 1
    use_pdf_text_lines: bool = True
    use_selective_line_provider: bool = True
    provider_quality_threshold: float = 0.55
    parent_ambiguity_margin: float = 0.75
    min_boundary_gap_line_ratio: float = 0.18
    strong_boundary_gap_line_ratio: float = 0.55
    max_line_outside_source_ratio: float = 0.15


@dataclass(frozen=True)
class CaptionOCRConfig:
    """Optional dotted-path provider for selective caption line extraction."""

    enabled: bool = False
    provider: str = ""


@dataclass(frozen=True)
class ExportConfig:
    write_raw: bool = True
    write_regions: bool = True
    write_overlays: bool = True


@dataclass(frozen=True)
class PipelineConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    document: DocumentConfig = field(default_factory=DocumentConfig)
    docling: DoclingConfig = field(default_factory=DoclingConfig)
    page1: Page1FilterConfig = field(default_factory=Page1FilterConfig)
    headers: HeaderFilterConfig = field(default_factory=HeaderFilterConfig)
    figures: FigureFilterConfig = field(default_factory=FigureFilterConfig)
    footer: FooterFilterConfig = field(default_factory=FooterFilterConfig)
    tail: TailFilterConfig = field(default_factory=TailFilterConfig)
    reading_order: ReadingOrderConfig = field(default_factory=ReadingOrderConfig)
    table_context: TableContextConfig = field(default_factory=TableContextConfig)
    caption_overlap: CaptionOverlapConfig = field(default_factory=CaptionOverlapConfig)
    overlap_resolution: OverlapResolutionConfig = field(
        default_factory=OverlapResolutionConfig
    )
    caption_validation: CaptionValidationConfig = field(
        default_factory=CaptionValidationConfig
    )
    caption_ocr: CaptionOCRConfig = field(default_factory=CaptionOCRConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    exclude_labels: frozenset[str] = frozenset()

    @classmethod
    def from_yaml(cls, *paths: str | Path) -> "PipelineConfig":
        """Load one or more YAML profiles, with later files taking precedence."""
        import yaml

        config = cls()
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(values, dict):
                raise ValueError(f"Configuration root must be a mapping: {path}")
            config = _replace_dataclass(config, values)
        config.validate()
        return config

    @classmethod
    def from_env(
        cls,
        source_pdf: str | Path | None = None,
        *,
        profiles: tuple[str | Path, ...] | None = None,
        **overrides: object,
    ) -> "PipelineConfig":
        base = cls.from_yaml(*profiles) if profiles else cls()
        project = Path(os.environ.get("PHASE1_PROJECT_DIR", base.runtime.project_dir))
        document = replace(
            base.document,
            source_pdf=Path(
                source_pdf
                or os.environ.get("PHASE1_SOURCE_PDF", base.document.source_pdf)
            ),
            page_start=int(
                overrides.get(
                    "page_start",
                    os.environ.get("PHASE1_PAGE_START", base.document.page_start),
                )
            ),
            page_end=(
                overrides.get("page_end")
                if "page_end" in overrides
                else (
                    int(os.environ["PHASE1_PAGE_END"])
                    if os.environ.get("PHASE1_PAGE_END", "").strip()
                    else base.document.page_end
                )
            ),
            render_dpi=int(
                overrides.get(
                    "render_dpi",
                    os.environ.get("PHASE1_RENDER_DPI", base.document.render_dpi),
                )
            ),
            run_id=str(
                overrides.get(
                    "run_id", os.environ.get("PHASE1_RUN_ID", base.document.run_id)
                )
            ),
            prefer_persistent_copy=_flag(
                "PHASE1_PREFER_LOCAL_INPUT_COPY", base.document.prefer_persistent_copy
            ),
        )
        runtime = replace(
            base.runtime,
            use_google_drive=_flag(
                "PHASE1_USE_GOOGLE_DRIVE", base.runtime.use_google_drive
            ),
            drive_mount_point=Path(
                os.environ.get(
                    "PHASE1_GDRIVE_MOUNT_POINT", base.runtime.drive_mount_point
                )
            ),
            project_dir=project,
            offline=_flag("PHASE1_OFFLINE_MODE", base.runtime.offline),
            skip_pip_install=_flag(
                "PHASE1_SKIP_PIP_INSTALL", base.runtime.skip_pip_install
            ),
        )
        docling = replace(
            base.docling,
            artifacts_dir=Path(
                os.environ.get(
                    "PHASE1_DOCLING_ARTIFACTS_DIR", project / "artifacts/docling_models"
                )
            ),
            use_local_artifacts=_flag(
                "PHASE1_USE_LOCAL_DOCLING_ARTIFACTS", base.docling.use_local_artifacts
            ),
            require_saved_models=_flag(
                "PHASE1_REQUIRE_SAVED_DOCLING_MODELS", base.docling.require_saved_models
            ),
            auto_download_models=_flag(
                "PHASE1_AUTO_DOWNLOAD_DOCLING_MODELS", base.docling.auto_download_models
            ),
            force_redownload_models=_flag(
                "PHASE1_FORCE_REDOWNLOAD_DOCLING_MODELS",
                base.docling.force_redownload_models,
            ),
            do_ocr=_flag("PHASE1_DOCLING_DO_OCR", base.docling.do_ocr),
        )
        aliases = tuple(
            x.strip()
            for x in os.environ.get(
                "PHASE1_PAGE1_ABSTRACT_EQUIVALENT_ALIASES",
                ",".join(base.page1.abstract_aliases),
            ).split(",")
            if x.strip()
        )
        excluded = frozenset(
            x.strip().lower()
            for x in os.environ.get(
                "PHASE1_DOCLING_EXCLUDE_LABELS", ",".join(base.exclude_labels)
            ).split(",")
            if x.strip()
        )
        config = replace(
            base,
            runtime=runtime,
            document=document,
            docling=docling,
            page1=replace(
                base.page1, abstract_aliases=aliases or ("Abstract", "Summary")
            ),
            exclude_labels=excluded,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.document.page_start < 1:
            raise ValueError("page_start must be at least 1")
        if (
            self.document.page_end is not None
            and self.document.page_end < self.document.page_start
        ):
            raise ValueError("page_end must not precede page_start")
        if self.document.render_dpi <= 0:
            raise ValueError("render_dpi must be positive")
        if self.caption_validation.split_acceptance_score < 0:
            raise ValueError("caption validation acceptance score must be non-negative")
        if self.caption_validation.split_margin < 0:
            raise ValueError("caption validation margin must be non-negative")
        if not 0 < self.caption_validation.max_parent_gap_page_ratio <= 1:
            raise ValueError("caption validation parent gap ratio must be in (0, 1]")
        if not 0 <= self.caption_validation.min_parent_horizontal_overlap <= 1:
            raise ValueError("caption validation parent overlap must be in [0, 1]")
        if self.caption_validation.min_segment_lines < 1:
            raise ValueError("caption validation min_segment_lines must be positive")
        for name in (
            "provider_quality_threshold",
            "max_line_outside_source_ratio",
        ):
            if not 0 <= getattr(self.caption_validation, name) <= 1:
                raise ValueError(f"caption validation {name} must be in [0, 1]")
        for name in (
            "parent_ambiguity_margin",
            "min_boundary_gap_line_ratio",
            "strong_boundary_gap_line_ratio",
        ):
            if getattr(self.caption_validation, name) < 0:
                raise ValueError(f"caption validation {name} must be non-negative")
        if not 0 < self.table_context.max_vertical_gap_page_ratio <= 1:
            raise ValueError("table context vertical gap ratio must be in (0, 1]")
        if not 0 <= self.table_context.min_horizontal_overlap_ratio <= 1:
            raise ValueError("table context overlap ratio must be in [0, 1]")
        if self.table_context.acceptance_score < 0:
            raise ValueError("table context acceptance score must be non-negative")
        if self.table_context.ambiguity_margin < 0:
            raise ValueError("table context ambiguity margin must be non-negative")
        if not 0 <= self.table_context.max_boundary_overlap_page_ratio <= 1:
            raise ValueError("table context boundary overlap ratio must be in [0, 1]")
        for name in (
            "fragment_max_gap_page_ratio",
            "fragment_min_horizontal_overlap",
            "fragment_edge_alignment_page_ratio",
        ):
            if not 0 <= getattr(self.table_context, name) <= 1:
                raise ValueError(f"table context {name} must be in [0, 1]")
        for name in (
            "fragment_max_line_gap_ratio",
            "fragment_acceptance_score",
            "fragment_ambiguity_margin",
        ):
            if getattr(self.table_context, name) < 0:
                raise ValueError(f"table context {name} must be non-negative")
        overlap = self.caption_overlap
        for name in (
            "duplicate_iou",
            "duplicate_area_ratio",
            "nested_containment",
            "boundary_overlap_ratio",
        ):
            if not 0 <= getattr(overlap, name) <= 1:
                raise ValueError(f"caption overlap {name} must be in [0, 1]")
        for name in (
            "duplicate_edge_page_ratio",
            "fragment_max_gap_page_ratio",
            "boundary_overlap_page_ratio",
        ):
            if getattr(overlap, name) < 0:
                raise ValueError(f"caption overlap {name} must be non-negative")
        generalized = self.overlap_resolution
        for name in (
            "duplicate_iou",
            "duplicate_area_ratio",
            "nested_containment",
            "fragment_horizontal_overlap",
            "boundary_overlap_ratio",
        ):
            if not 0 <= getattr(generalized, name) <= 1:
                raise ValueError(f"overlap resolution {name} must be in [0, 1]")
        for name in ("duplicate_edge_page_ratio", "fragment_max_gap_page_ratio"):
            if getattr(generalized, name) < 0:
                raise ValueError(f"overlap resolution {name} must be non-negative")


def _replace_dataclass(instance, values: dict):
    """Recursively apply a YAML mapping to a dataclass with strict key checking."""
    known = {item.name: item for item in fields(instance)}
    unknown = set(values) - set(known)
    if unknown:
        raise ValueError(
            f"Unknown {type(instance).__name__} configuration keys: {sorted(unknown)}"
        )
    updates = {}
    for name, value in values.items():
        current = getattr(instance, name)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"Configuration section {name!r} must be a mapping")
            updates[name] = _replace_dataclass(current, value)
        elif isinstance(current, Path) or (current is None and name.endswith("_dir")):
            updates[name] = None if value is None else Path(value)
        elif isinstance(current, tuple) and isinstance(value, list):
            updates[name] = tuple(value)
        elif isinstance(current, frozenset):
            updates[name] = frozenset(value)
        else:
            updates[name] = value
    return replace(instance, **updates)
