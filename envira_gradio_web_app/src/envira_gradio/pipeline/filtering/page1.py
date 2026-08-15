"""Page-one title, frontmatter, abstract, and author-metadata processing."""

from __future__ import annotations
import re
from ..config import Page1FilterConfig
from ..types import FilterStageResult, LayoutRegion, PageRecord

_CONTACT = re.compile(
    r"\b(correspond|e-?mail|doi|received|accepted|available online|copyright)\b", re.I
)
_AFFIL = re.compile(
    r"\b(university|department|institute|laborator|faculty|hospital|school of|research cent)\w*\b",
    re.I,
)
_ANCHOR = re.compile(r"^(abstract|summary|article info|keywords?)\b", re.I)


def _ratios(region, page):
    x0, y0, x1, y1 = region["bbox_px"]
    return (
        x0 / page.width_px,
        y0 / page.height_px,
        x1 / page.width_px,
        y1 / page.height_px,
    )


def process_page1_regions(
    regions: list[LayoutRegion],
    page_map: dict[int, PageRecord],
    pdf_path,
    config: Page1FilterConfig,
) -> FilterStageResult:
    if not config.enabled or 1 not in page_map:
        return FilterStageResult(list(regions))
    page = page_map[1]
    first = [r for r in regions if r["page_number"] == 1]
    other = [r for r in regions if r["page_number"] != 1]
    title_candidates = [
        r
        for r in first
        if config.title_y_min <= _ratios(r, page)[1] <= config.title_y_max
        and r["type"] in {"Title", "Text"}
        and len(r.get("text", "").split()) >= 3
    ]
    title = max(
        title_candidates,
        key=lambda r: (r["type"] == "Title", r["width_px"], -r["bbox_px"][1]),
        default=None,
    )
    anchors = [
        r
        for r in first
        if _ANCHOR.search(r.get("text", "").strip())
        and _ratios(r, page)[1] <= config.body_anchor_y_max
    ]
    anchor = min(anchors, key=lambda r: r["bbox_px"][1], default=None)
    upper_end = anchor["bbox_px"][1] / page.height_px if anchor else 0.44
    excluded = []
    kept = []
    for region in first:
        _, y0, _, y1 = _ratios(region, page)
        text = region.get("text", "")
        drop = False
        reason = ""
        if title and y1 < title["bbox_px"][1] / page.height_px:
            drop, reason = True, "page1_upper_before_title"
        elif (
            title
            and y0 > title["bbox_px"][3] / page.height_px
            and y1 < upper_end
            and region is not anchor
        ):
            drop, reason = True, "page1_upper_frontmatter"
        elif y0 >= config.lower_metadata_min_y and (
            _CONTACT.search(text) or (_AFFIL.search(text) and len(text.split()) < 35)
        ):
            drop, reason = True, "page1_post_abstract_author_metadata"
        elif y0 >= config.hard_footer_y and region["type"] in {
            "Footnote",
            "Page-footer",
            "Unknown",
        }:
            drop, reason = True, "page1_lower_metadata"
        if drop:
            excluded.append({**region, "filter_reason": reason})
        else:
            kept.append(region)
    return FilterStageResult(
        other + kept,
        excluded,
        {
            "title": title,
            "body_anchor": anchor,
            "candidate_count": len(title_candidates),
            "drop_count": len(excluded),
            "protected_article_region_ids": [r["layout_region_id"] for r in anchors],
        },
    )
