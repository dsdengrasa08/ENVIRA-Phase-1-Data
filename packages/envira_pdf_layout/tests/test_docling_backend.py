from types import SimpleNamespace

from envira_pdf_layout.docling_backend import DoclingBackend


class Document:
    def __init__(self):
        self.markdown_calls = 0

    def export_to_dict(self):
        return {"texts": []}

    def export_to_markdown(self):
        self.markdown_calls += 1
        return "markdown"


class Converter:
    def __init__(self, document):
        self.document = document

    def convert(self, *_args, **_kwargs):
        return SimpleNamespace(document=self.document)


def test_conversion_skips_unused_markdown_materialization(tmp_path):
    document = Document()
    conversion = DoclingBackend(Converter(document)).convert(
        tmp_path / "source.pdf", (1, 1), materialize_markdown=False
    )

    assert conversion.raw_document == {"texts": []}
    assert conversion.markdown == ""
    assert document.markdown_calls == 0


def test_conversion_materializes_markdown_by_default(tmp_path):
    document = Document()
    conversion = DoclingBackend(Converter(document)).convert(
        tmp_path / "source.pdf", (1, 1)
    )

    assert conversion.markdown == "markdown"
    assert document.markdown_calls == 1
