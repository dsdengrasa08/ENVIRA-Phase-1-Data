from envira_pdf_layout.semantic_caption import (
    body_reference_evidence,
    caption_reference_quality,
    find_table_reference_mention,
    leading_table_label_fragment,
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


def test_embedded_singular_table_mention_is_available_only_as_fragment_evidence():
    mention = find_table_reference_mention("See Table 2 for treatment codes.")
    assert mention and mention.number == "2" and mention.position == "embedded"
    assert find_table_reference_mention("Results from Tables 3 and 4 differ.") is None


def test_note_derived_lowercase_letter_identifier_is_not_authoritative():
    text = "Table a See Table 2 for treatment codes."
    reference = parse_semantic_caption_reference(text)
    quality = caption_reference_quality(text, reference)
    assert reference and reference.number == "a"
    assert quality["authoritative"] is False
    assert quality["reasons"] == [
        "lowercase_single_letter_identifier",
        "table_note_continuation",
        "immediate_trailing_table_reference",
    ]


def test_legitimate_uppercase_letter_identifier_remains_authoritative():
    text = "Table A. Experimental outcomes"
    reference = parse_semantic_caption_reference(text)
    quality = caption_reference_quality(text, reference)
    assert reference and reference.number == "A"
    assert quality["authoritative"] is True


def test_bare_table_label_can_be_completed_by_a_neighboring_number():
    assert leading_table_label_fragment("Table Average N2O flux") == "Table"
    assert leading_table_label_fragment("Table 4. Average N2O flux") is None
