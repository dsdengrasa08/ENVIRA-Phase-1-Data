"""Notebook-safe Gradio launch and shutdown helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import time
from urllib.parse import urlparse


@dataclass(frozen=True)
class ShareDiagnostics:
    """Non-secret facts useful when Gradio's native tunnel cannot start."""

    gradio_version: str
    in_colab: bool
    frpc_path: str
    frpc_exists: bool
    frpc_executable: bool
    certificate_directory_writable: bool
    outbound_proxy_configured: bool


@dataclass(frozen=True)
class LaunchInfo:
    """URLs and presentation mode for a running Gradio server."""

    local_url: str
    share_url: str | None
    presentation: str
    share_attempts: int
    share_failure: str | None = None
    diagnostics: ShareDiagnostics | None = None


def in_colab() -> bool:
    return importlib.util.find_spec("google.colab") is not None


def _port_from_url(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port is None:
        raise ValueError(f"Gradio local URL has no port: {url}")
    return parsed.port


def share_diagnostics(*, colab: bool | None = None) -> ShareDiagnostics:
    """Inspect local tunnel prerequisites without gating Gradio's native attempt."""
    import gradio
    from gradio.tunneling import BINARY_PATH, CERTIFICATE_PATH

    binary = Path(BINARY_PATH)
    certificate_parent = Path(CERTIFICATE_PATH).resolve().parent
    try:
        certificate_parent.mkdir(parents=True, exist_ok=True)
        certificate_writable = os.access(certificate_parent, os.W_OK)
    except OSError:
        certificate_writable = False
    proxy_names = (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    )
    return ShareDiagnostics(
        gradio_version=gradio.__version__,
        in_colab=in_colab() if colab is None else colab,
        frpc_path=str(binary),
        frpc_exists=binary.is_file(),
        frpc_executable=binary.is_file() and os.access(binary, os.X_OK),
        certificate_directory_writable=certificate_writable,
        outbound_proxy_configured=any(os.getenv(name) for name in proxy_names),
    )


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
    max_share_attempts: int = 2,
    retry_delay_seconds: float = 2.0,
) -> LaunchInfo:
    """Use native Gradio sharing first and Colab's proxy only as a fallback.

    Gradio owns broker discovery, ``frpc`` acquisition, certificate handling, and
    public URL creation. This wrapper deliberately performs no API preflight or
    public-URL health gate. A failed native attempt is retried after closing its
    local server; the last healthy local server is then presented through Colab.
    """
    colab = in_colab() if colab is None else colab
    attempts = max(1, int(max_share_attempts)) if share else 0
    diagnostics = share_diagnostics(colab=colab)
    local_url = ""
    share_url = None

    for attempt in range(1, attempts + 1 if share else 2):
        close_application(demo)
        _, local_url, share_url = demo.launch(
            share=share,
            inline=False,
            debug=False,
            prevent_thread_lock=True,
            show_error=False,
        )
        if share_url or not share or attempt == attempts:
            break
        time.sleep(max(0.0, retry_delay_seconds))

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

    failure = None
    if share and not share_url:
        failure = f"Gradio returned no public URL after {attempts} native attempt(s)"
    return LaunchInfo(
        local_url=local_url,
        share_url=share_url,
        presentation=presentation,
        share_attempts=attempts,
        share_failure=failure,
        diagnostics=diagnostics,
    )


__all__ = [
    "LaunchInfo",
    "ShareDiagnostics",
    "close_application",
    "in_colab",
    "launch_application",
    "share_diagnostics",
]
