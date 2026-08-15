from types import SimpleNamespace

from envira_gradio import launcher
from envira_gradio.launcher import close_application, launch_application


class Demo:
    def __init__(self, share_url=None, *, running=False):
        self.is_running = running
        self.share_url = share_url
        self.closed = 0
        self.launch_calls = []

    def close(self):
        self.closed += 1
        self.is_running = False

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        self.is_running = True
        return SimpleNamespace(), "http://127.0.0.1:7867", self.share_url


def diagnostics(colab=False):
    return launcher.ShareDiagnostics("test", colab, "/frpc", False, False, True, False)


def test_close_stops_server_without_owning_runtime():
    demo = Demo(running=True)
    close_application(demo)
    assert demo.closed == 1


def test_colab_delegates_sharing_and_inline_presentation_to_gradio(monkeypatch):
    monkeypatch.setattr(
        launcher, "share_diagnostics", lambda **_: diagnostics(colab=True)
    )
    demo = Demo("https://public.gradio.live", running=True)

    info = launch_application(demo, colab=True, share=True, height=720)

    assert demo.closed == 1
    assert len(demo.launch_calls) == 1
    assert demo.launch_calls[0] == {
        "share": True,
        "inline": True,
        "debug": False,
        "prevent_thread_lock": False,
        "show_error": False,
        "height": 720,
    }
    assert info.presentation == "gradio_share"
    assert info.share_url == "https://public.gradio.live"
    assert info.share_attempts == 1
    assert info.share_failure is None


def test_colab_uses_gradio_native_inline_when_share_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        launcher, "share_diagnostics", lambda **_: diagnostics(colab=True)
    )
    info = launch_application(Demo(), colab=True, share=True)

    assert info.presentation == "gradio_colab_inline"
    assert info.share_attempts == 1
    assert info.share_failure == (
        "Gradio returned no public URL; native Colab inline access remains active"
    )


def test_local_launch_disables_inline_embedding(monkeypatch):
    monkeypatch.setattr(launcher, "share_diagnostics", lambda **_: diagnostics())
    demo = Demo()
    info = launch_application(demo, share=False, colab=False)
    assert demo.launch_calls[0]["inline"] is False
    assert demo.launch_calls[0]["share"] is False
    assert info.presentation == "local_url"
    assert info.share_attempts == 0
    assert info.share_failure is None
