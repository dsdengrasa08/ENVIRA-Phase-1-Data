"""Infer logical table context without changing physical layout detections."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from .config import TableContextConfig
from .types import LayoutRegion
from .region_index import RegionIndex

_TABLE_LABEL_RE = re.compile(
    r"^\s*(?P<label>(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?:table|tab\.)\s+(?:[A-Z](?:[.\-]?\d+)?|[IVXLCDM]+|\d+(?:[.\-]\w+)?))"
    r"(?:\s*[:.\-])?(?:\s+|$)",
    re.IGNORECASE,
)
_NOTE_RE = re.compile(
    r"^\s*(?:notes?|sources?)\s*:|^\s*(?:[*†‡]|[a-z])(?:[.)]|\s{1,3})\s+|"
    r"\b[pP]\s*[<=>]\s*\.?\d+",
    re.IGNORECASE,
)
_BODY_SENTENCE_RE = re.compile(r"^[A-Z][^.!?]{35,}[.!?](?:\s|$)")
_NEW_OBJECT_RE = re.compile(
    r"^\s*(?:fig(?:ure)?\.?|equation|eq\.?|algorithm|listing)\s+\w+",
    re.IGNORECASE,
)
_TEXT_TYPES = {"Text", "Caption", "Footnote", "Section-header", "Title", "List"}
_FRAGMENT_TYPES = {"Text", "Caption", "List"}
_BOUNDARY_TYPES = {"Table", "Figure", "Section-header", "Title"}


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _column_compatible(
    candidate: LayoutRegion, table: LayoutRegion, page_width: float
) -> bool:
    candidate_column = candidate.get("reading_order_column")
    table_column = table.get("reading_order_column")
    table_width = float(table["bbox_px"][2] - table["bbox_px"][0]) / page_width
    candidate_width = (
        float(candidate["bbox_px"][2] - candidate["bbox_px"][0]) / page_width
    )
    if table_width >= 0.72 or candidate_width >= 0.72:
        return True
    if (
        not candidate_column
        or not table_column
        or "single" in {candidate_column, table_column}
    ):
        return True
    return candidate_column == table_column


def _has_blocker(
    candidate: LayoutRegion, table: LayoutRegion, page_regions: list[LayoutRegion]
) -> str | None:
    cb, tb = candidate["bbox_px"], table["bbox_px"]
    candidate_center = (float(cb[1]) + float(cb[3])) / 2.0
    table_center = (float(tb[1]) + float(tb[3])) / 2.0
    top, bottom = (
        sorted((float(cb[3]), float(tb[1])))
        if candidate_center <= table_center
        else sorted((float(tb[3]), float(cb[1])))
    )
    for region in page_regions:
        if region is candidate or region is table:
            continue
        rb = region["bbox_px"]
        if (
            float(rb[1]) >= top
            and float(rb[3]) <= bottom
            and _overlap_ratio(list(map(float, rb)), list(map(float, tb))) >= 0.18
            and region.get("type") in _BOUNDARY_TYPES
        ):
            return str(region.get("layout_region_id"))
    return None


def _score_edge(
    candidate: LayoutRegion,
    table: LayoutRegion,
    role: str,
    page_regions: list[LayoutRegion],
    page_width: float,
    page_height: float,
    config: TableContextConfig,
) -> dict[str, Any] | None:
    cb, tb = list(map(float, candidate["bbox_px"])), list(map(float, table["bbox_px"]))
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    above = cb[3] <= tb[1] + tolerance and cb[1] < tb[1]
    below = cb[1] >= tb[3] - tolerance and cb[3] > tb[3]
    if not (above or below) or candidate.get("type") not in _TEXT_TYPES:
        return None
    gap = (tb[1] - cb[3]) if above else (cb[1] - tb[3])
    gap_page = max(0.0, gap) / page_height
    overlap = _overlap_ratio(cb, tb)
    if gap_page > config.max_vertical_gap_page_ratio:
        return None
    if overlap < config.min_horizontal_overlap_ratio:
        return None
    if not _column_compatible(candidate, table, page_width):
        return None
    blocker = _has_blocker(candidate, table, page_regions)
    if blocker:
        return None

    text = str(candidate.get("text") or "").strip()
    label_match = _TABLE_LABEL_RE.match(text)
    note_match = _NOTE_RE.search(text)
    style = candidate.get("typography") or {}
    is_italic = bool(style.get("italic") or candidate.get("is_italic"))
    has_superscript = bool(style.get("superscript") or candidate.get("has_superscript"))
    order_delta = abs(
        int(
            candidate.get("layout_reading_order")
            or candidate.get("docling_reading_order")
            or 0
        )
        - int(
            table.get("layout_reading_order") or table.get("docling_reading_order") or 0
        )
    )
    direction_ok = (role == "caption" and above) or (role == "note" and below)
    components = {
        "proximity": max(
            0.0, 2.4 * (1.0 - gap_page / config.max_vertical_gap_page_ratio)
        ),
        "horizontal_compatibility": 1.8 * overlap,
        "column_compatibility": 1.5,
        "reading_order": (
            1.2 if order_delta <= 2 else (0.5 if order_delta <= 4 else 0.0)
        ),
        "direction": 0.8 if direction_ok else (-0.4 if role == "caption" else -1.0),
        "raw_class": (
            2.0
            if role == "caption" and candidate.get("type") == "Caption"
            else 1.4
            if role == "note" and candidate.get("type") == "Footnote"
            else 0.0
        ),
        "identifier_lexical": 1.8 if label_match and role == "caption" else 0.0,
        "note_lexical": 1.5 if note_match and role == "note" else 0.0,
        "body_paragraph_penalty": -3.2 if _BODY_SENTENCE_RE.search(text) else 0.0,
        "typography": (
            0.4 if (role == "note" and (is_italic or has_superscript)) else 0.0
        ),
    }
    score = sum(components.values())
    return {
        "table_region_id": table["layout_region_id"],
        "region_id": candidate["layout_region_id"],
        "proposed_role": role,
        "score": round(score, 4),
        "accepted": False,
        "direction": "above" if above else "below",
        "features": {
            "gap_page_ratio": round(gap_page, 6),
            "boundary_overlap_page_ratio": round(max(0.0, -gap) / page_height, 6),
            "horizontal_overlap_ratio": round(overlap, 6),
            "reading_order_delta": order_delta,
            "components": components,
        },
        "printed_label": label_match.group("label").strip() if label_match else None,
        "caption_text_after_label": bool(
            label_match and text[label_match.end() :].strip()
        ),
    }


def _order(region: LayoutRegion) -> int:
    return int(
        region.get("resolved_reading_order")
        or region.get("layout_reading_order")
        or region.get("docling_reading_order")
        or 10**9
    )


def _fragment_edge(
    candidate: LayoutRegion,
    member: LayoutRegion,
    table: LayoutRegion,
    page_regions: list[LayoutRegion],
    page_width: float,
    page_height: float,
    config: TableContextConfig,
    relationship_kinds: set[str],
) -> dict[str, Any] | None:
    """Score one local caption-continuation edge.

    A fragment is admitted through a caption seed/component, rather than merely
    because it happens to be close to a table. This keeps the decision local and
    permits long captions whose first line is not itself close to the table.
    """
    if candidate.get("type") not in _FRAGMENT_TYPES:
        return None
    text = str(candidate.get("text") or "").strip()
    if not text or _TABLE_LABEL_RE.match(text) or _NEW_OBJECT_RE.match(text):
        return None
    cb = list(map(float, candidate["bbox_px"]))
    mb = list(map(float, member["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    member_above = (mb[1] + mb[3]) / 2 < (tb[1] + tb[3]) / 2
    candidate_above = (cb[1] + cb[3]) / 2 < (tb[1] + tb[3]) / 2
    if member_above != candidate_above:
        return None
    # A caption component must remain on the table-facing side of the asset.
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    if member_above and cb[3] > tb[1] + tolerance:
        return None
    if not member_above and cb[1] < tb[3] - tolerance:
        return None
    if not _column_compatible(candidate, table, page_width):
        return None

    vertical_gap = max(0.0, max(cb[1], mb[1]) - min(cb[3], mb[3]))
    local_height = max(1.0, min(cb[3] - cb[1], mb[3] - mb[1]))
    gap_page = vertical_gap / page_height
    gap_lines = vertical_gap / local_height
    if (
        gap_page > config.fragment_max_gap_page_ratio
        or gap_lines > config.fragment_max_line_gap_ratio
    ):
        return None
    horizontal = _overlap_ratio(cb, mb)
    left_delta = abs(cb[0] - mb[0]) / page_width
    right_delta = abs(cb[2] - mb[2]) / page_width
    aligned = (
        horizontal >= config.fragment_min_horizontal_overlap
        or min(left_delta, right_delta) <= config.fragment_edge_alignment_page_ratio
    )
    if not aligned:
        return None
    blocker = _has_blocker(candidate, member, page_regions)
    if blocker:
        return None

    order_delta = abs(_order(candidate) - _order(member))
    style_a, style_b = candidate.get("typography") or {}, member.get("typography") or {}
    shared_style = bool(style_a and style_b) and all(
        style_a.get(key) == style_b.get(key)
        for key in ("font_family", "font_size", "italic", "bold")
        if key in style_a and key in style_b
    )
    punctuation_continuation = bool(
        text[:1].islower()
        or str(member.get("text") or "").rstrip().endswith((",", ";", ":", "(", "-"))
    )
    paragraph_penalty = 0.0
    if _BODY_SENTENCE_RE.search(text):
        paragraph_penalty -= 2.8
    if len(re.findall(r"[.!?](?:\s|$)", text)) > 1:
        paragraph_penalty -= 1.5
    components = {
        "local_proximity": 2.7
        * max(0.0, 1.0 - gap_lines / config.fragment_max_line_gap_ratio),
        "horizontal_compatibility": 1.8 * horizontal,
        "edge_alignment": (
            1.0
            if min(left_delta, right_delta) <= config.fragment_edge_alignment_page_ratio
            else 0.0
        ),
        "reading_order": (
            1.1 if order_delta <= 1 else (0.5 if order_delta <= 2 else -0.8)
        ),
        "table_corridor": (
            0.8
            if _overlap_ratio(cb, tb) >= config.min_horizontal_overlap_ratio
            else 0.0
        ),
        "detector_class": 0.8 if candidate.get("type") == "Caption" else 0.0,
        "lexical_continuation": 0.5 if punctuation_continuation else 0.0,
        "typography": 0.4 if shared_style else 0.0,
        "overlap_evidence": (
            0.5
            if relationship_kinds & {"FRAGMENT_CANDIDATE", "COMPLEMENTARY_FRAGMENT"}
            else 0.0
        ),
        "conflict_penalty": (
            -2.5
            if relationship_kinds
            & {"INVALID_OCCLUSION", "CLASS_CONFLICT", "AMBIGUOUS_OVERLAP"}
            else 0.0
        ),
        "body_paragraph_penalty": paragraph_penalty,
    }
    score = sum(components.values())
    if score < config.fragment_acceptance_score:
        return None
    return {
        "table_region_id": str(table["layout_region_id"]),
        "region_id": str(candidate["layout_region_id"]),
        "member_region_id": str(member["layout_region_id"]),
        "proposed_role": "caption_fragment",
        "score": round(score, 4),
        "accepted": False,
        "direction": "above" if member_above else "below",
        "features": {
            "vertical_gap_page_ratio": round(gap_page, 6),
            "vertical_gap_line_ratio": round(gap_lines, 4),
            "horizontal_overlap_ratio": round(horizontal, 6),
            "left_alignment_page_ratio": round(left_delta, 6),
            "right_alignment_page_ratio": round(right_delta, 6),
            "reading_order_delta": order_delta,
            "relationship_kinds": sorted(relationship_kinds),
            "components": components,
        },
    }


def _group_bbox(regions: list[LayoutRegion]) -> list[float]:
    boxes = [list(map(float, region["bbox_px"])) for region in regions]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _caption_table_corridor_edge(
    candidate: LayoutRegion,
    seed: LayoutRegion,
    table: LayoutRegion,
    page_width: float,
    page_height: float,
    config: TableContextConfig,
    relationship_kinds: set[str],
) -> dict[str, Any] | None:
    """Associate text physically sandwiched between a caption and its table.

    Once a caption seed has been unambiguously assigned to a table, geometry is
    authoritative for the intervening area.  In particular, paragraph-like
    wording must not prevent a detector-split caption continuation from being
    included.  This is intentionally distinct from speculative graph growth
    beyond the seed-to-table corridor, where the stricter semantic safeguards
    still apply.
    """
    if candidate.get("type") not in _TEXT_TYPES:
        return None
    text = str(candidate.get("text") or "").strip()
    if not text:
        return None

    cb = list(map(float, candidate["bbox_px"]))
    sb = list(map(float, seed["bbox_px"]))
    tb = list(map(float, table["bbox_px"]))
    tolerance = config.max_boundary_overlap_page_ratio * page_height
    seed_above = (sb[1] + sb[3]) / 2.0 < (tb[1] + tb[3]) / 2.0
    if seed_above:
        between = cb[1] >= sb[3] - tolerance and cb[3] <= tb[1] + tolerance
    else:
        between = cb[1] >= tb[3] - tolerance and cb[3] <= sb[1] + tolerance
    if not between or not _column_compatible(candidate, table, page_width):
        return None

    table_overlap = _overlap_ratio(cb, tb)
    seed_overlap = _overlap_ratio(cb, sb)
    if max(table_overlap, seed_overlap) < config.min_horizontal_overlap_ratio:
        return None

    return {
        "table_region_id": str(table["layout_region_id"]),
        "region_id": str(candidate["layout_region_id"]),
        "member_region_id": str(seed["layout_region_id"]),
        "proposed_role": "caption_fragment",
        "score": 10.0,
        "accepted": False,
        "direction": "above" if seed_above else "below",
        "features": {
            "rule": "text_between_associated_caption_and_table",
            "horizontal_overlap_with_table": round(table_overlap, 6),
            "horizontal_overlap_with_caption_seed": round(seed_overlap, 6),
            "body_text_semantics_ignored": True,
            "relationship_kinds": sorted(relationship_kinds),
            "components": {
                "overlap_evidence": (
                    0.5
                    if relationship_kinds
                    & {"FRAGMENT_CANDIDATE", "COMPLEMENTARY_FRAGMENT"}
                    else 0.0
                )
            },
        },
    }


def associate_table_context(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    *,
    document_id: str,
    config: TableContextConfig | None = None,
    relationships: list[dict[str, Any]] | None = None,
    index: RegionIndex | None = None,
    metrics: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Create table groups using constrained, explainable relationship scoring.

    Raw regions are referenced by ID and are never reclassified or resized.
    Candidate regions have exclusive ownership; uncertain competing assignments
    are deliberately left unattached.
    """
    config = config or TableContextConfig()
    relationship_kinds: dict[frozenset[str], set[str]] = defaultdict(set)
    for relationship in relationships or []:
        left = relationship.get("left_region_id") or relationship.get("child_region_id")
        right = relationship.get("right_region_id") or relationship.get(
            "parent_region_id"
        )
        if left and right:
            relationship_kinds[frozenset((str(left), str(right)))].add(
                str(relationship.get("kind") or "")
            )
    index = index or RegionIndex.build(regions, pages)
    metrics = metrics if metrics is not None else {}
    metrics.update(tables=0, candidate_role_pairs=0, scored_edges=0)

    groups: list[dict[str, Any]] = []
    for page_number in sorted(index.by_page):
        page_regions = index.by_page[page_number]
        tables = sorted(
            (region for region in page_regions if region.get("type") == "Table"),
            key=lambda region: (
                int(region.get("layout_reading_order") or 10**9),
                float(region["bbox_px"][1]),
                float(region["bbox_px"][0]),
            ),
        )
        width, height = index.page_sizes.get(page_number, (1.0, 1.0))
        metrics["tables"] += len(tables)
        page_groups: dict[str, dict[str, Any]] = {}
        for ordinal, table in enumerate(tables, 1):
            internal_id = f"{document_id}:p{page_number:04d}:t{ordinal:02d}"
            page_groups[table["layout_region_id"]] = {
                "internal_id": internal_id,
                "page_number": page_number,
                "table_region_id": table["layout_region_id"],
                "table_bbox": list(table["bbox_px"]),
                "identifier_region_ids": [],
                "caption_region_ids": [],
                "note_region_ids": [],
                "printed_label": None,
                "associations": [],
                "confidence": 0.0,
                "group_bbox": list(table["bbox_px"]),
                "continuation_group_id": None,
                "continuation_status": "page_local",
            }

        edges: list[dict[str, Any]] = []
        for table in tables:
            for candidate in page_regions:
                if candidate is table:
                    continue
                for role in ("caption", "note"):
                    metrics["candidate_role_pairs"] += 1
                    if role == "caption" and not (
                        candidate.get("type") == "Caption"
                        or _TABLE_LABEL_RE.match(str(candidate.get("text") or ""))
                    ):
                        continue
                    if role == "note" and not (
                        candidate.get("type") == "Footnote"
                        or _NOTE_RE.search(str(candidate.get("text") or ""))
                        or bool((candidate.get("typography") or {}).get("superscript"))
                        or candidate.get("has_superscript")
                    ):
                        continue
                    edge = _score_edge(
                        candidate, table, role, page_regions, width, height, config
                    )
                    if edge and edge["score"] >= config.acceptance_score:
                        edges.append(edge)
                        metrics["scored_edges"] += 1

        candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            candidates[edge["region_id"]].append(edge)
        region_by_id = {region["layout_region_id"]: region for region in page_regions}
        for region_id, alternatives in candidates.items():
            alternatives.sort(key=lambda edge: edge["score"], reverse=True)
            winner = alternatives[0]
            if (
                len(alternatives) > 1
                and winner["score"] - alternatives[1]["score"] < config.ambiguity_margin
            ):
                continue
            winner["accepted"] = True
            winner["alternative_count"] = len(alternatives) - 1
            group = page_groups[winner["table_region_id"]]
            if winner["proposed_role"] == "caption":
                if winner["printed_label"]:
                    group["identifier_region_ids"].append(region_id)
                    group["printed_label"] = (
                        group["printed_label"] or winner["printed_label"]
                    )
                    if winner["caption_text_after_label"]:
                        group["caption_region_ids"].append(region_id)
                else:
                    group["caption_region_ids"].append(region_id)
            else:
                group["note_region_ids"].append(region_id)
            group["associations"].append(winner)

        # Grow captions from accepted label/class seeds using local adjacency.
        # Each round uses the current component as its frontier and assigns a
        # fragment only when one table wins by a clear margin.
        owned = {
            region_id
            for group in page_groups.values()
            for key in (
                "identifier_region_ids",
                "caption_region_ids",
                "note_region_ids",
            )
            for region_id in group[key]
        }
        tables_by_id = {str(table["layout_region_id"]): table for table in tables}

        # A detector frequently emits only the short "Table N." label as a
        # Caption and emits the description as ordinary Text.  Include every
        # text region physically between an accepted caption seed and its table
        # before attempting conservative graph growth outside that corridor.
        corridor_proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for table_id, group in page_groups.items():
            seeds = list(
                dict.fromkeys(
                    group["identifier_region_ids"] + group["caption_region_ids"]
                )
            )
            for seed_id in seeds:
                for candidate in page_regions:
                    candidate_id = str(candidate.get("layout_region_id"))
                    if candidate_id in owned or candidate_id == table_id:
                        continue
                    edge = _caption_table_corridor_edge(
                        candidate,
                        region_by_id[seed_id],
                        tables_by_id[table_id],
                        width,
                        height,
                        config,
                        relationship_kinds.get(
                            frozenset((candidate_id, seed_id)), set()
                        ),
                    )
                    if edge:
                        corridor_proposals[candidate_id].append(edge)
        for region_id, alternatives in corridor_proposals.items():
            table_ids = {edge["table_region_id"] for edge in alternatives}
            # Do not guess when the same physical text lies in corridors for
            # multiple tables. Within one table, the closest seed is sufficient.
            if len(table_ids) != 1:
                continue
            winner = min(
                alternatives,
                key=lambda edge: abs(
                    _order(region_by_id[edge["member_region_id"]])
                    - _order(region_by_id[region_id])
                ),
            )
            winner["accepted"] = True
            winner["alternative_count"] = len(alternatives) - 1
            group = page_groups[winner["table_region_id"]]
            group["caption_region_ids"].append(region_id)
            group["associations"].append(winner)
            owned.add(region_id)

        while True:
            proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for table_id, group in page_groups.items():
                members = list(
                    dict.fromkeys(
                        group["identifier_region_ids"] + group["caption_region_ids"]
                    )
                )
                if not members:
                    continue
                for candidate in page_regions:
                    candidate_id = str(candidate.get("layout_region_id"))
                    if candidate_id in owned or candidate_id == table_id:
                        continue
                    for member_id in members:
                        evidence = relationship_kinds.get(
                            frozenset((candidate_id, member_id)), set()
                        )
                        edge = _fragment_edge(
                            candidate,
                            region_by_id[member_id],
                            tables_by_id[table_id],
                            page_regions,
                            width,
                            height,
                            config,
                            evidence,
                        )
                        if edge:
                            proposals[candidate_id].append(edge)
            accepted_any = False
            for region_id, alternatives in proposals.items():
                # Retain the strongest path per table before comparing parents.
                best_by_table: dict[str, dict[str, Any]] = {}
                for edge in alternatives:
                    table_id = edge["table_region_id"]
                    if (
                        table_id not in best_by_table
                        or edge["score"] > best_by_table[table_id]["score"]
                    ):
                        best_by_table[table_id] = edge
                ranked = sorted(
                    best_by_table.values(), key=lambda item: item["score"], reverse=True
                )
                winner = ranked[0]
                if (
                    len(ranked) > 1
                    and winner["score"] - ranked[1]["score"]
                    < config.fragment_ambiguity_margin
                ):
                    continue
                winner["accepted"] = True
                winner["alternative_count"] = len(ranked) - 1
                group = page_groups[winner["table_region_id"]]
                group["caption_region_ids"].append(region_id)
                group["associations"].append(winner)
                owned.add(region_id)
                accepted_any = True
            if not accepted_any:
                break

        for table in tables:
            group = page_groups[table["layout_region_id"]]
            for key in (
                "identifier_region_ids",
                "caption_region_ids",
                "note_region_ids",
            ):
                group[key].sort(
                    key=lambda region_id: (
                        int(
                            region_by_id[region_id].get("layout_reading_order") or 10**9
                        ),
                        float(region_by_id[region_id]["bbox_px"][1]),
                    )
                )
            associated_regions = [table] + [
                region_by_id[region_id]
                for key in (
                    "identifier_region_ids",
                    "caption_region_ids",
                    "note_region_ids",
                )
                for region_id in group[key]
            ]
            group["group_bbox"] = _group_bbox(associated_regions)
            scores = [item["score"] for item in group["associations"]]
            group["confidence"] = (
                round(min(1.0, sum(scores) / max(1, len(scores)) / 8.0), 4)
                if scores
                else 1.0
            )
            group["caption_fragment_association"] = {
                "strategy": "caption_table_corridor_then_seeded_local_graph",
                "semantic_role": "table_caption",
                "fragment_region_ids": list(group["caption_region_ids"]),
                "source_geometry_preserved": True,
            }
            groups.append(group)
    return groups
