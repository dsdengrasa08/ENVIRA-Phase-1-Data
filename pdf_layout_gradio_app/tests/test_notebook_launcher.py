from envira_layout_web.notebook_launcher import launch_notebook_app


class FakeDemo:
    def __init__(self, *, share_url=None):
        self.share_url = share_url
        self.local_url = "http://127.0.0.1:7860"
        self.queue_limit = None
        self.launch_options = None

    def queue(self, *, default_concurrency_limit):
        self.queue_limit = default_concurrency_limit
        return self

    def launch(self, **options):
        self.launch_options = options
        return self, self.local_url, self.share_url


def test_colab_uses_proxy_when_share_creation_fails():
    displayed = []
    demo = FakeDemo()

    result = launch_notebook_app(
        demo,
        concurrency_limit=0,
        in_colab=True,
        proxy_url_factory=lambda port: f"https://colab.proxy/{port}",
        proxy_display=displayed.append,
    )

    assert result.proxy_url == "https://colab.proxy/7860"
    assert displayed == [result.proxy_url]
    assert demo.queue_limit == 1
    assert demo.launch_options == {
        "share": True,
        "inline": True,
        "debug": False,
        "prevent_thread_lock": True,
        "server_name": "0.0.0.0",
        "server_port": 7860,
    }


def test_colab_share_url_does_not_create_proxy():
    demo = FakeDemo(share_url="https://example.gradio.live")

    result = launch_notebook_app(
        demo,
        in_colab=True,
        proxy_url_factory=lambda _port: (_ for _ in ()).throw(AssertionError()),
    )

    assert result.share_url == "https://example.gradio.live"
    assert result.proxy_url is None
