"""Main-body end detection and conservative back-matter separation."""

from __future__ import annotations
import re
from ..config import TailFilterConfig
from ..types import FilterStageResult

_CONCLUSION = re.compile(
    r"^(?:\d+(?:\.\d+)*\s*)?(conclusions?|discussion and conclusions?)\s*$", re.I
)
_BACK = re.compile(
    r"^(references|bibliography|acknowledg|conflict of interest|author contributions|data availability|appendix)\b",
    re.I,
)


def filter_document_tail(regions, page_map, config: TailFilterConfig):
    if not config.enabled:
        return FilterStageResult(list(regions))
    ordered = sorted(
        regions, key=lambda r: (r["page_number"], r["bbox_px"][1], r["bbox_px"][0])
    )
    conclusion = next(
        (r for r in reversed(ordered) if _CONCLUSION.match(r.get("text", "").strip())),
        None,
    )
    search = [
        r
        for r in ordered
        if conclusion is None
        or (r["page_number"], r["bbox_px"][1])
        > (conclusion["page_number"], conclusion["bbox_px"][1])
    ]
    boundary = next((r for r in search if _BACK.match(r.get("text", "").strip())), None)
    if boundary is None:
        return FilterStageResult(
            list(regions),
            diagnostics={"boundary_method": None, "conclusion_anchor": conclusion},
        )
    key = (boundary["page_number"], boundary["bbox_px"][1])
    excluded = []
    kept = []
    for r in regions:
        if (r["page_number"], r["bbox_px"][1]) >= key:
            excluded.append({**r, "filter_reason": "post_conclusion_backmatter"})
        else:
            kept.append(r)
    return FilterStageResult(
        kept,
        excluded,
        {
            "boundary_method": (
                "conclusion_anchor" if conclusion else "direct_backmatter_fallback"
            ),
            "conclusion_anchor": conclusion,
            "boundary": boundary,
            "drop_count": len(excluded),
        },
    )
