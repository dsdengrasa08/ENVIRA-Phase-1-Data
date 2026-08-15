from types import ModuleType, SimpleNamespace
import sys

from envira_gradio import launcher
from envira_gradio.launcher import _port_from_url, close_application, launch_application


class Demo:
    def __init__(self, share_urls=(), *, running=False):
        self.is_running = running
        self.share_urls = iter(share_urls)
        self.closed = 0
        self.launch_calls = []

    def close(self):
        self.closed += 1
        self.is_running = False

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        self.is_running = True
        share_url = next(self.share_urls, None) if kwargs["share"] else None
        return SimpleNamespace(), "http://127.0.0.1:7867", share_url


def diagnostics():
    return launcher.ShareDiagnostics("test", False, "/frpc", False, False, True, False)


def install_colab(monkeypatch, calls):
    google = ModuleType("google")
    colab = ModuleType("google.colab")
    colab.output = SimpleNamespace(
        serve_kernel_port_as_iframe=lambda port, height: calls.append((port, height))
    )
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)


def test_port_is_derived_from_gradio_local_url():
    assert _port_from_url("http://127.0.0.1:7867") == 7867


def test_close_stops_server_without_owning_runtime():
    demo = Demo(running=True)
    close_application(demo)
    assert demo.closed == 1


def test_native_share_is_not_gated_and_retries_once(monkeypatch):
    monkeypatch.setattr(launcher, "share_diagnostics", lambda **_: diagnostics())
    demo = Demo([None, "https://public.gradio.live"], running=True)

    info = launch_application(
        demo, colab=False, max_share_attempts=2, retry_delay_seconds=0
    )

    assert len(demo.launch_calls) == 2
    assert all(call["share"] is True for call in demo.launch_calls)
    assert all(call["inline"] is False for call in demo.launch_calls)
    assert all(call["debug"] is False for call in demo.launch_calls)
    assert demo.closed == 2
    assert info.share_url == "https://public.gradio.live"
    assert info.presentation == "share_url"
    assert info.share_failure is None


def test_colab_proxy_is_used_only_after_native_retries_fail(monkeypatch):
    calls = []
    install_colab(monkeypatch, calls)
    monkeypatch.setattr(launcher, "share_diagnostics", lambda **_: diagnostics())
    demo = Demo([None, None])

    info = launch_application(
        demo,
        colab=True,
        height=720,
        max_share_attempts=2,
        retry_delay_seconds=0,
    )

    assert len(demo.launch_calls) == 2
    assert info.presentation == "colab_kernel_proxy"
    assert info.share_attempts == 2
    assert info.share_failure == "Gradio returned no public URL after 2 native attempt(s)"
    assert calls == [(7867, 720)]


def test_share_false_starts_once_without_reporting_failure(monkeypatch):
    monkeypatch.setattr(launcher, "share_diagnostics", lambda **_: diagnostics())
    demo = Demo()
    info = launch_application(demo, share=False, colab=False)
    assert len(demo.launch_calls) == 1
    assert demo.launch_calls[0]["share"] is False
    assert info.share_attempts == 0
    assert info.share_failure is None
