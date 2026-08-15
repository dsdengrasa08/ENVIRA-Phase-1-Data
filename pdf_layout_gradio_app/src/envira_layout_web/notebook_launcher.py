"""Notebook-specific Gradio launch behavior with a Colab proxy fallback."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Callable


@dataclass(frozen=True)
class NotebookLaunchResult:
    local_url: str | None
    share_url: str | None
    proxy_url: str | None


def launch_notebook_app(
    demo: Any,
    *,
    concurrency_limit: int = 1,
    in_colab: bool = False,
    proxy_url_factory: Callable[[int], str] | None = None,
    proxy_display: Callable[[str], None] | None = None,
    server_port: int = 7860,
) -> NotebookLaunchResult:
    """Launch without blocking and embed a Colab proxy if sharing is unavailable."""
    demo.queue(default_concurrency_limit=max(1, concurrency_limit))
    launched = demo.launch(
        share=in_colab,
        inline=in_colab,
        debug=False,
        prevent_thread_lock=True,
        server_name="0.0.0.0",
        server_port=server_port,
    )
    local_url = getattr(demo, "local_url", None) or _tuple_value(launched, 1)
    share_url = getattr(demo, "share_url", None) or _tuple_value(launched, 2)
    proxy_url = None
    if in_colab and not share_url:
        factory = proxy_url_factory or _colab_proxy_url
        proxy_url = factory(server_port)
        display = proxy_display or _display_proxy
        display(proxy_url)
    return NotebookLaunchResult(local_url, share_url, proxy_url)


def _tuple_value(value: Any, index: int) -> str | None:
    if isinstance(value, tuple) and len(value) > index:
        item = value[index]
        return str(item) if item else None
    return None


def _colab_proxy_url(port: int) -> str:
    from google.colab import output

    return str(output.eval_js(f"google.colab.kernel.proxyPort({int(port)})"))


def _display_proxy(url: str) -> None:
    from IPython.display import HTML, display

    safe_url = escape(url, quote=True)
    display(
        HTML(
            '<p><strong>Gradio share service unavailable.</strong> '
            f'<a href="{safe_url}" target="_blank">Open the Colab-proxied app</a>.</p>'
            f'<iframe src="{safe_url}" width="100%" height="800" '
            'style="border:1px solid #ddd;border-radius:8px"></iframe>'
        )
    )
