"""The recheck renders a script-drawn index page in Firefox.

No browser is started. The renderer is replaced by a stub, and the fetcher
returns a page with no links, the way SSC's dashboard does to a plain fetch.
"""

from __future__ import annotations

from examhub_pipeline import fetch as fetch_module
from examhub_pipeline.fetch import Pipeline
from examhub_pipeline.http import CachedResponse
from examhub_pipeline.sources import Source

SHELL = b"""<!doctype html><html><head><script src="main.js"></script></head>
<body><app-root></app-root></body></html>"""

RENDERED = (
    b"<html><body><h1>Notices</h1>"
    b'<a href="/uploads/cgl-2026-notice.pdf">Notice for Combined Graduate Level Examination 2026</a>'
    + b"<p>" + b"word " * 200 + b"</p>"
    + b"".join(b'<a href="/other/%d">Other page %d</a>' % (i, i) for i in range(12))
    + b"</body></html>"
)

SOURCE = Source(
    key="ssc-test",
    name="Staff Selection Commission",
    notices_url="https://ssc.example/dashboard",
    document_hosts=("ssc.example",),
)


class FakeFetcher:
    stats = {"retries": 0}

    def __init__(self, body: bytes) -> None:
        self.body = body

    def fetch(self, url, **kwargs):
        return CachedResponse(
            url=url, final_url=url, status=200, content_type="text/html",
            content=self.body, etag=None, last_modified=None, retrieved=0.0,
            checked=0.0, from_cache=False, not_modified=False,
        )

    def close(self):
        pass


def test_script_drawn_index_is_rendered(settings, monkeypatch):
    rendered_urls = []

    def fake_render(self, url):
        rendered_urls.append(url)
        return url, RENDERED.decode()

    monkeypatch.setattr(fetch_module.BrowserRenderer, "render", fake_render)
    pipe = Pipeline(settings, fetcher=FakeFetcher(SHELL))
    try:
        refs, outcome = pipe.discover(SOURCE)
    finally:
        pipe.close()

    assert rendered_urls == ["https://ssc.example/dashboard"]
    assert [r.url for r in refs] == ["https://ssc.example/uploads/cgl-2026-notice.pdf"]
    assert outcome.ok


def test_plain_page_with_links_is_not_rendered(settings, monkeypatch):
    def fail_render(self, url):
        raise AssertionError("a page with its links in the HTML must not be rendered")

    monkeypatch.setattr(fetch_module.BrowserRenderer, "render", fail_render)
    pipe = Pipeline(settings, fetcher=FakeFetcher(RENDERED))
    try:
        pipe.discover(SOURCE)
    finally:
        pipe.close()


def test_missing_firefox_keeps_the_plain_page(settings, monkeypatch):
    def broken_driver(self):
        raise RuntimeError("geckodriver not found")

    monkeypatch.setattr(fetch_module.BrowserRenderer, "_get_driver", broken_driver)
    pipe = Pipeline(settings, fetcher=FakeFetcher(SHELL))
    try:
        refs, outcome = pipe.discover(SOURCE)
        assert refs == []
        assert outcome.ok
        # One failed start switches rendering off for the rest of the run.
        assert pipe._render_failed
    finally:
        pipe.close()
