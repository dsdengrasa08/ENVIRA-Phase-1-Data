"""Semantic/geometric decomposition of detector-merged caption regions.

Native PDF words are the geometric authority.  GLM-OCR is an optional semantic
verifier and never supplies an arbitrary split when localized text is unavailable.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.request import Request, urlopen

from .config import CaptionDecompositionConfig

_ANCHOR = re.compile(
    r"^\s*(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?P<kind>fig(?:ure)?\.?|table|tab\.)\s*"
    r"(?P<number>[A-Z]?(?:[.\-]?\d+)+[a-z]?|[IVXLCDM]+|[A-Z])"
    r"(?:\s*[:.\-])?(?:\s+|$)",
    re.I,
)
_FUZZY_KIND = re.compile(r"^(?:f[l1i]g(?:ure)?\.?|tab[l1i]e|tab\.)$", re.I)


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]
    words: tuple[tuple[float, float, float, float, str], ...] = ()
    confidence: float | None = None


def _horizontal_overlap(a, b) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _native_lines(document, page_number: int, bbox_px, page) -> list[TextLine]:
    """Extract clipped native words and return coordinates in rendered pixels."""
    import pymupdf

    sx = float(page["image_width_px"]) / float(page["page_width_pt"])
    sy = float(page["image_height_px"]) / float(page["page_height_pt"])
    clip = pymupdf.Rect(
        bbox_px[0] / sx, bbox_px[1] / sy, bbox_px[2] / sx, bbox_px[3] / sy
    )
    with pymupdf.open(document.pdf_path) as pdf:
        words = pdf[page_number - 1].get_text("words", clip=clip, sort=True)
    grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for word in words:
        grouped[(int(word[5]), int(word[6]))].append(word)
    lines = []
    for key in sorted(
        grouped,
        key=lambda k: (min(w[1] for w in grouped[k]), min(w[0] for w in grouped[k])),
    ):
        ws = sorted(grouped[key], key=lambda w: (w[0], w[1]))
        localized = tuple(
            (w[0] * sx, w[1] * sy, w[2] * sx, w[3] * sy, str(w[4])) for w in ws
        )
        lines.append(
            TextLine(
                " ".join(w[4] for w in ws),
                (
                    min(w[0] for w in localized),
                    min(w[1] for w in localized),
                    max(w[2] for w in localized),
                    max(w[3] for w in localized),
                ),
                localized,
            )
        )
    return lines


def _anchor(line: TextLine, crop_left: float) -> dict[str, Any] | None:
    match = _ANCHOR.match(line.text)
    fuzzy = False
    if not match:
        tokens = line.text.split()
        if (
            len(tokens) >= 2
            and _FUZZY_KIND.match(tokens[0])
            and re.match(r"^(?:\d+[a-z]?|[IVXLCDM]+)[.:]?$", tokens[1], re.I)
        ):
            fuzzy = True
            kind = "figure" if tokens[0].casefold().startswith("f") else "table"
            number = tokens[1].rstrip(".:")
        else:
            return None
    else:
        kind = "figure" if match.group("kind").casefold().startswith("f") else "table"
        number = match.group("number")
    score = (
        3.0 + (0.7 if number else 0.0) + (0.4 if line.bbox[0] - crop_left < 24 else 0.0)
    )
    if fuzzy:
        score -= 1.0
    if line.confidence is not None and line.confidence < 0.6:
        score -= 1.0
    return {
        "kind": kind,
        "number": number,
        "score": score,
        "fuzzy": fuzzy,
        "text": line.text,
    }


def _suspicious(region, lines, page_height, assets, config) -> tuple[bool, list[str]]:
    reasons = []
    box = region["bbox_px"]
    if (box[3] - box[1]) / page_height >= config.suspicious_height_page_ratio:
        reasons.append("height_outlier")
    if len(lines) >= config.suspicious_min_lines:
        reasons.append("many_text_lines")
    anchors = [a for line in lines if (a := _anchor(line, box[0]))]
    if len(anchors) >= 2:
        reasons.append("multiple_line_start_anchors")
    plausible = [
        a
        for a in assets
        if _horizontal_overlap(box, a["bbox_px"])
        >= config.parent_min_horizontal_overlap
    ]
    if len(plausible) >= 2:
        reasons.append("multiple_nearby_assets")
    return ("multiple_line_start_anchors" in reasons or len(reasons) >= 2), reasons


class GlmOcrVerifier:
    """Ask GLM-OCR to transcribe every detected caption into positioned lines."""

    def __init__(self, config: CaptionDecompositionConfig):
        self.config = config

    @property
    def available(self) -> bool:
        return bool(self.config.glm_endpoint and self.config.glm_api_key)

    def scan(self, image_path: str, crop) -> dict[str, Any]:
        """Return GLM lines and caption-label starts in crop-relative coordinates."""
        if not self.available:
            return {
                "available": False,
                "reason": "not_configured",
                "lines": [],
                "anchors": [],
            }
        from io import BytesIO
        from PIL import Image

        with Image.open(image_path) as image:
            buffer = BytesIO()
            image.crop(tuple(map(int, crop))).save(buffer, format="PNG")
        prompt = (
            "OCR this detected scientific-caption crop. Return JSON only. Preserve reading order and "
            "line breaks. Locate every line in normalized crop coordinates 0..1000. A caption label is "
            "a Fig, Figure, Table, or Tab label followed by an identifier at the START of a logical "
            "caption; do not mark an in-sentence reference. Schema: "
            '{"lines":[{"text":"...","bbox":[x0,y0,x1,y1]}],'
            '"anchors":[{"line_index":0,"kind":"figure|table","label":"Fig. 1"}],'
            '"confidence":0.0}. Every anchor line starts a caption and that caption ends immediately '
            "before the next anchor line."
        )
        payload = {
            "model": self.config.glm_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                + base64.b64encode(buffer.getvalue()).decode()
                            },
                        },
                    ],
                }
            ],
        }
        request = Request(
            self.config.glm_endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.config.glm_api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.config.glm_timeout_seconds) as response:
                raw = json.loads(response.read().decode())
            content = raw["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            result = json.loads(content)
            return {"available": True, **result}
        except Exception as exc:
            return {
                "available": True,
                "reason": f"scan_error:{type(exc).__name__}",
                "lines": [],
                "anchors": [],
            }

    # Compatibility for injected verifiers used by older callers/tests.
    def verify(self, image_path: str, crop, lines, anchors) -> dict[str, Any]:
        result = self.scan(image_path, crop)
        return {**result, "verified": len(result.get("anchors", [])) >= 2}


def _glm_lines(result, crop) -> list[TextLine]:
    """Map GLM's normalized crop line boxes back to page-image pixels."""
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    output = []
    for item in result.get("lines", []):
        box = item.get("bbox")
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not str(item.get("text", "")).strip()
        ):
            continue
        x0, y0, x1, y1 = (float(value) for value in box)
        if (
            not all(0 <= value <= 1000 for value in (x0, y0, x1, y1))
            or x1 <= x0
            or y1 <= y0
        ):
            continue
        output.append(
            TextLine(
                str(item["text"]).strip(),
                (
                    crop[0] + width * x0 / 1000,
                    crop[1] + height * y0 / 1000,
                    crop[0] + width * x1 / 1000,
                    crop[1] + height * y1 / 1000,
                ),
                confidence=result.get("confidence"),
            )
        )
    return output


