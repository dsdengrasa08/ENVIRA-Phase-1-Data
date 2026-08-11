"""Execute the authoritative notebook's layout post-processing unchanged.

The reference notebook is deliberately immutable and is protected by a checksum
test.  Rather than maintaining a second, inevitably drifting copy of its large
set of document-layout heuristics, this adapter executes the authoritative
helper/preprocessing cells in an isolated namespace and converts their outputs
to the package's :class:`PipelineResult` contract.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any, Iterator

from .types import PipelineResult


_REFERENCE_CELLS = (4, 8, 10, 22)


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _reference_notebook() -> Path:
    path = Path(__file__).resolve().parents[3] / "pdf_layoutparser_vF.ipynb"
    if not path.is_file():
        raise FileNotFoundError(
            "The authoritative pdf_layoutparser_vF.ipynb notebook is required "
            "to run the fidelity-preserving post-processor"
        )
    return path


def _cell_source(notebook: dict[str, Any], index: int) -> str:
    cell = notebook["cells"][index]
    if cell.get("cell_type") != "code":
        raise RuntimeError(f"Authoritative notebook cell {index} is no longer code")
    return "".join(cell.get("source", []))


def _page_records(page_set, render_dpi: int) -> list[dict[str, Any]]:
    document = page_set.document
    return [
        {
            "doc_id": document.doc_id,
            "pdf_hash": document.pdf_hash,
            "source_pdf": str(document.pdf_path),
            "source_pdf_name": document.pdf_path.name,
            "source_pdf_original_name": document.original_name,
            "page_number": page.page_number,
            "page_index": page.page_number - 1,
            "total_pages": document.total_pages,
            "page_pdf_path": str(page.page_pdf_path),
            "page_image_path": str(page.page_image_path),
            "page_width_pt": page.width_pt,
            "page_height_pt": page.height_pt,
            "image_width_px": page.width_px,
            "image_height_px": page.height_px,
            "render_dpi": render_dpi,
        }
        for page in page_set.pages
    ]


def run_authoritative_pipeline(conversion, page_set, config) -> PipelineResult:
    """Run the exact reference item conversion, filters, and reading order."""
    notebook = json.loads(_reference_notebook().read_text(encoding="utf-8"))
    document = page_set.document
    artifacts = document.artifacts
    environment = {
        "PHASE1_SOURCE_PDF": str(document.pdf_path),
        "PHASE1_USE_GOOGLE_DRIVE": "0",
        "PHASE1_PROJECT_DIR": str(config.runtime.project_dir),
        "PHASE1_PAGE_START": str(document.page_start),
        "PHASE1_PAGE_END": str(document.page_end),
        "PHASE1_RENDER_DPI": str(config.document.render_dpi),
        "PHASE1_RUN_ID": config.document.run_id,
        "PHASE1_DOCLING_EXCLUDE_LABELS": ",".join(sorted(config.exclude_labels)),
    }
    namespace: dict[str, Any] = {
        "__name__": "envira_pdf_layout._authoritative_runtime",
        "display": lambda *args, **kwargs: None,
    }
    with _temporary_environment(environment):
        for index in _REFERENCE_CELLS[:3]:
            exec(compile(_cell_source(notebook, index), f"reference-cell-{index}", "exec"), namespace)

        page_json_dir = artifacts.document_dir / "page_json"
        page_json_dir.mkdir(parents=True, exist_ok=True)
        namespace.update(
            {
                "PDF_PATH": document.pdf_path,
                "DOC_ID": document.doc_id,
                "PDF_HASH": document.pdf_hash,
                "SOURCE_PDF_NAME": document.original_name,
                "PAGE_START": document.page_start,
                "PAGE_END_EFFECTIVE": document.page_end,
                "RENDER_DPI": config.document.render_dpi,
                "page_records": _page_records(page_set, config.document.render_dpi),
                "docling_page_range": (document.page_start, document.page_end),
                "docling_doc": conversion.document,
                "DOCLING_EXCLUDE_LABELS": {
                    str(label).lower().replace("-", "_")
                    for label in config.exclude_labels
                },
                "PAGE_PDF_DIR": artifacts.page_pdf_dir,
                "PAGE_IMAGE_DIR": artifacts.page_image_dir,
                "PAGE_JSON_DIR": page_json_dir,
                "OVERLAY_DIR": artifacts.overlay_dir,
                "PAGE_RECORDS_JSONL": artifacts.page_records_jsonl,
                "DOCLING_RAW_JSON": artifacts.raw_json,
                "DOCLING_MARKDOWN": artifacts.raw_markdown,
                "DOCLING_PAGE_RECORDS_JSONL": artifacts.document_dir / "docling_page_records.jsonl",
                "DOCLING_REGIONS_JSONL": artifacts.regions_jsonl,
                "POST_BODY_ASSETS_JSONL": artifacts.post_body_assets_jsonl,
                "POST_BODY_ASSET_REGIONS_JSONL": artifacts.post_body_asset_regions_jsonl,
                "SUMMARY_CSV": artifacts.summary_csv,
            }
        )
        exec(
            compile(_cell_source(notebook, _REFERENCE_CELLS[-1]), "reference-cell-22", "exec"),
            namespace,
        )

    excluded = {
        "label_exclusions": namespace["base_excluded_regions"],
        "page1_upper": namespace["page1_upper_excluded_regions"],
        "page1_lower": namespace["page1_lower_excluded_regions"],
        "page1_post_abstract": namespace["page1_post_abstract_excluded_regions"],
        "later_headers": namespace["later_page_upper_excluded_regions"],
        "small_edge_figures": namespace["small_edge_figure_excluded_regions"],
        "nested_assets": namespace["nested_asset_element_excluded_regions"],
        "side_margins": namespace["side_margin_text_excluded_regions"],
        "footer_furniture": namespace["repeated_footer_visual_excluded_regions"],
        "document_tail": namespace["post_conclusion_excluded_regions"],
    }
    diagnostics = {
        "page1": namespace["page1_post_abstract_metadata_analysis"],
        "later_headers": namespace["later_page_upper_header_analysis"],
        "small_edge_figures": namespace["small_edge_figure_analysis"],
        "figure_completion": namespace["caption_figure_completion_analysis"],
        "nested_assets": namespace["nested_asset_element_analysis"],
        "side_margins": namespace["side_margin_text_analysis"],
        "footer_furniture": namespace["repeated_footer_visual_analysis"],
        "document_tail": {
            "conclusion_anchor": namespace["detected_conclusion_anchor"],
            "boundary": namespace["detected_post_conclusion_boundary"],
        },
        "full_page_table_fallback": namespace["full_page_table_fallback_analysis"],
        "implementation": "pdf_layoutparser_vF.ipynb:cell-22",
    }
    return PipelineResult(
        document=document,
        pages=namespace["layout_page_records"],
        raw_regions=namespace["raw_regions"],
        final_regions=namespace["all_layout_regions"],
        excluded_by_stage=excluded,
        post_body_assets=namespace["post_body_asset_records"],
        post_body_asset_regions=namespace["post_body_asset_regions"],
        diagnostics=diagnostics,
        raw_document=conversion.raw_document,
        raw_markdown=conversion.markdown,
    )
