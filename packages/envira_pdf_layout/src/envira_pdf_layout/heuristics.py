"""Explainable, data-driven evidence for document-family layout heuristics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal

EvidenceCategory = Literal[
    "generic_geometry",
    "generic_structure",
    "scholarly_article_structure",
    "language_specific_lexical",
    "publisher_specific_lexical",
]


@dataclass(frozen=True)
class HeuristicEvidence:
    category: EvidenceCategory
    name: str
    matched: bool
    value: Any = None
    threshold: Any = None
    profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeuristicDecision:
    action: Literal["keep", "exclude", "protect", "observe"]
    reason: str
    evidence: tuple[HeuristicEvidence, ...]
    destructive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "destructive": self.destructive,
            "evidence": [item.to_dict() for item in self.evidence],
        }


PUBLISHER_PROFILES: dict[str, dict[str, Any]] = {
    "elsevier_sciencedirect": {
        "terms": (
            "contents lists available",
            "science direct",
            "sciencedirect",
            "journal homepage",
            "elsevier",
            "check for updates",
            "crossmark",
            "cross mark",
        ),
    },
    "generic_academic_publishers": {
        "terms": (
            "springer",
            "springer nature",
            "elsevier",
            "wiley",
            "blackwell",
            "taylor & francis",
            "taylor and francis",
            "sage",
            "mdpi",
            "frontiers",
            "nature portfolio",
            "biomed central",
            "bmc",
            "oxford university press",
            "cambridge university press",
        )
    },
}


def publisher_matches(text: str, enabled_profiles: tuple[str, ...]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return [
        name
        for name in enabled_profiles
        if name in PUBLISHER_PROFILES
        and any(term in normalized for term in PUBLISHER_PROFILES[name]["terms"])
    ]


def publisher_tokens(text: str, enabled_profiles: tuple[str, ...]) -> list[str]:
    """Return profile terms found in text for footer diagnostics."""
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return sorted(
        {
            term
            for name in enabled_profiles
            for term in PUBLISHER_PROFILES.get(name, {}).get("terms", ())
            if re.search(rf"\b{re.escape(term)}\b", normalized)
        }
    )


def classify_document_family(regions: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a conservative, explainable family classification."""
    page1 = [r for r in regions if int(r.get("page_number", -1)) == 1]
    text = "\n".join(str(r.get("text") or r.get("orig") or "") for r in page1)
    signals = {
        "abstract_heading": bool(re.search(r"(?im)^\s*(abstract|summary)\b", text)),
        "keywords_heading": bool(re.search(r"(?im)^\s*keywords?\b", text)),
        "scholarly_labels": any(
            r.get("type") in {"Caption", "Reference"} for r in regions
        ),
    }
    scholarly_score = sum(signals.values())
    alternatives = {
        "thesis": bool(re.search(r"(?i)\b(thesis|dissertation)\b", text)),
        "technical_report": bool(
            re.search(r"(?i)\btechnical report\b|\breport no\.?\b", text)
        ),
        "book_or_chapter": bool(re.search(r"(?i)\bchapter\s+\d+\b|\bisbn\b", text)),
        "form": any(r.get("type") in {"Form", "Key-value"} for r in regions),
    }
    explicit = next((name for name, matched in alternatives.items() if matched), None)
    family = explicit or ("scholarly_article" if scholarly_score >= 2 else "unknown")
    confidence = 0.8 if explicit else scholarly_score / 3
    return {
        "family": family,
        "confidence": round(confidence, 3),
        "signals": {**signals, **alternatives},
    }


def page1_publisher_decision(
    *,
    text: str,
    center_y_ratio: float,
    title_bottom_ratio: float | None,
    body_anchor_ratio: float | None,
    enabled_profiles: tuple[str, ...],
    mode: str,
) -> HeuristicDecision:
    """Evaluate publisher furniture; lexical evidence never acts alone."""
    matches = publisher_matches(text, enabled_profiles)
    upper_band = center_y_ratio <= 0.44
    outside_body = body_anchor_ratio is None or center_y_ratio < body_anchor_ratio
    after_or_without_title = (
        title_bottom_ratio is None or center_y_ratio >= title_bottom_ratio
    )
    evidence = (
        HeuristicEvidence(
            "publisher_specific_lexical",
            "publisher_profile_match",
            bool(matches),
            matches,
            profile=matches[0] if matches else None,
        ),
        HeuristicEvidence(
            "generic_geometry", "upper_page_band", upper_band, center_y_ratio, 0.44
        ),
        HeuristicEvidence(
            "generic_structure",
            "before_body_anchor",
            outside_body,
            center_y_ratio,
            body_anchor_ratio,
        ),
        HeuristicEvidence(
            "generic_structure",
            "after_or_without_title",
            after_or_without_title,
            center_y_ratio,
            title_bottom_ratio,
        ),
    )
    confirmed = bool(matches) and upper_band and outside_body and after_or_without_title
    destructive = (mode == "active" and bool(matches)) or (
        mode == "confirmatory" and confirmed
    )
    if destructive:
        return HeuristicDecision(
            "exclude", "page1_upper_publisher_or_update_text", evidence, True
        )
    return HeuristicDecision(
        "observe" if matches else "keep",
        "publisher_evidence_observed" if matches else "no_publisher_evidence",
        evidence,
    )
