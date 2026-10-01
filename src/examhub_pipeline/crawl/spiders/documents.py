"""Fetch the PDFs of new notification notices, for `documents build`.

    scrapy crawl documents                    # newest, up to 40
    scrapy crawl documents -a limit=200 -a recent_days=0   # backfill
    scrapy crawl documents -a notice=<id>,<id>
    scrapy crawl documents -a limit=6 -a ocr=0   # the fast loop: no OCR on hand

Writes ``work/documents/<id>.pdf`` and ``work/documents/fetched.jsonl``.
Nothing here parses a PDF; see :mod:`examhub_pipeline.crawl.ingest`.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit

import scrapy
from scrapy import signals
from scrapy.spidermiddlewares.httperror import HttpError

from .. import harvest, ingest

log = logging.getLogger(__name__)


class DocumentsSpider(scrapy.Spider):
    name = "documents"
    custom_settings = {
        # PDFs are large and fetched once; caching them only fills the disk.
        "HTTPCACHE_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 60,
        "RETRY_TIMES": 1,
        # A slow host must not stretch one PDF into minutes of back-off.
        "AUTOTHROTTLE_MAX_DELAY": 10,
        # A hard stop, whatever the hosts do; unfetched notices wait for the
        # next run. Callers can lower it (-s CLOSESPIDER_TIMEOUT=240).
        "CLOSESPIDER_TIMEOUT": 1500,
        "DOWNLOADER_MIDDLEWARES": {
            "examhub_pipeline.crawl.middlewares.FirefoxMiddleware": 950,
            "examhub_pipeline.crawl.middlewares.HostBreaker": 50,
        },
    }

    def __init__(self, limit: str = "40", recent_days: str = str(ingest.RECENT_DAYS),
                 notice: str = "", ocr: str = "1", **kw):
        super().__init__(**kw)
        self.limit = int(limit)
        self.recent_days = int(recent_days) or None
        self.only = set(filter(None, notice.split(",")))
        # Whether the build step after this fetch can OCR. Without it, scans
        # already read without OCR are not fetched again.
        self.ocr = ocr not in ("0", "false", "")
        self.rows: list[dict] = []
        self.dead_hosts: set[str] = set()

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        return spider

    async def start(self):
        notices = harvest.read_jsonl(harvest.HARVEST_DIR / "notices.jsonl")
        if self.only:
            chosen = [n for n in notices if n["id"] in self.only]
        else:
            chosen = ingest.select(notices, ingest.load_index(), limit=self.limit,
                                   recent_days=self.recent_days, ocr=self.ocr,
                                   gaps=ingest.load_gaps())
        ingest.WORK_DIR.mkdir(parents=True, exist_ok=True)
        (ingest.WORK_DIR / "fetched.jsonl").unlink(missing_ok=True)
        log.info("documents: %d notice(s) to fetch", len(chosen))
        for n in chosen:
            yield scrapy.Request(n["url"], callback=self.parse, errback=self.failed,
                                 cb_kwargs={"notice": n}, dont_filter=True)

    def _row(self, notice: dict, status: str, **extra) -> None:
        self.rows.append({"id": notice["id"], "notice": notice, "status": status,
                          "tried": harvest.now(), **extra})

    def parse(self, response, notice: dict):
        body = response.body
        if not body.lstrip()[:5].startswith(b"%PDF"):
            # An HTML landing page or a Word file: final, never retried.
            kind = response.headers.get(b"Content-Type", b"").decode("latin-1")[:60]
            self._row(notice, "not_pdf", error=kind or "no content type")
            return
        path = ingest.WORK_DIR / f"{notice['id']}.pdf"
        path.write_bytes(body)
        self._row(notice, "fetched", pdf=str(path), bytes=len(body))

    def failed(self, failure):
        notice = failure.request.cb_kwargs["notice"]
        if failure.check(HttpError):
            error = f"HTTP {failure.value.response.status}"
        else:
            error = f"{failure.type.__name__}: {failure.getErrorMessage()}"[:200]
            if re.search(r"Timeout|DNS|ConnectionRefused|ConnectError|TCPTimedOut", failure.type.__name__):
                self.dead_hosts.add(urlsplit(failure.request.url).hostname or "")
        if "maxsize" in error.lower() or "cancelled" in error.lower():
            self._row(notice, "too_large", error=error)
        else:
            self._row(notice, "failed", error=error)

    def _closed(self, spider, reason):
        # A robots.txt refusal arrives at the errback as IgnoreRequest and is
        # recorded as a failure, so it stops being tried after MAX_ATTEMPTS.
        ingest.WORK_DIR.mkdir(parents=True, exist_ok=True)
        path = ingest.WORK_DIR / "fetched.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        log.info("documents: %s", counts)
