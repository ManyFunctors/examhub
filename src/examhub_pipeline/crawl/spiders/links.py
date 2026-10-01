"""Fetch every link the exam records carry and record what each one is.

    scrapy crawl links
    scrapy crawl links -a only=ups-engineering-services-prelims-2027,nw-hp-tet-november-2026

Reads ``site/content/exams`` (official page, apply link, documents), follows
each page's own "Apply Online" links one hop, and writes
``data/harvest/link-check.jsonl``: one line per URL with ``state``, ``kind``
(file · portal · page), ``home``, ``apply_links``, ``title`` and ``text``
(see crawl/linkcheck.py). A page with almost no text is fetched again in
headless Firefox, since it is probably drawn by script.

A file is not downloaded whole: the download stops once the headers and the
first bytes say what it is. `checked` moves only when what the link is changes,
so an unchanged web makes no diff.
"""
from __future__ import annotations

from pathlib import Path

import scrapy
from scrapy import signals
from scrapy.exceptions import StopDownload

from ... import record as record_mod
from ...catalogue import PROJECT_ROOT
from .. import harvest
from ..linkcheck import classify

EXAMS = PROJECT_ROOT / "site" / "content" / "exams"
OUT = "link-check.jsonl"
#: the fields whose change counts as the link changing
_SAME = ("state", "kind", "home", "final_url", "apply_links", "title")


def record_links(exams: Path, only: set[str] | None = None) -> dict[str, list[str]]:
    """url -> the records that carry it."""
    out: dict[str, list[str]] = {}
    for path in sorted(exams.glob("*.md")):
        if only and path.stem not in only:
            continue
        try:
            rec, _ = record_mod.load(path)
        except (OSError, ValueError):
            continue
        links = rec.get("links") or {}
        urls = [links.get("link_official_page"), links.get("link_apply"),
                *(d.get("document_url") for d in links.get("documents") or [])]
        for u in urls:
            if isinstance(u, str) and u.startswith("http"):
                out.setdefault(u, []).append(path.stem)
    return out


class LinksSpider(scrapy.Spider):
    name = "links"
    # one fetch per link a reader can click on our site, never a walk through a site,
    # so robots.txt (kept by the harvest crawlers) is not consulted here
    custom_settings = {"HTTPCACHE_ENABLED": False, "DOWNLOAD_TIMEOUT": 45, "RETRY_TIMES": 1,
                       "ROBOTSTXT_OBEY": False}

    def __init__(self, only: str = "", **kw):
        super().__init__(**kw)
        self.only = set(filter(None, only.split(","))) or None
        self.results: dict[str, dict] = {}

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        crawler.signals.connect(spider._headers, signal=signals.headers_received)
        return spider

    def _headers(self, headers, body_length, request, spider):
        # a file says so in its headers; its bytes are not needed, only its first few
        ctype = (headers.get(b"Content-Type") or b"").decode("latin-1").lower()
        if ctype and "html" not in ctype and "text/" not in ctype and "xml" not in ctype:
            request.meta["content_type"] = ctype
            raise StopDownload(fail=False)

    def _request(self, url, refs, hop=0, render=None):
        meta = {"refs": refs, "hop": hop, "handle_httpstatus_list": [400, 401, 403, 404, 410, 429, 500, 502, 503, 504]}
        if render:
            meta["render"] = render
        return scrapy.Request(url, callback=self.parse, errback=self.failed, dont_filter=True, meta=meta)

    async def start(self):
        for url, refs in record_links(EXAMS, self.only).items():
            yield self._request(url, refs)

    def parse(self, response):
        url = response.meta.get("redirect_urls", [response.request.url])[0]
        ctype = response.meta.get("content_type") or (response.headers.get(b"Content-Type") or b"").decode("latin-1")
        try:
            info = classify(url, response.url, response.status, ctype, response.body)
        except Exception as exc:  # a page we can't read is recorded, not lost
            self.logger.exception("links: could not classify %s", url)
            self.results[url] = {"state": "error", "refs": response.meta["refs"],
                                 "error": f"classify: {type(exc).__name__}: {exc}"[:240]}
            return
        info["refs"] = response.meta["refs"]
        if info.get("thin") and info["state"] == "ok" and response.meta.get("render") != "browser":
            # drawn by script: ask Firefox
            req = self._request(url, info["refs"], response.meta["hop"], render="browser")
            req.meta["plain"] = {**{k: v for k, v in info.items() if k != "thin"}, "refs": info["refs"]}
            yield req
            return
        info.pop("thin", None)
        self.results[url] = info
        if response.meta["hop"] == 0:
            for target in info.get("apply_links") or []:
                if target not in self.results:
                    yield self._request(target, [f"apply-link:{url}"], hop=1)

    def failed(self, failure):
        req = failure.request
        url = req.meta.get("redirect_urls", [req.url])[0]
        if req.meta.get("plain"):
            # Firefox failed: the plain fetch still says what the page is
            self.logger.warning("links: browser failed on %s, keeping the plain fetch", url)
            self.results[url] = req.meta["plain"]
            return
        name = failure.type.__name__
        # robots.txt said no: we can't tell; no such host: the link is dead
        state = {"IgnoreRequest": "blocked", "CannotResolveHostError": "not_found",
                 "DNSLookupError": "not_found"}.get(name, "error")
        self.logger.info("links: %s %s (%s)", state, url, name)
        self.results[url] = {"state": state, "refs": req.meta.get("refs", []),
                             "error": f"{name}: {failure.value}"[:240]}

    def _closed(self, spider, reason):
        path = harvest.HARVEST_DIR / OUT
        old = {r["id"]: r for r in harvest.read_jsonl(path)}
        now = harvest.now()
        for url, r in self.results.items():
            prev = old.get(url)
            same = prev and all(prev.get(k) == r.get(k) for k in _SAME)
            old[url] = {"id": url, **r, "checked": prev["checked"] if same else now}
        harvest.write_jsonl(path, old.values())
        counts: dict[str, int] = {}
        for r in self.results.values():
            key = f"{r.get('state')}/{r.get('kind', '-')}"
            counts[key] = counts.get(key, 0) + 1
        self.logger.info("links: %d checked: %s", len(self.results), counts)
