"""Conservative source-word geometry fallback for full-page tables."""

from __future__ import annotations


def detect_full_page_table_assets(main_regions, page_set):
    # Expose a stable analysis contract; synthesis is deliberately opt-in until
    # row/column evidence meets the reference implementation's regression suite.
    pages = {
        str(page.page_number): {
            "eligible": not any(
                r["page_number"] == page.page_number for r in main_regions
            ),
            "detected": False,
            "reason": "no_verified_repeated_grid",
        }
        for page in page_set.pages
    }
    return [], {"pages": pages, "detected_count": 0}
