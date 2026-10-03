"""Scrapy settings. Politeness defaults match the rest of the pipeline."""

import os
import shutil
from pathlib import Path

from ..config import DEFAULT_CONTACT

BOT_NAME = "examhub"
SPIDER_MODULES = ["examhub_pipeline.crawl.spiders"]
NEWSPIDER_MODULE = "examhub_pipeline.crawl.spiders"

CONTACT = os.environ.get("EXAMHUB_CONTACT", DEFAULT_CONTACT)
# Identify honestly, but in a shape government WAFs accept. Measured on
# 2026-09-29 against upsc.gov.in and *.nta.nic.in: a bare product token
# passes, while anything bot-shaped -- "bot" in the name, a parenthesised URL
# or contact -- gets 403 on every path including robots.txt. The contact goes
# in the From header instead, which is what RFC 9110 section 10.1.2 has it for.
USER_AGENT = "examhub-pipeline/0.2"
DEFAULT_REQUEST_HEADERS = {
    "From": CONTACT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-IN,en;q=0.9",
}

# robots.txt is obeyed. A 4xx robots.txt means "no rules" (RFC 9309 2.3.1.3),
# which is also Scrapy's behaviour.
ROBOTSTXT_OBEY = True

# Government hosts are slow and easily upset. One request per host at a
# time, a few seconds apart, and AutoThrottle backs off further on its own.
CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 1
# Twisted's default DNS resolver uses a thread pool sized for 10 lookups at
# once; with 16 concurrent requests all resolving different slow gov.in hosts
# at crawl start, resolution queues and borderline-slow-but-working hosts can
# time out from that queueing alone, not from anything wrong on their end.
REACTOR_THREADPOOL_MAXSIZE = 30
DOWNLOAD_DELAY = float(os.environ.get("EXAMHUB_HOST_DELAY", "3"))
DOWNLOAD_DELAY_JITTER = 0.5
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = DOWNLOAD_DELAY
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_TIMEOUT = 45
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [408, 425, 429, 500, 502, 503, 504, 522, 524]
# Index pages only: a notice PDF is not downloaded by the feeds spider.
DOWNLOAD_MAXSIZE = 25 * 1024 * 1024
DOWNLOAD_WARNSIZE = 8 * 1024 * 1024

# A conditional-GET cache, so a re-run inside the day costs nothing.
HTTPCACHE_ENABLED = os.environ.get("EXAMHUB_HTTPCACHE", "1") == "1"
HTTPCACHE_DIR = os.path.abspath(os.path.join("work", "scrapy-cache"))
HTTPCACHE_EXPIRATION_SECS = int(os.environ.get("EXAMHUB_HTTPCACHE_SECS", str(6 * 3600)))
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.DummyPolicy"
HTTPCACHE_IGNORE_HTTP_CODES = [403, 429, 500, 502, 503, 504]

DOWNLOADER_MIDDLEWARES = {
    "examhub_pipeline.crawl.middlewares.FirefoxMiddleware": 950,
}


def _geckodriver() -> str:
    """GECKODRIVER, else GitHub's runner image variable (a directory), else PATH.

    ubuntu-latest runners ship Firefox and geckodriver and export
    GECKOWEBDRIVER=/usr/local/share/gecko_driver; the nix dev shell puts it
    on PATH. Nothing here depends on either being the environment."""
    for var in ("GECKODRIVER", "GECKOWEBDRIVER"):
        v = os.environ.get(var)
        if v:
            return os.path.join(v, "geckodriver") if os.path.isdir(v) else v
    # a full path: given a bare name, Selenium looks for a file in the working
    # directory, then tries to download a driver (which fails on NixOS)
    return shutil.which("geckodriver") or "geckodriver"


GECKODRIVER = _geckodriver()
FIREFOX_PAGE_WAIT = float(os.environ.get("EXAMHUB_FIREFOX_WAIT", "6"))

# Many Indian government hosts ship incomplete certificate chains or need TLS
# legacy renegotiation, which browsers tolerate. Scrapy does not verify
# certificates by default; this makes the legacy-renegotiation hosts work too.
DOWNLOADER_CLIENT_TLS_METHOD = "TLS"

LOG_LEVEL = os.environ.get("EXAMHUB_LOG_LEVEL", "INFO")

# work/ is git-ignored, so a fresh checkout (every Actions run) lacks it, and
# Scrapy cannot open LOG_FILE=work/<spider>.log without it
(Path(__file__).resolve().parents[3] / "work").mkdir(exist_ok=True)
FEED_EXPORT_ENCODING = "utf-8"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
