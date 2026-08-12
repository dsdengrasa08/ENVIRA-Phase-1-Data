from types import SimpleNamespace

import envira_pdf_layout.caption_decomposition as module
from envira_pdf_layout.caption_decomposition import TextLine, decompose_captions
from envira_pdf_layout.config import CaptionDecompositionConfig

PAGE = {
    "page_number": 1,
    "image_width_px": 1000,
    "image_height_px": 1000,
    "page_width_pt": 500,
    "page_height_pt": 500,
}


def line(text, top):
    return TextLine(text, (100, top, 700, top + 18))


def region(rid, kind, box, text=""):
    return {
        "layout_region_id": rid,
        "page_number": 1,
        "type": kind,
        "bbox_px": list(box),
        "text": text,
        "page_image_path": "unused.png",
        "layout_reading_order": 1,
    }


def run(monkeypatch, lines, verifier=None, assets=None):
    monkeypatch.setattr(module, "_native_lines", lambda *args: lines)
    caption = region("cap", "Caption", (100, 300, 700, 500), "merged")
    config = CaptionDecompositionConfig(glm_verify=verifier is not None)
    return decompose_captions(
        [caption] + (assets or []),
        [PAGE],
        SimpleNamespace(pdf_path="x"),
        config,
        verifier,
    )


def test_figure_then_table_is_split_on_native_line_geometry(monkeypatch):
    lines = [
        line("Fig. 1. Rainfall", 310),
        line("continued", 332),
        line("Table 2. Treatments", 400),
        line("continued", 422),
    ]
    assets = [
        region("fig", "Figure", (100, 100, 700, 290)),
        region("table", "Table", (100, 510, 700, 800)),
    ]
    output, diagnostics = run(monkeypatch, lines, assets=assets)
    derived = [r for r in output if r["type"].endswith(" Caption")]
    assert [r["type"] for r in derived] == ["Figure Caption", "Table Caption"]
    assert derived[0]["bbox_px"][3] == 350
    assert derived[1]["bbox_px"][1] == 400
    assert derived[0]["parent_region_id"] == "fig"
    assert derived[1]["parent_region_id"] == "table"
    assert diagnostics[0]["status"] == "decomposed"


def test_reverse_and_same_type_order_are_not_hard_coded(monkeypatch):
    lines = [
        line("Table IV. Data", 310),
        line("details", 332),
        line("Fig 3a. Plot", 400),
        line("details", 422),
    ]
    output, _ = run(monkeypatch, lines)
    assert [r["type"] for r in output] == ["Table Caption", "Figure Caption"]

    lines = [
        line("Fig. 2. First", 310),
        line("details", 332),
        line("Figure 3. Second", 400),
        line("details", 422),
    ]
    output, _ = run(monkeypatch, lines)
    assert [r["type"] for r in output] == ["Figure Caption", "Figure Caption"]


def test_in_sentence_reference_is_not_an_anchor(monkeypatch):
    lines = [
        line("Fig. 3. Comparison with values reported in Table 2.", 310),
        line("The caption continues here.", 332),
        line("and here", 354),
        line("last", 376),
    ]
    output, diagnostics = run(monkeypatch, lines)
    assert [r["layout_region_id"] for r in output] == ["cap"]
    assert diagnostics[0]["status"] != "decomposed"


def test_fuzzy_anchor_requires_context_and_legacy_glm_response_falls_back(monkeypatch):
    lines = [
        line("F1g. 1. Plot", 310),
        line("details", 332),
        line("Tab1e 2. Values", 400),
        line("details", 422),
    ]
    # Fuzzy anchors score below the default automatic threshold.
    output, diagnostics = run(monkeypatch, lines)
    assert output[0]["layout_region_id"] == "cap"
    assert diagnostics[0]["status"] == "abstained_insufficient_anchors"

    exact = [
        line("Fig. 1. Plot", 310),
        line("details", 332),
        line("Table 2. Values", 400),
        line("details", 422),
    ]
    verifier = SimpleNamespace(
        verify=lambda *args: {"available": True, "verified": False, "confidence": 0.8}
    )
    output, diagnostics = run(monkeypatch, exact, verifier=verifier)
    assert [item["type"] for item in output] == ["Figure Caption", "Table Caption"]
    assert diagnostics[0]["geometry_source"] == "native_pdf"


def test_glm_scans_every_caption_and_uses_label_to_next_label(monkeypatch):
    monkeypatch.setattr(module, "_native_lines", lambda *args: [])
    caption = region("cap", "Caption", (100, 300, 700, 500), "merged")
    calls = []

    class Verifier:
        def scan(self, image_path, crop):
            calls.append((image_path, crop))
            return {
                "available": True,
                "confidence": 0.96,
                "lines": [
                    {"text": "Fig. 1. Rainfall", "bbox": [0, 20, 1000, 150]},
                    {"text": "figure continuation", "bbox": [0, 170, 1000, 300]},
                    {"text": "Table 2. Treatments", "bbox": [0, 550, 1000, 680]},
                    {"text": "table continuation", "bbox": [0, 700, 1000, 850]},
                ],
                "anchors": [
                    {"line_index": 0, "kind": "figure", "label": "Fig. 1"},
                    {"line_index": 2, "kind": "table", "label": "Table 2"},
                ],
            }

    output, diagnostics = decompose_captions(
        [caption],
        [PAGE],
        SimpleNamespace(pdf_path="x"),
        CaptionDecompositionConfig(glm_verify=True),
        Verifier(),
    )
    assert len(calls) == 1
    assert [item["type"] for item in output] == ["Figure Caption", "Table Caption"]
    assert output[0]["text"] == "Fig. 1. Rainfall figure continuation"
    assert output[1]["text"] == "Table 2. Treatments table continuation"
    assert output[0]["bbox_px"][3] == 360
    assert output[1]["bbox_px"][1] == 410
    assert diagnostics[0]["geometry_source"] == "glm_ocr"


def test_intervening_paragraph_becomes_its_own_text_region(monkeypatch):
    lines = [
        line("Fig. 1. Plot", 310),
        line("caption details", 332),
        line(
            "This is a normal paragraph accidentally enclosed in the detector region.",
            380,
        ),
        line("It has a second complete sentence.", 402),
        line("Table 2. Values", 470),
        line("table details", 492),
    ]
    output, diagnostics = run(monkeypatch, lines)
    assert [r["type"] for r in output] == ["Figure Caption", "Text", "Table Caption"]
    assert "normal paragraph" in output[1]["text"]
    assert diagnostics[0]["status"] == "decomposed"
