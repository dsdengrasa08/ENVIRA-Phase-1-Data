"""Notebook-safe Gradio launch and shutdown helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from urllib.parse import urlparse


@dataclass(frozen=True)
class LaunchInfo:
    """URLs and presentation mode for a running Gradio server."""

    local_url: str
    share_url: str | None
    presentation: str


def in_colab() -> bool:
    return importlib.util.find_spec("google.colab") is not None


def _port_from_url(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port is None:
        raise ValueError(f"Gradio local URL has no port: {url}")
    return parsed.port


def close_application(demo) -> None:
    """Stop this app's Gradio server without terminating the notebook runtime."""
    if getattr(demo, "is_running", False):
        demo.close()


def launch_application(
    demo,
    *,
    share: bool = True,
    height: int = 900,
    colab: bool | None = None,
) -> LaunchInfo:
    """Launch once and present a usable URL, even if Gradio sharing is unavailable.

    Colab cannot load a kernel-local ``127.0.0.1`` URL directly in the browser. We
    therefore disable Gradio's automatic inline iframe, prefer its public share
    tunnel, and fall back to Colab's authenticated kernel-port proxy when the
    tunnel service is unavailable.
    """
    close_application(demo)
    colab = in_colab() if colab is None else colab
    _, local_url, share_url = demo.launch(
        share=share,
        inline=False,
        debug=False,
        prevent_thread_lock=True,
        show_error=False,
    )
    if colab:
        if share_url:
            from IPython.display import IFrame, display

            display(IFrame(share_url, width="100%", height=height))
            presentation = "gradio_share"
        else:
            from google.colab import output

            output.serve_kernel_port_as_iframe(
                _port_from_url(local_url), height=height
            )
            presentation = "colab_kernel_proxy"
    else:
        presentation = "share_url" if share_url else "local_url"
    return LaunchInfo(local_url, share_url, presentation)


__all__ = ["LaunchInfo", "close_application", "in_colab", "launch_application"]
