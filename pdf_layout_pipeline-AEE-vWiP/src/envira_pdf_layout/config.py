"""Configuration loading and validation without filesystem side effects."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
import os
from pathlib import Path
from typing import Any, Mapping, get_args, get_origin, get_type_hints

import yaml


def _serializable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _serializable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, frozenset, set)):
        return (
            [
                _serializable(item)
                for item in sorted(value)
                if isinstance(value, (set, frozenset))
            ]
            if isinstance(value, (set, frozenset))
            else [_serializable(item) for item in value]
        )
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in sorted(value.items())}
    return value


def _convert(value: Any, annotation: Any, key: str) -> Any:
    if value is None:
        return None
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is not None and type(None) in args:
        annotation = next(arg for arg in args if arg is not type(None))
        origin, args = get_origin(annotation), get_args(annotation)
    if annotation is Path:
        return Path(value)
    if annotation is bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ValueError(f"{key} must be a boolean")
        return normalized in {"1", "true", "yes", "on"}
    if origin is tuple:
        return tuple(value)
    if origin is frozenset:
        return frozenset(str(item).lower() for item in value)
    if annotation in {int, float, str}:
        try:
            return annotation(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid value for {key}: {value!r}") from exc
    return value


def _build_section(section: str, cls: type, values: Mapping[str, Any]) -> Any:
    allowed = {item.name for item in fields(cls)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(
            f"Unknown configuration field(s) in {section}: {', '.join(sorted(unknown))}"
        )
    hints = get_type_hints(cls)
    return cls(
        **{
            key: _convert(value, hints[key], f"{section}.{key}")
            for key, value in values.items()
        }
    )


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
    max_completion_area_multiplier: float = 4.0
    max_completion_page_area_ratio: float = 0.65
    max_completion_edge_growth_ratio: float = 0.45
    completion_paragraph_min_chars: int = 80
    completion_min_assignment_score: float = 7.0


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
class CaptionAssociationConfig:
    """Controls for authoritative caption ownership without layout mutation."""

    enabled: bool = True
    max_vertical_gap_page_ratio: float = 0.10
    min_horizontal_overlap_ratio: float = 0.18
    blocker_horizontal_overlap_ratio: float = 0.25
    acceptance_score: float = 0.35
    ambiguity_margin: float = 0.15


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
    fragment_horizontal_overlap: float = 0.50
    fragment_max_gap_page_ratio: float = 0.012
    boundary_overlap_ratio: float = 0.20
    preserve_authoritative_nested_regions: bool = True


@dataclass(frozen=True)
class ContainmentConfig:
    """Single source of thresholds for observational containment and hierarchy."""

    strong_child_coverage: float = 0.92
    center_child_coverage: float = 0.72
    max_child_parent_area_ratio: float = 0.85
    panel_label_max_chars: int = 12
    body_paragraph_min_chars: int = 80
    caption_identifier_max_chars: int = 24


@dataclass(frozen=True)
class ExportConfig:
    write_raw: bool = True
    write_regions: bool = True
    write_overlays: bool = True


@dataclass(frozen=True)
class HeuristicProfileConfig:
    """Optional lexical profiles; generic geometry remains authoritative."""

    publisher_profiles: tuple[str, ...] = (
        "elsevier_sciencedirect",
        "generic_academic_publishers",
    )
    publisher_mode: str = "confirmatory"
    document_family: str = "auto"
    language: str = "auto"


@dataclass(frozen=True)
class ContentPolicyConfig:
    """Consumer policy for valid semantic sections, separate from layout noise."""

    retain_front_matter: bool = False
    retain_references: bool = False
    retain_acknowledgements: bool = False
    retain_declarations: bool = False
    retain_appendices: bool = False
    retain_supplementary_sections: bool = False
    preserve_excluded_sections_in_secondary_stream: bool = True


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
    caption_association: CaptionAssociationConfig = field(
        default_factory=CaptionAssociationConfig
    )
    overlap_resolution: OverlapResolutionConfig = field(
        default_factory=OverlapResolutionConfig
    )
    containment: ContainmentConfig = field(default_factory=ContainmentConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    heuristics: HeuristicProfileConfig = field(default_factory=HeuristicProfileConfig)
    content_policy: ContentPolicyConfig = field(default_factory=ContentPolicyConfig)
    exclude_labels: frozenset[str] = frozenset()
    profile_path: Path | None = field(default=None, compare=False)
    value_sources: dict[str, str] = field(default_factory=dict, compare=False)
    legacy_core_environment: dict[str, str] = field(default_factory=dict, compare=False)

    @classmethod
    def load(
        cls,
        profile: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        source_pdf: str | Path | None = None,
        **overrides: object,
    ) -> "PipelineConfig":
        """Load defaults, YAML, environment, then explicit overrides in that order."""
        env = dict(os.environ if environ is None else environ)
        sections = {
            "runtime": RuntimeConfig,
            "document": DocumentConfig,
            "docling": DoclingConfig,
            "page1": Page1FilterConfig,
            "headers": HeaderFilterConfig,
            "figures": FigureFilterConfig,
            "footer": FooterFilterConfig,
            "tail": TailFilterConfig,
            "reading_order": ReadingOrderConfig,
            "table_context": TableContextConfig,
            "caption_overlap": CaptionOverlapConfig,
            "caption_association": CaptionAssociationConfig,
            "overlap_resolution": OverlapResolutionConfig,
            "containment": ContainmentConfig,
            "export": ExportConfig,
            "heuristics": HeuristicProfileConfig,
            "content_policy": ContentPolicyConfig,
        }
        data: dict[str, Any] = {}
        sources: dict[str, str] = {
            f"{section}.{item.name}": "default"
            for section, section_cls in sections.items()
            for item in fields(section_cls)
        }
        sources["exclude_labels"] = "default"
        profile_path = Path(profile).expanduser().resolve() if profile else None
        if profile_path:
            loaded = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, Mapping):
                raise ValueError("Configuration profile must contain a mapping")
            unknown = set(loaded) - set(sections) - {"exclude_labels"}
            if unknown:
                raise ValueError(
                    f"Unknown configuration section(s): {', '.join(sorted(unknown))}"
                )
            for key, value in loaded.items():
                if key not in sections:
                    continue
                if value is not None and not isinstance(value, Mapping):
                    raise ValueError(
                        f"Configuration section {key} must contain a mapping"
                    )
                data[key] = dict(value or {})
            if "exclude_labels" in loaded:
                data["exclude_labels"] = loaded["exclude_labels"]
            for section, values in data.items():
                if isinstance(values, Mapping):
                    for key in values:
                        sources[f"{section}.{key}"] = f"profile:{profile_path}"

        env_fields = {
            "PHASE1_USE_GOOGLE_DRIVE": ("runtime", "use_google_drive"),
            "PHASE1_GDRIVE_MOUNT_POINT": ("runtime", "drive_mount_point"),
            "PHASE1_PROJECT_DIR": ("runtime", "project_dir"),
            "PHASE1_OFFLINE_MODE": ("runtime", "offline"),
            "PHASE1_SKIP_PIP_INSTALL": ("runtime", "skip_pip_install"),
            "PHASE1_SOURCE_PDF": ("document", "source_pdf"),
            "PHASE1_PAGE_START": ("document", "page_start"),
            "PHASE1_PAGE_END": ("document", "page_end"),
            "PHASE1_RENDER_DPI": ("document", "render_dpi"),
            "PHASE1_RUN_ID": ("document", "run_id"),
            "PHASE1_PREFER_LOCAL_INPUT_COPY": ("document", "prefer_persistent_copy"),
            "PHASE1_DOCLING_ARTIFACTS_DIR": ("docling", "artifacts_dir"),
            "PHASE1_USE_LOCAL_DOCLING_ARTIFACTS": ("docling", "use_local_artifacts"),
            "PHASE1_REQUIRE_SAVED_DOCLING_MODELS": ("docling", "require_saved_models"),
            "PHASE1_AUTO_DOWNLOAD_DOCLING_MODELS": ("docling", "auto_download_models"),
            "PHASE1_FORCE_REDOWNLOAD_DOCLING_MODELS": (
                "docling",
                "force_redownload_models",
            ),
            "PHASE1_DOCLING_MIN_MODEL_SIZE_MB": ("docling", "min_model_size_mb"),
            "PHASE1_DOCLING_DO_OCR": ("docling", "do_ocr"),
            "PHASE1_DOCLING_DO_TABLE_STRUCTURE": ("docling", "do_table_structure"),
            "PHASE1_DOCLING_DO_FORMULA_ENRICHMENT": (
                "docling",
                "do_formula_enrichment",
            ),
            "PHASE1_DOCLING_DO_CODE_ENRICHMENT": ("docling", "do_code_enrichment"),
            "PHASE1_DOCLING_CODE_FORMULA_PRESET": ("docling", "code_formula_preset"),
        }
        # Every typed field has a predictable environment spelling; the mappings
        # above retain compatibility with established shorter variable names.
        for section, section_cls in sections.items():
            for item in fields(section_cls):
                env_fields.setdefault(
                    f"PHASE1_{section}_{item.name}".upper(), (section, item.name)
                )
        for name, (section, key) in env_fields.items():
            if name in env and (env[name].strip() or key == "run_id"):
                raw: Any = env[name]
                if key == "page_end" and not raw.strip():
                    raw = None
                data.setdefault(section, {})[key] = raw
                sources[f"{section}.{key}"] = f"environment:{name}"
        if "PHASE1_PAGE1_ABSTRACT_EQUIVALENT_ALIASES" in env:
            data.setdefault("page1", {})["abstract_aliases"] = [
                item.strip()
                for item in env["PHASE1_PAGE1_ABSTRACT_EQUIVALENT_ALIASES"].split(",")
                if item.strip()
            ]
            sources["page1.abstract_aliases"] = (
                "environment:PHASE1_PAGE1_ABSTRACT_EQUIVALENT_ALIASES"
            )
        if "PHASE1_DOCLING_EXCLUDE_LABELS" in env:
            data["exclude_labels"] = [
                item.strip()
                for item in env["PHASE1_DOCLING_EXCLUDE_LABELS"].split(",")
                if item.strip()
            ]
            sources["exclude_labels"] = "environment:PHASE1_DOCLING_EXCLUDE_LABELS"

        document_overrides = {
            key: overrides.pop(key)
            for key in list(overrides)
            if key in {item.name for item in fields(DocumentConfig)}
        }
        if source_pdf is not None:
            document_overrides["source_pdf"] = source_pdf
        if document_overrides:
            data.setdefault("document", {}).update(document_overrides)
            sources.update(
                {f"document.{key}": "explicit" for key in document_overrides}
            )
        for section, values in overrides.items():
            if section not in sections or not isinstance(values, Mapping):
                raise ValueError(
                    f"Unknown or invalid explicit configuration override: {section}"
                )
            data.setdefault(section, {}).update(values)
            sources.update({f"{section}.{key}": "explicit" for key in values})

        built = {
            section: _build_section(section, section_cls, data.get(section, {}))
            for section, section_cls in sections.items()
        }
        if built["docling"].artifacts_dir is None:
            built["docling"] = replace(
                built["docling"],
                artifacts_dir=built["runtime"].project_dir
                / "artifacts"
                / "docling_models",
            )
            if sources["docling.artifacts_dir"] == "default":
                sources["docling.artifacts_dir"] = "derived:runtime.project_dir"
        excluded = frozenset(
            str(item).lower() for item in data.get("exclude_labels", [])
        )
        legacy = {key: value for key, value in env.items() if key.startswith("PHASE1_")}
        config = cls(
            **built,
            exclude_labels=excluded,
            profile_path=profile_path,
            value_sources=sources,
            legacy_core_environment=legacy,
        )
        config.validate()
        return config

    @classmethod
    def from_env(
        cls, source_pdf: str | Path | None = None, **overrides: object
    ) -> "PipelineConfig":
        return cls.load(source_pdf=source_pdf, **overrides)

    def to_dict(self, *, include_provenance: bool = True) -> dict[str, Any]:
        value = _serializable(self)
        if not include_provenance:
            value.pop("profile_path", None)
            value.pop("value_sources", None)
            value.pop("legacy_core_environment", None)
        return value

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
        if self.docling.min_model_size_mb < 0:
            raise ValueError("docling min_model_size_mb must be non-negative")
        for section_name in (
            "page1",
            "headers",
            "figures",
            "footer",
            "reading_order",
        ):
            section = getattr(self, section_name)
            for item in fields(section):
                value = getattr(section, item.name)
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and (
                        item.name.endswith("_ratio")
                        or item.name.endswith("_min_y")
                        or item.name.endswith("_max_y")
                        or item.name.endswith("_y_min")
                        or item.name.endswith("_y_max")
                        or item.name.endswith("_y0_min")
                        or item.name.endswith("_y1_max")
                    )
                    and not 0 <= value <= 1
                ):
                    raise ValueError(f"{section_name}.{item.name} must be in [0, 1]")
        if self.page1.title_y_min > self.page1.title_y_max:
            raise ValueError("page1 title_y_min must not exceed title_y_max")
        if self.headers.min_repeat_pages < 1 or self.footer.min_repeat_pages < 1:
            raise ValueError("repeat-page thresholds must be positive")
        if self.figures.max_completion_area_multiplier < 1:
            raise ValueError(
                "figures.max_completion_area_multiplier must be at least 1"
            )
        if self.figures.completion_paragraph_min_chars < 1:
            raise ValueError("figures.completion_paragraph_min_chars must be positive")
        if self.figures.completion_min_assignment_score < 0:
            raise ValueError(
                "figures.completion_min_assignment_score must be non-negative"
            )
        if self.heuristics.publisher_mode not in {
            "disabled",
            "evidence_only",
            "confirmatory",
            "active",
        }:
            raise ValueError("heuristics.publisher_mode is invalid")
        from .heuristics import PUBLISHER_PROFILES

        unknown_profiles = set(self.heuristics.publisher_profiles) - set(
            PUBLISHER_PROFILES
        )
        if unknown_profiles:
            raise ValueError(
                "Unknown publisher profile(s): " + ", ".join(sorted(unknown_profiles))
            )
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
        association = self.caption_association
        for name in (
            "max_vertical_gap_page_ratio",
            "min_horizontal_overlap_ratio",
            "blocker_horizontal_overlap_ratio",
        ):
            if not 0 <= getattr(association, name) <= 1:
                raise ValueError(f"caption association {name} must be in [0, 1]")
        for name in ("acceptance_score", "ambiguity_margin"):
            if getattr(association, name) < 0:
                raise ValueError(f"caption association {name} must be non-negative")
        generalized = self.overlap_resolution
        for name in (
            "duplicate_iou",
            "duplicate_area_ratio",
            "fragment_horizontal_overlap",
            "boundary_overlap_ratio",
        ):
            if not 0 <= getattr(generalized, name) <= 1:
                raise ValueError(f"overlap resolution {name} must be in [0, 1]")
        for name in ("duplicate_edge_page_ratio", "fragment_max_gap_page_ratio"):
            if getattr(generalized, name) < 0:
                raise ValueError(f"overlap resolution {name} must be non-negative")
        for name in (
            "strong_child_coverage",
            "center_child_coverage",
            "max_child_parent_area_ratio",
        ):
            if not 0 <= getattr(self.containment, name) <= 1:
                raise ValueError(f"containment {name} must be in [0, 1]")
        for name in (
            "panel_label_max_chars",
            "body_paragraph_min_chars",
            "caption_identifier_max_chars",
        ):
            if getattr(self.containment, name) < 1:
                raise ValueError(f"containment {name} must be positive")
