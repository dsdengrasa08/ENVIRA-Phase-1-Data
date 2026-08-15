from types import SimpleNamespace
from types import ModuleType
import sys

from envira_gradio.launcher import (
    _port_from_url,
    close_application,
    launch_application,
)


class Demo:
    def __init__(self, *, running=False, share_url=None):
        self.is_running = running
        self.share_url = share_url
        self.closed = 0
        self.launch_kwargs = None

    def close(self):
        self.closed += 1
        self.is_running = False

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        self.is_running = True
        return SimpleNamespace(), "http://127.0.0.1:7867", self.share_url


def test_port_is_derived_from_gradio_local_url():
    assert _port_from_url("http://127.0.0.1:7867") == 7867


def test_close_stops_server_without_owning_runtime():
    demo = Demo(running=True)
    close_application(demo)
    assert demo.closed == 1


def test_relaunch_closes_existing_server_and_does_not_block():
    demo = Demo(running=True)
    info = launch_application(demo, colab=False)
    assert demo.closed == 1
    assert demo.launch_kwargs["inline"] is False
    assert demo.launch_kwargs["debug"] is False
    assert demo.launch_kwargs["prevent_thread_lock"] is True
    assert info.local_url == "http://127.0.0.1:7867"
    assert info.presentation == "local_url"


def test_colab_falls_back_to_kernel_proxy_when_share_tunnel_fails(monkeypatch):
    calls = []
    google = ModuleType("google")
    colab = ModuleType("google.colab")
    colab.output = SimpleNamespace(
        serve_kernel_port_as_iframe=lambda port, height: calls.append((port, height))
    )
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)

    info = launch_application(Demo(share_url=None), colab=True, height=720)

    assert info.presentation == "colab_kernel_proxy"
    assert calls == [(7867, 720)]
