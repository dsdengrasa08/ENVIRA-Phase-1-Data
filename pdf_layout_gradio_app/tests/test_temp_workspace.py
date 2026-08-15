from envira_layout_web.services.temp_workspace import temporary_workspace


def test_temporary_workspace_cleans_only_request_directory(tmp_path):
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    retained = persistent / "overlay.png"
    retained.write_bytes(b"png")
    temp_root = tmp_path / "temporary"
    with temporary_workspace(temp_root) as workspace:
        staged = workspace / "upload.pdf"
        staged.write_bytes(b"%PDF-")
        assert staged.exists()
    assert not workspace.exists()
    assert retained.exists()
