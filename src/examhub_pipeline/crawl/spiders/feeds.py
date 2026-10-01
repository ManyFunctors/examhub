"""Read every active feed in the catalogue and merge notices into the harvest.

    scrapy crawl feeds
    scrapy crawl feeds -a tier=hot              # only feeds in season (the fast loop)
    scrapy crawl feeds -a tier=warm             # hot and warm
    scrapy crawl feeds -a body=in-upsc,in-ssc
    scrapy crawl feeds -a jurisdiction=kl
    scrapy crawl feeds -a include_blocked=1     # also try feeds marked blocked

Requests are conditional where the host allows it: the ETag and
Last-Modified from the previous run are sent back, and a 304 costs the host
nothing and changes nothing here. A quarter of the catalogue's hosts support
it; for the rest the change test is the extracted notice set, not the page
bytes, because visitor counters and CSRF tokens change the bytes every time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

import scrapy
from scrapy import signals

from ... import catalogue as C
from .. import adapters, harvest

log = logging.getLogger(__name__)

_TIERS = {"hot": {"hot"}, "warm": {"hot", "warm"}, "all": {"hot", "warm", "cold"}}


#: failures from a reply the server sent but got wrong, not from one it never sent
_MALFORMED = re.compile(r"InvalidHeader|ResponseFailed|BadHttpHeader|ParseError|_DataLoss")

class FeedsSpider(scrapy.Spider):
    name = "feeds"

    def __init__(self, body: str = "", jurisdiction: str = "", feed: str = "",
                 include_blocked: str = "", tier: str = "all", **kw):
        super().__init__(**kw)
        self.cat = C.load()
        self.bodies = set(filter(None, body.split(",")))
        self.jurs = set(filter(None, jurisdiction.split(",")))
        self.only = set(filter(None, feed.split(",")))
        self.include_blocked = bool(include_blocked)
        if tier not in _TIERS:
            raise ValueError(f"tier must be one of {sorted(_TIERS)}")
        self.tier = tier
        self.tiers = harvest.feed_tiers(self.cat) if tier != "all" else {}
        self.prev = {r["id"]: r for r in harvest.read_jsonl(harvest.HARVEST_DIR / "feed-health.jsonl")}
        self.rows: list[dict] = []
        self.health: list[dict] = []
        self.not_modified = 0

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        return spider

    def selected_feeds(self):
        ok = {"active", "blocked"} if self.include_blocked else {"active"}
        for f in self.cat.feeds.values():
            b = self.cat.bodies[f["body"]]
            if f["status"] not in ok:
                continue
            if self.only and f["id"] not in self.only:
                continue
            if self.bodies and f["body"] not in self.bodies:
                continue
            if self.jurs and b["jurisdiction"] not in self.jurs:
                continue
            if self.tiers and self.tiers.get(f["id"], "cold") not in _TIERS[self.tier]:
                continue
            yield f

    def _conditional(self, f) -> dict:
        prev = self.prev.get(f["id"]) or {}
        if f.get("render") == "browser" or not prev.get("count"):
            return {}
        h = {}
        if prev.get("etag"):
            h["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"):
            h["If-Modified-Since"] = prev["last_modified"]
        return h

    async def start(self):
        for f in self.selected_feeds():
            yield scrapy.Request(
                f["url"], callback=self.parse_feed, errback=self.failed,
                headers=self._conditional(f),
                meta={"feed": f, "render": f.get("render", "http"),
                      # Let redirects be followed; see every other status.
                      "handle_httpstatus_list": [304, 400, 401, 403, 404, 410, 429, 500, 502, 503, 504]},
                dont_filter=True,
            )

    def _health(self, f, **kw):
        self.health.append({"id": f["id"], "body": f["body"], "url": f["url"],
                            "checked": harvest.now(), **kw})

    @staticmethod
    def _validators(response) -> dict:
        out = {}
        for key, header in (("etag", b"ETag"), ("last_modified", b"Last-Modified")):
            v = response.headers.get(header)
            if v:
                out[key] = v.decode("latin1")
        return out

    def parse_feed(self, response):
        f = response.meta["feed"]
        if response.status == 304:
            self.not_modified += 1
            self._health(f, ok=True, not_modified=True, **self._validators(response))
            return
        if response.status >= 400:
            self._health(f, ok=False, status=response.status, count=0, final_url=response.url)
            return
        try:
            rows = adapters.run(f, response.url, response.body)
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            self._health(f, ok=False, status=response.status, count=0, error=str(exc)[:300])
            return
        if (not rows and "firefox" not in response.flags and f["adapter"] in ("html_links", "html_table")
                and self.settings.getbool("EXAMHUB_AUTO_BROWSER", True) and adapters.looks_unrendered(response.body)):
            # An empty page that is mostly script is a client-rendered site.
            # One retry in Firefox, and the feed is marked so the maintainer
            # can make `render = "browser"` explicit.
            yield response.request.replace(
                headers={}, dont_filter=True,
                meta={**response.meta, "render": "browser", "auto_browser": True})
            return
        # Validators are stored only when the notice set changed. A host that
        # rotates its ETag on every request then simply never answers 304,
        # instead of rewriting feed-health.jsonl on every run.
        sha = hashlib.sha256("\n".join(sorted(r["id"] for r in rows)).encode()).hexdigest()[:16]
        prev = self.prev.get(f["id"]) or {}
        if rows and prev.get("notices_sha") == sha:
            validators = {k: prev[k] for k in ("etag", "last_modified") if k in prev}
        else:
            validators = self._validators(response) if rows else {}
        extra = {"auto_browser": True} if response.meta.get("auto_browser") and rows else {}
        self._health(f, ok=True, status=response.status, count=len(rows), notices_sha=sha,
                     final_url=response.url, rendered="firefox" in response.flags, **validators, **extra)
        self.rows.extend(rows)
        for r in rows:
            yield r

    def failed(self, failure):
        req = failure.request
        f = req.meta["feed"]
        error = f"{failure.type.__name__}: {failure.value}"
        if (_MALFORMED.search(error) and req.meta.get("render") != "browser"
                and self.settings.getbool("EXAMHUB_AUTO_BROWSER", True)):
            # a reply browsers accept but Twisted rejects (a bad header): ask Firefox
            log.info("feed %s: malformed reply (%s), trying Firefox", f["id"], error[:120])
            yield req.replace(dont_filter=True, meta={**req.meta, "render": "browser", "auto_browser": True})
            return
        self._health(f, ok=False, count=0, error=error[:300])

    def _closed(self, spider, reason):
        # Only a feed that answered with links can say a notice has gone.
        ran = {h["id"] for h in self.health if h.get("ok") and h.get("count")}
        counts = harvest.merge_notices(self.cat, self.rows, ran)
        new_ids = counts.pop("new_ids")
        alerts = harvest.write_health(self.health)
        ok = sum(1 for h in self.health if h.get("ok") and (h.get("count") or h.get("not_modified")))
        log.info("feeds[%s]: %d/%d feeds answered (%d not modified); notices %s",
                 self.tier, ok, len(self.health), self.not_modified, counts)
        for a in alerts:
            log.warning("feed %s: %s (was %s)", a["id"], a["alert"], a.get("previous_count"))
        summary = {"reason": reason, "tier": self.tier, "feeds_run": len(self.health), "feeds_ok": ok,
                   "not_modified": self.not_modified, "alerts": [a["id"] for a in alerts], **counts}
        out = C.PROJECT_ROOT / "work"
        out.mkdir(exist_ok=True)
        (out / "last-crawl.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        # For the notifier: exactly this run's new notices.
        new = set(new_ids)
        harvest.write_jsonl(out / "new-notices.jsonl",
                            (r for r in harvest.read_jsonl(harvest.HARVEST_DIR / "notices.jsonl") if r["id"] in new))
