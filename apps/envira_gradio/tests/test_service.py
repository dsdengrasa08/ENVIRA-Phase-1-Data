from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace

from PIL import Image

from envira_gradio.service import processing as processing_module
from envira_gradio.service.processing import ProcessingService
from envira_gradio.settings import AppSettings


class Progress:
    def __init__(self): self.updates = []
    def __call__(self, value, **kwargs): self.updates.append((value, kwargs))


@dataclass(frozen=True)
class Document:
    source_pdf: Path
    run_id: str = ""


@dataclass(frozen=True)
class Config:
    document: Document


def test_service_returns_only_ordered_overlay_paths_and_cleans_staging(tmp_path, monkeypatch):
    upload = tmp_path / "upload.pdf"
    upload.write_bytes(b"%PDF-fake")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}\n")
    settings = AppSettings(tmp_path / "drive", config_file, tmp_path / "temp").normalized()
    settings.temporary_root.mkdir()
    base = Config(Document(upload))
    overlay_dir = settings.persistent_root / "overlays"
    overlay_dir.mkdir(parents=True)
    paths = [overlay_dir / "page_0002.png", overlay_dir / "page_0001.png"]
    for path in paths:
        Image.new("RGB", (12, 8), "white").save(path)
    monkeypatch.setattr(
        processing_module,
        "run_pdf",
        lambda *args, **kwargs: SimpleNamespace(overlay_paths=tuple(paths)),
    )
    progress = Progress()
    service = ProcessingService(settings, base, object())
    result = service.process(upload, progress)
    assert all(isinstance(item[0], Image.Image) for item in result)
    assert [item[0].size for item in result] == [(12, 8), (12, 8)]
    assert [item[1] for item in result] == ["Page 1", "Page 2"]
    assert list(settings.temporary_root.iterdir()) == []
    assert progress.updates[-1][0] == 1.0
