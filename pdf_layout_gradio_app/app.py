"""Optional Python launcher; the notebook remains the primary entry point."""

from envira_layout_web import AppSettings, create_app


def main() -> None:
    settings = AppSettings.load()
    demo = create_app(settings)
    demo.queue(default_concurrency_limit=settings.concurrency_limit).launch()


if __name__ == "__main__":
    main()
