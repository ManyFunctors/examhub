"""Fetch the official documents behind each existing ExamHub record.

    scrapy crawl records -a site=data/old-records            # every record
    scrapy crawl records -a site=data/old-records -a only=<slug>,<slug>

For each record it fetches ``provenance.source_url`` and ``official_url``.
A PDF is saved as it is. An HTML page is saved too, and the PDF links on it
whose link text or URL share words with the record's title are followed, a
few per page, because a portal page usually lists the notification rather
than being it.

Writes ``work/records/<slug>/<sha1 of url>.{pdf,html}`` and one
``work/records/<slug>/manifest.jsonl`` per record. Nothing here parses a PDF.

Built to run unattended (GitHub Actions):

* a file already on disk is reused, not downloaded again, so a re-run
  resumes where the last one stopped (``-a refetch=1`` forces fresh copies);
* manifests are written as rows arrive, so a killed run keeps its work;
* every fetch is logged, with a progress line each minute;
* a host that stops answering is skipped for the rest of the run;
* a watchdog closes the crawl if nothing arrives for ``STALL_SECONDS`` and
  forces the exit if the close itself hangs;
* the run ends by writing ``work/records/_report.json`` (counts, every
  failure with its reason, dead hosts) and logging the same summary.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import tomllib
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import scrapy
from scrapy import signals
from scrapy.http import HtmlResponse
from scrapy.spidermiddlewares.httperror import HttpError

from ... import records

log = logging.getLogger(__name__)

OUT = Path("work/records")
LINKS_PER_PAGE = 4
STALL_SECONDS = 300      # no response for this long: close the crawl
CLOSE_GRACE_SECONDS = 90  # a close that has not finished by then is forced
# Failures worth marking a host dead for: the host itself is not answering.
DEAD_HOST_ERRORS = ("TimeoutError", "TCPTimedOutError", "DNSLookupError", "ConnectionRefusedError",
                    "ConnectError", "ResponseNeverReceived")
# Words too common in notice titles to say which exam a link is about.
STOP = set("""a an and the of for in on to by with from at or exam examination
recruitment notice notification advertisement post posts online application
apply form last date official website 2023 2024 2025 2026 2027 2028 pdf
click here download new""".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def load_records(site: str) -> list[dict]:
    out = []
    for f in sorted(Path(site).glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("+++"):
            continue
        d = tomllib.loads(text.split("+++")[1])
        d["slug"] = f.stem
        out.append(d)
    return out


class RecordsSpider(scrapy.Spider):
    name = "records"
    custom_settings = {
        "HTTPCACHE_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 60,
        "RETRY_TIMES": 2,
        "AUTOTHROTTLE_MAX_DELAY": 10,
        "CLOSESPIDER_TIMEOUT": 3000,
        "LOGSTATS_INTERVAL": 60,
        "DOWNLOAD_MAXSIZE": 60 * 1024 * 1024,
        "DOWNLOADER_MIDDLEWARES": {
            "examhub_pipeline.crawl.middlewares.FirefoxMiddleware": 950,
            "examhub_pipeline.crawl.middlewares.HostBreaker": 50,
        },
    }

    def __init__(self, site: str = "data/old-records", only: str = "", refetch: str = "0", **kw):
        super().__init__(**kw)
        self.site = site
        self.only = set(filter(None, only.split(",")))
        self.refetch = refetch not in ("0", "false", "")
        self.rows: dict[str, list[dict]] = {}
        self.dead_hosts: set[str] = set()
        self.last_activity = time.monotonic()
        self.stats_seen = {"fetched": 0, "reused": 0, "failed": 0, "skipped": 0}

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        crawler.signals.connect(spider._opened, signal=signals.spider_opened)
        return spider

    # ── watchdog ────────────────────────────────────────────────────────
    def _opened(self, spider):
        threading.Thread(target=self._watch, name="records-watchdog", daemon=True).start()

    def _watch(self):
        """Log progress each minute; close the crawl if it has gone quiet."""
        while True:
            time.sleep(60)
            idle = time.monotonic() - self.last_activity
            log.info("records: progress %s, %d dead host(s), idle %ds",
                     self.stats_seen, len(self.dead_hosts), idle)
            if idle > STALL_SECONDS:
                log.error("records: nothing arrived for %ds, closing the crawl as stalled", idle)
                self.crawler.engine.close_spider(self, "stalled")
                time.sleep(CLOSE_GRACE_SECONDS)
                log.error("records: close did not finish in %ds, writing the report and exiting",
                          CLOSE_GRACE_SECONDS)
                self._write_report("stalled (forced exit)")
                os._exit(3)

    def _done(self, slug: str) -> set[str]:
        m = OUT / slug / "manifest.jsonl"
        if self.refetch or not m.exists():
            return set()
        return {json.loads(line)["url"] for line in m.open() if '"status": "ok"' in line}

    async def start(self):
        chosen = load_records(self.site)
        if self.only:
            chosen = [r for r in chosen if r["slug"] in self.only]
        log.info("records: %d record(s)", len(chosen))
        for r in chosen:
            slug = r["slug"]
            self.rows[slug] = []
            done = self._done(slug)
            if done:
                # Keep what an earlier run already fetched.
                self.rows[slug] = [json.loads(l) for l in (OUT / slug / "manifest.jsonl").open()]
                continue
            title = " ".join([r.get("title", ""), *r.get("known_as", [])])
            seen = set()
            wanted = [("source", r["provenance"]["source_url"]), ("official", r.get("official_url"))]
            wanted += [(f"notice:{n.get('doc_type')}:{n['score']}:{n['title'][:100]}", n["url"])
                       for n in records.match(r) if n["score"] >= 8]
            log.info("records: [%s] %d url(s) to fetch", slug, len([u for _, u in wanted if u]))
            for role, url in wanted:
                if not url or url in seen:
                    continue
                seen.add(url)
                for req in self._fetch(url, slug=slug, role=role, title=title, depth=0):
                    yield req

    def _cached(self, url: str, slug: str) -> Path | None:
        if self.refetch:
            return None
        for kind in ("pdf", "html"):
            path = OUT / slug / f"{key(url)}.{kind}"
            if path.exists() and path.stat().st_size:
                return path
        return None

    def _fetch(self, url: str, **kw):
        """A request for ``url``, or, when an earlier run saved it, the same
        handling done from the file on disk (and requests for anything it
        links to that is not on disk either)."""
        path = self._cached(url, kw["slug"])
        if path is None:
            yield scrapy.Request(url, callback=self.parse, errback=self.failed, dont_filter=True, cb_kwargs=kw)
            return
        body = path.read_bytes()
        self.stats_seen["reused"] += 1
        log.debug("records: [%s] reused %s (%s)", kw["slug"], path.name, url)
        if path.suffix == ".pdf":
            self._row(kw["slug"], {"url": url, "role": kw["role"], "status": "ok", "kind": "pdf",
                                   "file": path.name, "bytes": len(body), "reused": True})
            return
        resp = HtmlResponse(url=url, body=body, encoding="utf-8")
        yield from self._handle(resp, reused=True, **kw)

    def _save(self, slug: str, url: str, role: str, body: bytes, kind: str, **extra) -> None:
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{key(url)}.{kind}"
        path.write_bytes(body)
        self._row(slug, {"url": url, "role": role, "status": "ok", "kind": kind,
                         "file": path.name, "bytes": len(body), **extra})

    def _row(self, slug: str, row: dict) -> None:
        """Record a row and rewrite the manifest now, so a run that is cut
        off (a CI time limit) keeps everything it fetched."""
        self.rows[slug].append(row)
        d = OUT / slug
        d.mkdir(parents=True, exist_ok=True)
        with (d / "manifest.jsonl").open("w", encoding="utf-8") as fh:
            for r in self.rows[slug]:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def parse(self, response, slug: str, role: str, title: str, depth: int):
        self.last_activity = time.monotonic()
        self.stats_seen["fetched"] += 1
        yield from self._handle(response, slug=slug, role=role, title=title, depth=depth)

    def _handle(self, response, slug: str, role: str, title: str, depth: int, reused: bool = False):
        body = response.body
        ctype = response.headers.get(b"Content-Type", b"").decode("latin-1").lower()
        if not reused:
            if body.lstrip()[:5].startswith(b"%PDF"):
                self._save(slug, response.url, role, body, "pdf")
                log.info("records: [%s] saved pdf %dKB %s", slug, len(body) // 1024, response.url)
                return
            if "html" not in ctype and not body.lstrip()[:200].lower().count(b"<html"):
                self.stats_seen["skipped"] += 1
                log.warning("records: [%s] skipped %s: not a PDF or page (%s)", slug, response.url, ctype[:60])
                self._row(slug, {"url": response.url, "role": role, "status": "skipped", "error": ctype[:60]})
                return
            self._save(slug, response.url, role, body, "html")
            log.info("records: [%s] saved page %dKB %s", slug, len(body) // 1024, response.url)
        else:
            self._row(slug, {"url": response.url, "role": role, "status": "ok", "kind": "html",
                             "file": f"{key(response.url)}.html", "bytes": len(body), "reused": True})
        if depth:
            return
        want = words(title)
        scored = []
        for a in response.css("a"):
            href = a.attrib.get("href", "")
            if not re.search(r"\.pdf($|\?)", href, re.I):
                continue
            url = urljoin(response.url, href)
            text = " ".join(a.css("::text").getall())
            score = len(want & (words(text) | words(urlsplit(url).path)))
            if score:
                scored.append((score, url, text.strip()[:120]))
        seen = set()
        for score, url, text in sorted(scored, key=lambda s: -s[0]):
            if url in seen:
                continue
            seen.add(url)
            if len(seen) > LINKS_PER_PAGE:
                break
            yield from self._fetch(url, slug=slug, role=f"linked:{score}:{text}", title=title, depth=1)

    def failed(self, failure):
        kw = failure.request.cb_kwargs
        if failure.check(HttpError):
            error = f"HTTP {failure.value.response.status}"
        else:
            error = f"{failure.type.__name__}: {failure.getErrorMessage()}"[:200]
        self.last_activity = time.monotonic()
        self.stats_seen["failed"] += 1
        host = urlsplit(failure.request.url).hostname or ""
        if failure.type.__name__ in DEAD_HOST_ERRORS and host not in self.dead_hosts:
            self.dead_hosts.add(host)
            log.warning("records: %s is not answering; skipping its other requests this run", host)
        log.warning("records: [%s] failed %s: %s", kw["slug"], failure.request.url, error)
        self._row(kw["slug"], {"url": failure.request.url, "role": kw["role"],
                               "status": "failed", "error": error})

    def _closed(self, spider, reason):
        self._write_report(reason)

    def _write_report(self, reason: str) -> None:
        """Counts, every failure with its reason, and dead hosts, to a file a
        workflow can upload or diff, and to the log."""
        counts: dict[str, int] = {}
        failures = []
        empty = []
        for slug, rows in sorted(self.rows.items()):
            if not any(r["status"] == "ok" for r in rows):
                empty.append(slug)
            for row in rows:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
                if row["status"] != "ok":
                    failures.append({"slug": slug, "url": row["url"], "status": row["status"],
                                     "error": row.get("error", "")})
        report = {"reason": reason, "records": len(self.rows), "counts": counts,
                  "this_run": self.stats_seen, "dead_hosts": sorted(self.dead_hosts),
                  "records_with_nothing": empty, "failures": failures}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("records: finished (%s): %d record(s), rows %s, this run %s", reason, len(self.rows),
                 counts, self.stats_seen)
        log.info("records: %d record(s) with no document, %d dead host(s); details in %s",
                 len(empty), len(self.dead_hosts), OUT / "_report.json")
