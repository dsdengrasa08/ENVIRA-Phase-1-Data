"""Package-native Docling conversion and order-sensitive layout filtering."""

from __future__ import annotations

from collections import Counter

from .assets.post_body import collect_post_body_assets
from .assets.table_fallback import detect_full_page_table_assets
from .filtering.document_tail import filter_document_tail
from .filtering.figures import (
    complete_caption_anchored_figures,
    filter_small_edge_figures,
)
from .filtering.footer_furniture import filter_repeated_footer_furniture
from .filtering.headers import filter_later_page_headers
from .filtering.nested_assets import filter_nested_asset_elements
from .filtering.page1 import process_page1_regions
from .filtering.side_margins import filter_side_margin_text_regions
from .reading_order import assign_document_reading_order
from .region_conversion import convert_docling_items
from .types import PipelineResult


def _page_records(page_set, regions, post_body_regions):
    records = []
    for page in page_set.pages:
        page_regions = [r for r in regions if r["page_number"] == page.page_number]
        assets = [r for r in post_body_regions if r["page_number"] == page.page_number]
        counts = Counter(r["type"] for r in page_regions)
        records.append(
            {
                **page.to_dict(),
                "doc_id": page_set.document.doc_id,
                "pdf_hash": page_set.document.pdf_hash,
                "source_pdf": str(page_set.document.pdf_path),
                "source_pdf_name": page_set.document.pdf_path.name,
                "source_pdf_original_name": page_set.document.original_name,
                "page_index": page.page_number - 1,
                "total_pages": page_set.document.total_pages,
                "image_width_px": page.width_px,
                "image_height_px": page.height_px,
                "page_width_pt": page.width_pt,
                "page_height_pt": page.height_pt,
                "render_dpi": None,
                "layout_regions": page_regions,
                "post_body_asset_regions": assets,
                "asset_aware_overlay_regions": page_regions + assets,
                "counts": {
                    "raw_region_count": 0,
                    "final_region_count": len(page_regions),
                    "post_body_asset_region_count": len(assets),
                    **{
                        f"{name.lower()}_count": count for name, count in counts.items()
                    },
                },
            }
        )
    return records


def run_modular_pipeline(conversion, page_set, config) -> PipelineResult:
    """Run the maintained Python implementation without executing a notebook."""
    raw = convert_docling_items(conversion.raw_document, page_set)
    excluded = {
        "label_exclusions": [
            {**r, "filter_reason": "configured_docling_label_exclusion"}
            for r in raw
            if r["docling_label"].lower().replace("-", "_") in config.exclude_labels
        ]
    }
    regions = [
        r
        for r in raw
        if r["docling_label"].lower().replace("-", "_") not in config.exclude_labels
    ]
    diagnostics = {"implementation": "envira_pdf_layout.modular_pipeline"}

    stages = (
        (
            "page1",
            lambda rs: process_page1_regions(
                rs, page_set.by_number, page_set.document.pdf_path, config.page1
            ),
        ),
        (
            "later_headers",
            lambda rs: filter_later_page_headers(
                rs, page_set.by_number, config.headers
            ),
        ),
        (
            "small_edge_figures",
            lambda rs: filter_small_edge_figures(
                rs, page_set.by_number, config.figures
            ),
        ),
    )
    for name, stage in stages:
        outcome = stage(regions)
        regions, excluded[name], diagnostics[name] = (
            outcome.kept,
            outcome.excluded,
            outcome.diagnostics,
        )

    completion = complete_caption_anchored_figures(
        regions, raw, page_set.by_number, config.figures
    )
    regions, diagnostics["figure_completion"] = (
        completion.regions,
        completion.diagnostics,
    )
    for name, stage in (
        (
            "nested_assets",
            lambda rs: filter_nested_asset_elements(rs, page_set.by_number),
        ),
        (
            "side_margins",
            lambda rs: filter_side_margin_text_regions(rs, page_set.by_number),
        ),
        (
            "footer_furniture",
            lambda rs: filter_repeated_footer_furniture(
                rs, page_set.by_number, config.footer
            ),
        ),
    ):
        outcome = stage(regions)
        regions, excluded[name], diagnostics[name] = (
            outcome.kept,
            outcome.excluded,
            outcome.diagnostics,
        )

    tail = filter_document_tail(regions, page_set.by_number, config.tail)
    regions, excluded["document_tail"], diagnostics["document_tail"] = (
        tail.kept,
        tail.excluded,
        tail.diagnostics,
    )
    post_body_assets, post_body_regions = collect_post_body_assets(tail.excluded)
    fallback_records, fallback_diagnostics = detect_full_page_table_assets(
        regions, page_set
    )
    post_body_assets.extend(fallback_records)
    diagnostics["full_page_table_fallback"] = fallback_diagnostics
    regions, order_metadata = assign_document_reading_order(
        regions, page_set.by_number, config.reading_order
    )
    diagnostics["reading_order"] = {
        "decisions": list(order_metadata.values()),
        "pages": order_metadata,
    }
    pages = _page_records(page_set, regions, post_body_regions)
    raw_by_page = Counter(r["page_number"] for r in raw)
    for page in pages:
        page["counts"]["raw_region_count"] = raw_by_page[page["page_number"]]
        page["render_dpi"] = config.document.render_dpi
    return PipelineResult(
        document=page_set.document,
        pages=pages,
        raw_regions=raw,
        final_regions=regions,
        excluded_by_stage=excluded,
        post_body_assets=post_body_assets,
        post_body_asset_regions=post_body_regions,
        diagnostics=diagnostics,
        raw_document=conversion.raw_document,
        raw_markdown=conversion.markdown,
        config=config,
    )
