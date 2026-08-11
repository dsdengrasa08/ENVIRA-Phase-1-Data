from envira_pdf_layout.region_conversion import docling_label_to_region_type


def test_label_mapping():
    assert docling_label_to_region_type("section_header") == "Section-header"
    assert docling_label_to_region_type("picture") == "Figure"
    assert docling_label_to_region_type("new_label") == "Unknown"
