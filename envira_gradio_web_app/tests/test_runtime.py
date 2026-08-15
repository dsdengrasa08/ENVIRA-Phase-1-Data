from pathlib import Path
from types import SimpleNamespace

from envira_gradio.pipeline import runtime
from envira_gradio.pipeline.config import RuntimeConfig


def test_colab_keeps_executables_local_and_model_blobs_persistent(
    tmp_path: Path, monkeypatch
):
    drive_root = tmp_path / "drive"
    local_root = tmp_path / "content"
    monkeypatch.setattr(runtime, "in_colab", lambda: True)
    monkeypatch.delitem(runtime.sys.modules, "gradio.tunneling", raising=False)
    config = RuntimeConfig(
        use_google_drive=False,
        project_dir=drive_root,
        local_cache_root=local_root,
    )

    report = runtime.prepare_runtime(config)

    assert report["hf_home"] == local_root / "huggingface"
    assert report["hf_hub_cache"] == drive_root / "cache/huggingface/hub"
    assert report["hf_home"].is_dir()
    assert report["hf_hub_cache"].is_dir()
    assert runtime.os.environ["HF_HOME"] == str(local_root / "huggingface")
    assert runtime.os.environ["HF_HUB_CACHE"] == str(
        drive_root / "cache/huggingface/hub"
    )


def test_local_runtime_uses_persistent_hf_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime, "in_colab", lambda: False)
    config = RuntimeConfig(use_google_drive=False, project_dir=tmp_path)

    report = runtime.prepare_runtime(config)

    assert report["hf_home"] == tmp_path / "cache/huggingface"


def test_colab_rejects_gradio_imported_with_stale_drive_binary_path(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(runtime, "in_colab", lambda: True)
    monkeypatch.setitem(
        runtime.sys.modules,
        "gradio.tunneling",
        SimpleNamespace(BINARY_PATH=str(tmp_path / "drive/frpc")),
    )
    config = RuntimeConfig(
        use_google_drive=False,
        project_dir=tmp_path / "drive",
        local_cache_root=tmp_path / "content",
    )

    import pytest

    with pytest.raises(RuntimeError, match="Restart the Colab runtime"):
        runtime.prepare_runtime(config)