def _parent_score(block, anchor, asset, page_height, config):
    if asset.get("type") != anchor["kind"].title():
        return None
    overlap = _horizontal_overlap(block, asset["bbox_px"])
    gap = (
        max(
            0.0, max(block[1], asset["bbox_px"][1]) - min(block[3], asset["bbox_px"][3])
        )
        / page_height
    )
    if (
        overlap < config.parent_min_horizontal_overlap
        or gap > config.parent_max_gap_page_ratio
    ):
        return None
    return 0.6 * overlap + 0.4 * max(0.0, 1 - gap / config.parent_max_gap_page_ratio)


def decompose_captions(regions, pages, document, config=None, verifier=None):
    """Return derived regions and complete auditable decomposition diagnostics."""
    config = config or CaptionDecompositionConfig()
    if not config.enabled:
        return list(regions), []
    verifier = verifier or GlmOcrVerifier(config)
    page_map = {int(p["page_number"]): p for p in pages}
    output, diagnostics = [], []
    for region in regions:
        if region.get("type") != "Caption":
            output.append(region)
            continue
        page = page_map[int(region["page_number"])]
        assets = [
            r
            for r in regions
            if r.get("page_number") == region.get("page_number")
            and r.get("type") in {"Figure", "Table"}
        ]
        try:
            lines = _native_lines(
                document, int(region["page_number"]), region["bbox_px"], page
            )
        except Exception as exc:
            lines = []
            extraction_error = type(exc).__name__
        else:
            extraction_error = None
        # GLM scans every detected caption.  Native words remain a fallback and
        # a geometry cross-check, rather than a gate that can prevent scanning.
        if config.glm_verify:
            if hasattr(verifier, "scan"):
                glm = verifier.scan(region["page_image_path"], region["bbox_px"])
            else:
                glm = verifier.verify(
                    region["page_image_path"], region["bbox_px"], lines, []
                )
        else:
            glm = {"available": False, "reason": "disabled", "lines": [], "anchors": []}
        glm_lines = _glm_lines(glm, region["bbox_px"])
        geometry_source = "glm_ocr" if glm_lines else "native_pdf"
        analysis_lines = glm_lines or lines
        suspicious, reasons = _suspicious(
            region, analysis_lines, float(page["image_height_px"]), assets, config
        )
        record = {
            "source_region_id": str(region["layout_region_id"]),
            "suspicious": suspicious,
            "suspicion_reasons": reasons,
            "native_line_count": len(lines),
            "native_extraction_error": extraction_error,
            "glm_scan": glm,
            "geometry_source": geometry_source,
            "status": "preserved",
        }
        if not analysis_lines:
            output.append(region)
            record["status"] = "abstained_no_positioned_lines"
            diagnostics.append(record)
            continue
        candidates = []
        for index, line in enumerate(analysis_lines):
            anchor = _anchor(line, region["bbox_px"][0])
            if anchor and anchor["score"] >= config.min_anchor_score:
                candidates.append((index, anchor))
        # Prefer GLM's explicit semantic anchors, while requiring a valid line
        # index and a figure/table label at that line's beginning.
        if glm_lines and glm.get("anchors"):
            explicit = []
            for item in glm["anchors"]:
                try:
                    index = int(item["line_index"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not 0 <= index < len(analysis_lines):
                    continue
                anchor = _anchor(analysis_lines[index], region["bbox_px"][0])
                if anchor:
                    explicit.append((index, anchor))
            if explicit:
                candidates = sorted(dict(explicit).items())
        if len(candidates) < 2:
            output.append(region)
            record["status"] = "abstained_insufficient_anchors"
            diagnostics.append(record)
            continue
        record["detected_anchors"] = [anchor for _, anchor in candidates]
        heights = [max(1.0, line.bbox[3] - line.bbox[1]) for line in analysis_lines]
        if any(
            (analysis_lines[b].bbox[1] - analysis_lines[a].bbox[3])
            / (sum(heights) / len(heights))
            < -config.min_anchor_separation_lines
            for (a, _), (b, _) in zip(candidates, candidates[1:])
        ):
            output.append(region)
            record["status"] = "abstained_overlapping_anchors"
            diagnostics.append(record)
            continue
        starts = [i for i, _ in candidates] + [len(analysis_lines)]
        children = []
        semantic_children = []
        used_parents = set()
        for ordinal, ((start, anchor), end) in enumerate(
            zip(candidates, starts[1:]), 1
        ):
            block_lines = analysis_lines[start:end]
            # A detector box can contain caption + body paragraph + caption.
            # Isolate a prose-like tail only when a conspicuous whitespace break
            # precedes it; ordinary multiline caption continuations remain intact.
            prose_lines = []
            if end < len(analysis_lines) and len(block_lines) >= 3:
                gaps = [
                    max(0.0, b.bbox[1] - a.bbox[3])
                    for a, b in zip(block_lines, block_lines[1:])
                ]
                median_height = sorted(heights)[len(heights) // 2]
                cut = max(range(len(gaps)), key=gaps.__getitem__)
                tail = block_lines[cut + 1 :]
                tail_text = " ".join(item.text for item in tail)
                if (
                    gaps[cut] >= 0.8 * median_height
                    and len(tail_text) >= 45
                    and re.search(r"[.!?](?:\s|$)", tail_text)
                ):
                    prose_lines = tail
                    block_lines = block_lines[: cut + 1]
            box = [
                min(l.bbox[0] for l in block_lines),
                min(l.bbox[1] for l in block_lines),
                max(l.bbox[2] for l in block_lines),
                max(l.bbox[3] for l in block_lines),
            ]
            ranked = sorted(
                (
                    (s, a)
                    for a in assets
                    if (
                        s := _parent_score(
                            box, anchor, a, float(page["image_height_px"]), config
                        )
                    )
                    is not None
                    and str(a["layout_region_id"]) not in used_parents
                ),
                reverse=True,
                key=lambda x: x[0],
            )
            parent_id = (
                str(ranked[0][1]["layout_region_id"])
                if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.15)
                else None
            )
            confidence = min(
                1.0,
                0.55
                + 0.08 * anchor["score"]
                + (0.12 if parent_id else 0)
                + (0.1 if glm_lines else 0),
            )
            child = deepcopy(region)
            child.update(
                {
                    "layout_region_id": f"{region['layout_region_id']}:caption:{ordinal}",
                    "type": f"{anchor['kind'].title()} Caption",
                    "semantic_caption_type": anchor["kind"],
                    "text": " ".join(l.text for l in block_lines),
                    "bbox_px": box,
                    "width_px": box[2] - box[0],
                    "height_px": box[3] - box[1],
                    "area_px": (box[2] - box[0]) * (box[3] - box[1]),
                    "source_region_ids": list(
                        dict.fromkeys(
                            region.get(
                                "source_region_ids", [str(region["layout_region_id"])]
                            )
                            + [str(region["layout_region_id"])]
                        )
                    ),
                    "source_bbox_px": list(region["bbox_px"]),
                    "resolved_bbox_px": box,
                    "geometry_version": int(region.get("geometry_version", 1)) + 1,
                    "resolution_action": "semantic_caption_decomposition",
                    "decomposition_confidence": round(confidence, 4),
                    "caption_anchor": anchor,
                    "parent_region_id": parent_id,
                    "emission_policy": "emit_derived",
                }
            )
            if parent_id:
                used_parents.add(parent_id)
            children.append(child)
            semantic_children.append(child)
            if prose_lines:
                prose_box = [
                    min(l.bbox[0] for l in prose_lines),
                    min(l.bbox[1] for l in prose_lines),
                    max(l.bbox[2] for l in prose_lines),
                    max(l.bbox[3] for l in prose_lines),
                ]
                prose = deepcopy(region)
                prose.update(
                    {
                        "layout_region_id": f"{region['layout_region_id']}:intervening:{ordinal}",
                        "type": "Text",
                        "text": " ".join(l.text for l in prose_lines),
                        "bbox_px": prose_box,
                        "width_px": prose_box[2] - prose_box[0],
                        "height_px": prose_box[3] - prose_box[1],
                        "area_px": (prose_box[2] - prose_box[0])
                        * (prose_box[3] - prose_box[1]),
                        "source_region_ids": [str(region["layout_region_id"])],
                        "source_bbox_px": list(region["bbox_px"]),
                        "resolved_bbox_px": prose_box,
                        "resolution_action": "semantic_caption_decomposition_intervening_text",
                        "emission_policy": "emit_derived",
                        "geometry_version": int(region.get("geometry_version", 1)) + 1,
                    }
                )
                semantic_children.append(prose)
        if (
            len(children) >= 2
            and min(c["decomposition_confidence"] for c in children)
            >= config.min_split_confidence
        ):
            output.extend(semantic_children)
            record.update(
                status="decomposed",
                derived_region_ids=[c["layout_region_id"] for c in semantic_children],
            )
        else:
            output.append(region)
            record["status"] = "abstained_low_confidence"
        diagnostics.append(record)
    # Rebuild deterministic page-local reading order after one-to-many replacement.
    for page_number in {int(r["page_number"]) for r in output}:
        page_regions = [r for r in output if int(r["page_number"]) == page_number]
        for order, item in enumerate(
            sorted(page_regions, key=lambda r: (r["bbox_px"][1], r["bbox_px"][0])), 1
        ):
            item["resolved_reading_order"] = order
    return output, diagnostics
