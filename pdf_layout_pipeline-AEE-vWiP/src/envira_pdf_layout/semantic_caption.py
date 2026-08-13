"""Shared, conservative parsing of semantic asset-caption identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable


_LEADING_NOISE_RE = re.compile(r"^[\s\u2022\u25aa\u25cf|_]+")
_REFERENCE_RE = re.compile(
    r"^(?P<label>(?:(?:supplementary|supplemental|extended\s+data)\s+)?"
    r"(?P<kind>fig(?:ure)?\.?|table|tab\.?|equation|eq\.?|algorithm|listing)\s*"
    r"(?P<number>(?:[A-Z]\s*[.\-]?\s*)?\d+(?:\s*[.\-]\s*\d+)?|[IVXLCDM]+|[A-Z]))"
    r"(?:\s*[:.\-])?(?=\s|$)",
    re.IGNORECASE,
)
_OCR_TABLE_RE = re.compile(
    r"^(?P<label>(?:supplementary\s+|supplemental\s+)?"
    r"ta\s*b\s*[1il]\s*e\s*"
    r"(?P<number>(?:[A-Z]\s*)?\d+|[IVXLCDM]+))"
    r"(?:\s*[:.\-])?(?=\s|$)",
    re.IGNORECASE,
)
_PROSE_LEAD_RE = re.compile(
    r"\b(?:as\s+shown\s+in|shown\s+in|reported\s+in|according\s+to|"
    r"results?\s+from|values?\s+in|compared\s+(?:with|in)|see)\s+$",
    re.IGNORECASE,
)
_PLURAL_RE = re.compile(r"\btables?\s+\w+\s+(?:and|to|[-–])\s+\w+", re.IGNORECASE)
_TABLE_MENTION_RE = re.compile(
    r"\b(?P<label>(?:(?:supplementary|supplemental)\s+)?(?:table|tab\.?)\s*"
    r"(?P<number>(?:[A-Z]\s*[.\-]?\s*)?\d+(?:\s*[.\-]\s*\d+)?|"
    r"[IVXLCDM]+|[A-Z]))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticCaptionReference:
    kind: str
    label: str
    number: str
    start: int
    end: int
    position: str
    confidence: float
    ocr_tolerant: bool = False


def normalize_caption_text(value: Any) -> str:
    """Normalize OCR whitespace and punctuation without losing lexical content."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u00a0", " ").replace("–", "-").replace("—", "-")
    return " ".join(text.split())


def parse_semantic_caption_reference(
    value: Any, *, allow_ocr_tolerance: bool = False
) -> SemanticCaptionReference | None:
    """Parse a structurally leading asset identifier, never an embedded citation."""
    text = normalize_caption_text(value)
    cleaned = _LEADING_NOISE_RE.sub("", text)
    offset = len(text) - len(cleaned)
    match = _REFERENCE_RE.match(cleaned)
    tolerant = False
    if not match and allow_ocr_tolerance:
        match = _OCR_TABLE_RE.match(cleaned)
        tolerant = bool(match)
    if not match:
        return None
    raw_kind = (match.groupdict().get("kind") or "table").casefold().rstrip(".")
    kind = (
        "figure"
        if raw_kind in {"fig", "figure"}
        else "table"
        if raw_kind in {"tab", "table"}
        else "equation"
        if raw_kind in {"eq", "equation"}
        else raw_kind
    )
    return SemanticCaptionReference(
        kind=kind,
        label=match.group("label").strip(),
        number=re.sub(r"\s+", "", match.group("number")),
        start=offset + match.start(),
        end=offset + match.end(),
        position="leading" if offset == 0 else "near_leading",
        confidence=0.86 if tolerant else (1.0 if offset == 0 else 0.94),
        ocr_tolerant=tolerant,
    )


def body_reference_evidence(value: Any) -> list[str]:
    """Return explicit reasons that text resembles prose/table discussion."""
    text = normalize_caption_text(value)
    reasons: list[str] = []
    table_match = re.search(r"\btable(?:s)?\b", text, re.IGNORECASE)
    if table_match and text[: table_match.start()].strip():
        reasons.append("identifier_embedded_in_prose")
        if _PROSE_LEAD_RE.search(text[: table_match.start()]):
            reasons.append("cross_reference_lead_in")
    if _PLURAL_RE.search(text):
        reasons.append("plural_table_reference")
    if re.search(r"\([^)]*\btable\b[^)]*\)", text, re.IGNORECASE):
        reasons.append("parenthetical_reference")
    return reasons


def find_table_reference_mention(value: Any) -> SemanticCaptionReference | None:
    """Find one singular Table identifier embedded in a larger text fragment.

    This is supporting fragment evidence, not a stand-alone caption decision.
    Callers must require an already-associated Caption and same-side geometry.
    """
    text = normalize_caption_text(value)
    if _PLURAL_RE.search(text):
        return None
    match = _TABLE_MENTION_RE.search(text)
    if not match:
        return None
    return SemanticCaptionReference(
        kind="table",
        label=match.group("label").strip(),
        number=re.sub(r"\s+", "", match.group("number")),
        start=match.start(),
        end=match.end(),
        position="leading" if match.start() == 0 else "embedded",
        confidence=0.72 if match.start() else 1.0,
    )


def parse_fragmented_table_reference(
    values: Iterable[Any], *, allow_ocr_tolerance: bool = False
) -> tuple[SemanticCaptionReference, str] | None:
    """Parse an identifier reconstructed from a small adjacent-region sequence."""
    combined = normalize_caption_text(" ".join(str(value or "") for value in values))
    reference = parse_semantic_caption_reference(
        combined, allow_ocr_tolerance=allow_ocr_tolerance
    )
    return (reference, combined) if reference and reference.kind == "table" else None
