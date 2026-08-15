"""Optional command-line launcher."""

from . import AppSettings, create_app


def main() -> None:
    settings = AppSettings.load()
    demo = create_app(settings)
    demo.queue(default_concurrency_limit=settings.concurrency_limit).launch()
