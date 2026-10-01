"""Check every URL the catalogue asserts: body websites and exam pages.

    scrapy crawl verify
    scrapy crawl verify -a jurisdiction=kl

Writes ``data/harvest/url-health.jsonl``, one line per URL, with the same
rule as feed health: `since` moves only when the state changes, so a
healthy catalogue produces no diff. A URL is only ever *reported*; the
catalogue is never edited by a machine.

States: ``ok`` (2xx), ``redirected`` (2xx on another host -- the catalogue
should probably be updated), ``soft_404`` (2xx on a not-found page),
``blocked`` (401/403/429/503 -- reachable in a browser, not by script),
``not_found`` (404/410), ``error`` (DNS, TLS, timeout).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import scrapy
from scrapy import signals

from ... import catalogue as C
from .. import harvest

_SOFT_404 = re.compile(r"(page\s*not\s*found|pagenotfound|filenotfound|404\s*error|error\s*404|the requested url was not found)", re.I)


class VerifySpider(scrapy.Spider):
    name = "verify"
    custom_settings = {"HTTPCACHE_ENABLED": False, "DOWNLOAD_TIMEOUT": 30, "RETRY_TIMES": 1}

    def __init__(self, jurisdiction: str = "", **kw):
        super().__init__(**kw)
        self.cat = C.load()
        self.jurs = set(filter(None, jurisdiction.split(",")))
        self.results: dict[str, dict] = {}

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        return spider

    def targets(self):
        seen = set()
        for b in self.cat.bodies.values():
            if self.jurs and b["jurisdiction"] not in self.jurs:
                continue
            if b.get("status") == "active" and b["website"] not in seen:
                seen.add(b["website"])
                yield b["website"], [f"body:{b['id']}"]
        for e in self.cat.exams.values():
            if self.jurs and e["jurisdiction"] not in self.jurs:
                continue
            u = e.get("official_url")
            if u and u not in seen:
                seen.add(u)
                yield u, [f"exam:{e['id']}"]

    async def start(self):
        for url, refs in self.targets():
            yield scrapy.Request(url, callback=self.parse, errback=self.failed, dont_filter=True,
                                 meta={"refs": refs, "handle_httpstatus_list": [400, 401, 403, 404, 410, 429, 500, 502, 503, 504]})

    def _record(self, url, refs, state, **kw):
        self.results[url] = {"id": url, "refs": refs, "state": state, "checked": harvest.now(), **kw}

    def parse(self, response):
        req = response.request
        url = response.meta.get("redirect_urls", [req.url])[0]
        s = response.status
        if s in (401, 403, 429, 503):
            state = "blocked"
        elif s in (404, 410):
            state = "not_found"
        elif s >= 400:
            state = "error"
        else:
            head = response.text[:20000] if hasattr(response, "text") else ""
            if _SOFT_404.search(response.url) or _SOFT_404.search(head[:3000]):
                state = "soft_404"
            elif (urlsplit(response.url).hostname or "").removeprefix("www.") != (urlsplit(url).hostname or "").removeprefix("www."):
                state = "redirected"
            else:
                state = "ok"
        title = ""
        if hasattr(response, "css"):
            title = " ".join(response.css("title::text").get(default="").split())[:160]
        self._record(url, response.meta["refs"], state, status=s, final_url=response.url, title=title)

    def failed(self, failure):
        req = failure.request
        self._record(req.url, req.meta["refs"], "error", error=f"{failure.type.__name__}: {failure.value}"[:240])

    def _closed(self, spider, reason):
        path = harvest.HARVEST_DIR / "url-health.jsonl"
        old = {r["id"]: r for r in harvest.read_jsonl(path)}
        for url, r in self.results.items():
            checked = r.pop("checked")
            prev = old.get(url)
            r["since"] = prev["since"] if prev and prev.get("state") == r["state"] else checked
            old[url] = r
        harvest.write_jsonl(path, old.values())
        counts: dict[str, int] = {}
        for r in self.results.values():
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        self.logger.info("verify: %s", counts)
