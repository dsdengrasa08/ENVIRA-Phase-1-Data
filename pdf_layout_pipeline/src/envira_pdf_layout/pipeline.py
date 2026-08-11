"""Explicit, inspectable orchestration of the layout-processing stages."""

from __future__ import annotations
from collections import Counter, defaultdict
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


def run_layout_pipeline(conversion, page_set, config):
    raw = convert_docling_items(conversion.raw_document, page_set)
    page_map = page_set.by_number
    excluded = {}
    diagnostics = {}
    current = [
        r for r in raw if r["docling_label"].lower() not in config.exclude_labels
    ]
    excluded["label_exclusions"] = [
        {**r, "filter_reason": "configured_docling_label_exclusion"}
        for r in raw
        if r["docling_label"].lower() in config.exclude_labels
    ]
    stages = [
        (
            "page1",
            lambda rs: process_page1_regions(
                rs, page_map, page_set.document.pdf_path, config.page1
            ),
        ),
        (
            "later_headers",
            lambda rs: filter_later_page_headers(rs, page_map, config.headers),
        ),
        (
            "small_edge_figures",
            lambda rs: filter_small_edge_figures(rs, page_map, config.figures),
        ),
    ]
    for name, stage in stages:
        result = stage(current)
        current = result.kept
        excluded[name] = result.excluded
        diagnostics[name] = result.diagnostics
    completion = complete_caption_anchored_figures(
        current, raw, page_map, config.figures
    )
    current = completion.regions
    diagnostics["figure_completion"] = completion.diagnostics
    for name, stage in [
        ("nested_assets", lambda rs: filter_nested_asset_elements(rs, page_map)),
        ("side_margins", lambda rs: filter_side_margin_text_regions(rs, page_map)),
        (
            "footer_furniture",
            lambda rs: filter_repeated_footer_furniture(rs, page_map, config.footer),
        ),
    ]:
        result = stage(current)
        current = result.kept
        excluded[name] = result.excluded
        diagnostics[name] = result.diagnostics
    tail = filter_document_tail(current, page_map, config.tail)
    current = tail.kept
    excluded["document_tail"] = tail.excluded
    diagnostics["document_tail"] = tail.diagnostics
    assets, asset_regions = collect_post_body_assets(tail.excluded)
    synthetic, table_analysis = detect_full_page_table_assets(current, page_set)
    assets.extend(synthetic)
    diagnostics["full_page_table_fallback"] = table_analysis
    ordered, reading_meta = assign_document_reading_order(
        current, page_map, config.reading_order
    )
    diagnostics["reading_order"] = reading_meta
    by_page = defaultdict(list)
    assets_by_page = defaultdict(list)
    for r in ordered:
        by_page[r["page_number"]].append(r)
    for r in asset_regions:
        assets_by_page[r["page_number"]].append(r)
    pages = []
    for page in page_set.pages:
        regions = by_page[page.page_number]
        post = assets_by_page[page.page_number]
        counts = Counter(r["type"] for r in regions)
        pages.append(
            {
                "doc_id": page_set.document.doc_id,
                "pdf_hash": page_set.document.pdf_hash,
                "page_number": page.page_number,
                "page_image_path": str(page.page_image_path),
                "page_pdf_path": str(page.page_pdf_path),
                "layout_backend_used": "docling",
                "reading_order": reading_meta.get(str(page.page_number), {}),
                "layout_regions": regions,
                "post_body_asset_regions": post,
                "asset_aware_overlay_regions": [*regions, *post],
                "counts": {
                    "layout_regions": len(regions),
                    "post_body_asset_regions": len(post),
                    "figure_regions": counts["Figure"],
                    "table_regions": counts["Table"],
                    "formula_regions": counts["Formula"],
                    "excluded_regions": sum(
                        1
                        for rows in excluded.values()
                        for r in rows
                        if r["page_number"] == page.page_number
                    ),
                },
            }
        )
    return PipelineResult(
        page_set.document,
        pages,
        raw,
        ordered,
        excluded,
        assets,
        asset_regions,
        diagnostics,
        conversion.raw_document,
        conversion.markdown,
    )
