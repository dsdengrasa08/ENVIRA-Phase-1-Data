from envira_pdf_layout.semantic_caption import (
    body_reference_evidence,
    parse_semantic_caption_reference,
)


def test_generalized_table_identifier_variants():
    values = [
        "Table 3. Experimental results",
        "TABLE IV Results",
        "Table S2: Supplementary outcomes",
        "Supplementary Table 2 Outcomes",
        "Tab. 6 Results",
        "Table B.3 Appendix results",
    ]
    assert all(parse_semantic_caption_reference(value) for value in values)


def test_embedded_and_plural_references_are_not_caption_identifiers():
    values = [
        "The values are reported in Table 3.",
        "As shown in Table 3, emissions increased.",
        "Results from Tables 3 and 4 indicate a difference.",
        "The result differed significantly (Table 4).",
        "See Table S2 for treatment codes.",
    ]
    assert not any(parse_semantic_caption_reference(value) for value in values)
    assert all(body_reference_evidence(value) for value in values)


def test_ocr_tolerance_is_opt_in_and_leading_only():
    assert parse_semantic_caption_reference("Tab1e 3. Results") is None
    parsed = parse_semantic_caption_reference(
        "Tab1e 3. Results", allow_ocr_tolerance=True
    )
    assert parsed and parsed.kind == "table" and parsed.ocr_tolerant
    assert (
        parse_semantic_caption_reference(
            "Values in Tab1e 3 differ", allow_ocr_tolerance=True
        )
        is None
    )
