"""Headless Firefox for index pages whose links are drawn by script.

The recheck fetches plain HTML. A page built by JavaScript (SSC's notice
dashboard, for one) comes back as an empty shell with no links, so the
recheck found nothing there. The crawl already renders such pages; this is
the same renderer for the recheck, started only when a page needs it.
"""

from __future__ import annotations

import logging
import os
import shutil
import time

log = logging.getLogger(__name__)


def _geckodriver() -> str:
    """GECKODRIVER, else GECKOWEBDRIVER (a directory on the runner image), else PATH."""
    for var in ("GECKODRIVER", "GECKOWEBDRIVER"):
        v = os.environ.get(var)
        if v:
            return os.path.join(v, "geckodriver") if os.path.isdir(v) else v
    return shutil.which("geckodriver") or "geckodriver"


class BrowserRenderer:
    """One Firefox, started on first use and reused for the run."""

    def __init__(self, user_agent: str, wait: float = 6.0) -> None:
        self.user_agent = user_agent
        self.wait = wait
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.firefox.service import Service

            opts = Options()
            opts.add_argument("-headless")
            opts.set_preference("general.useragent.override", self.user_agent)
            opts.set_preference("pdfjs.disabled", True)
            # Incomplete chains are common on gov.in; the fetch is read-only.
            opts.accept_insecure_certs = True
            self._driver = webdriver.Firefox(
                options=opts, service=Service(_geckodriver())
            )
            self._driver.set_page_load_timeout(60)
        return self._driver

    def render(self, url: str) -> tuple[str, str]:
        """Return (final_url, html) once the DOM stops growing."""
        d = self._get_driver()
        d.get(url)
        deadline = time.monotonic() + self.wait
        last = -1
        while time.monotonic() < deadline:
            size = len(d.page_source)
            if size == last and size > 2000:
                break
            last = size
            time.sleep(1.0)
        return d.current_url, d.page_source

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception as exc:  # noqa: BLE001 - shutdown must not fail the run
                log.warning("firefox did not quit cleanly: %s", exc)
            finally:
                self._driver = None
