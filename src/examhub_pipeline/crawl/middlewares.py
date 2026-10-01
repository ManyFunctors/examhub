"""Headless Firefox for pages that render their content client-side.

A request opts in with ``meta={"render": "browser"}``. Everything else goes
through Scrapy's normal downloader. One Firefox instance is shared and used
from a worker thread, one page at a time, so a browser-rendered feed is
exactly as polite as a plain one.

robots.txt is still consulted: RobotsTxtMiddleware runs before this one.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from scrapy import signals
from scrapy.http import HtmlResponse

log = logging.getLogger(__name__)


class FirefoxMiddleware:
    def __init__(self, geckodriver: str, wait: float, user_agent: str) -> None:
        self.geckodriver = geckodriver
        self.wait = wait
        self.user_agent = user_agent
        self._driver = None
        self._lock = threading.Lock()

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        mw = cls(s.get("GECKODRIVER"), s.getfloat("FIREFOX_PAGE_WAIT"), s.get("USER_AGENT"))
        crawler.signals.connect(mw.close, signal=signals.spider_closed)
        return mw

    def _get_driver(self):
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.firefox.service import Service

            opts = Options()
            opts.add_argument("-headless")
            # Identify honestly, as the rest of the crawler does.
            opts.set_preference("general.useragent.override", self.user_agent)
            opts.set_preference("pdfjs.disabled", True)
            opts.accept_insecure_certs = True  # incomplete chains are endemic on gov.in
            self._driver = webdriver.Firefox(options=opts, service=Service(self.geckodriver))
            self._driver.set_page_load_timeout(60)
        return self._driver

    def _render(self, url: str, wait: float) -> tuple[str, str]:
        with self._lock:
            d = self._get_driver()
            d.get(url)
            # Wait for the SPA to settle: stop when the DOM size is stable.
            deadline = time.monotonic() + wait
            last = -1
            while time.monotonic() < deadline:
                size = len(d.page_source)
                if size == last and size > 2000:
                    break
                last = size
                time.sleep(1.0)
            return d.current_url, d.page_source

    async def process_request(self, request, spider=None):
        if request.meta.get("render") != "browser":
            return None
        wait = float(request.meta.get("render_wait", self.wait))
        try:
            final_url, html = await asyncio.to_thread(self._render, request.url, wait)
        except Exception as exc:  # noqa: BLE001 - reported as a failed fetch
            log.warning("firefox failed on %s: %s", request.url, exc)
            raise
        return HtmlResponse(
            url=final_url, body=html.encode("utf-8"), encoding="utf-8",
            request=request, status=200, flags=["firefox"],
        )

    def close(self, spider=None):
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None


class HostBreaker:
    """Stop sending a run's requests to a host that has stopped answering.

    Per-domain concurrency is 1, so a dead host's queued requests each wait
    out a timeout, the retries, and AutoThrottle's growing delay: ten NTA
    PDFs on a bad night cost a quarter of an hour. After the first
    connection-level failure (timeout, DNS, refused), the rest of that
    host's requests fail at once with IgnoreRequest, which reaches the
    spider's errback, and are tried again on a later run.

    The spider records dead hosts in ``spider.dead_hosts`` from its errback.
    """

    def process_request(self, request, spider=None):
        from urllib.parse import urlsplit

        from scrapy.exceptions import IgnoreRequest

        dead = getattr(spider, "dead_hosts", None)
        if dead and (urlsplit(request.url).hostname or "") in dead:
            raise IgnoreRequest(f"host unreachable earlier this run: {request.url}")
        return None
