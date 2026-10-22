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
import os
import re
from datetime import datetime, timezone

import scrapy
from scrapy import signals

from ... import catalogue as C
from .. import adapters, harvest

log = logging.getLogger(__name__)

_TIERS = {"hot": {"hot"}, "warm": {"hot", "warm"}, "all": {"hot", "warm", "cold"}}


_WAYBACK = "https://web.archive.org/web/2id_/"   # the latest capture, bytes as served
_SAVE = "https://web.archive.org/save"   # Save Page Now 2: needs a free archive.org key pair
_SAVE_STATUS = "https://web.archive.org/save/status/"
_SNAPSHOT = re.compile(r"/web/(\d{14})")
#: a host that never answered (as opposed to one that answered with "no"): the
#: Internet Archive may hold a copy
_UNREACHABLE = re.compile(r"Timeout|ConnectionRefused|ConnectionLost|ConnectError|TCPTimedOut|SSL|ConnectionDone|ResponseNeverReceived|ProxyConnect")

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
        # feeds with a detail page that failed: their notice set is incomplete
        self.partial: set[str] = set()
        self.not_modified = 0
        # A feed its host will not answer is read from the Internet Archive's copy
        # instead. A capture older than the stale limit is refreshed first (Save Page
        # Now 2, free but needs an archive.org S3 key pair in IA_ACCESS_KEY and IA_SECRET_KEY),
        # up to a few per run. Without the keys the latest capture is read as it is.
        self.wayback = os.environ.get("EXAMHUB_WAYBACK", "1") == "1"
        self.saves_left = int(os.environ.get("EXAMHUB_WAYBACK_SAVES", "20"))
        self.stale_days = int(os.environ.get("EXAMHUB_WAYBACK_STALE_DAYS", "1"))
        key, secret = os.environ.get("IA_ACCESS_KEY", ""), os.environ.get("IA_SECRET_KEY", "")
        self.ia_auth = f"LOW {key}:{secret}" if key and secret else ""

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
                      **({"download_timeout": int(f["timeout_seconds"])} if f.get("timeout_seconds") else {}),
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

    def _wayback_request(self, f, **meta):
        return scrapy.Request(
            _WAYBACK + f["url"], callback=self.parse_feed, errback=self.failed, dont_filter=True,
            meta={"feed": f, "wayback": True, "download_timeout": 90,
                  "handle_httpstatus_list": [304, 400, 401, 403, 404, 410, 429, 500, 502, 503, 504], **meta})

    def _try_wayback(self, f, req, why):
        """The Internet Archive's copy of a feed the host would not answer, once."""
        if not (self.wayback and not req.meta.get("wayback") and f["adapter"] != "json_api"):
            return None
        log.info("feed %s: %s, trying the Internet Archive", f["id"], why[:80])
        return self._wayback_request(f)

    def _spn_headers(self):
        return {"Authorization": self.ia_auth, "Accept": "application/json"}

    def _after_save(self, response_or_failure):
        """Save Page Now has run (or failed): read whatever the latest capture is now."""
        meta = getattr(response_or_failure, "meta", None) or response_or_failure.request.meta
        yield self._wayback_request(meta["feed"], saved=True)

    def _spn_started(self, response):
        f = response.meta["feed"]
        try:
            job = response.json().get("job_id")
        except ValueError:
            job = None
        if not job:
            log.info("feed %s: Save Page Now refused (%s)", f["id"], response.text[:100])
            yield from self._after_save(response)
            return
        yield self._spn_poll(f, job, 0)

    def _spn_poll(self, f, job, polls):
        return scrapy.Request(_SAVE_STATUS + job, headers=self._spn_headers(), callback=self._spn_status,
                              errback=self._after_save, dont_filter=True,
                              meta={"feed": f, "wayback": True, "saved": True, "job": job, "polls": polls,
                                    "download_timeout": 60, "handle_httpstatus_list": [400, 404, 429, 500, 502, 503]})

    def _spn_status(self, response):
        f, polls = response.meta["feed"], response.meta["polls"]
        try:
            status = response.json().get("status")
        except ValueError:
            status = "error"
        if status == "pending" and polls < 24:
            yield self._spn_poll(f, response.meta["job"], polls + 1)
            return
        yield from self._after_save(response)

    def parse_feed(self, response):
        f = response.meta["feed"]
        wb = response.meta.get("wayback")
        if wb:
            yield from self._parse_wayback(f, response)
            return
        if response.status in (403, 429, 500, 502, 503, 504) and (req := self._try_wayback(f, response.request, f"status {response.status}")):
            yield req
            return
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
        if f.get("follow") and not response.meta.get("followed"):
            # A listing of listings: its rows are not notices, they are pages to read
            # with the `follow` adapter (cookies from this request ride along).
            rep = f.get("follow_replace") or ["", ""]
            child = {**f, "adapter": f["follow"], "follow": None}
            for r in rows[: int(f.get("follow_limit", 40))]:
                yield response.follow(r["url"].replace(*rep), callback=self.parse_feed, errback=self.failed,
                                      headers={"Referer": response.url}, dont_filter=True,
                                      meta={"feed": child, "followed": True, "handle_httpstatus_list": [400, 403, 404, 500]})
            self._health(f, ok=True, status=response.status, count=len(rows), final_url=response.url)
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
        yield from self._detail_requests(f, response, rows)

    def _parse_wayback(self, f, response):
        if response.status >= 400:
            self._health(f, ok=False, status=response.status, count=0, via="wayback",
                         error=f"no Internet Archive capture (status {response.status})")
            return
        m = _SNAPSHOT.search(response.url)
        taken = datetime.strptime(m[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) if m else None
        age = (datetime.now(timezone.utc) - taken).days if taken else None
        if (self.ia_auth and age is not None and age >= self.stale_days and self.saves_left > 0
                and not response.meta.get("saved")):
            self.saves_left -= 1
            yield scrapy.FormRequest(
                _SAVE, formdata={"url": f["url"], "skip_first_archive": "1", "if_not_archived_within": "1d"},
                headers=self._spn_headers(), callback=self._spn_started, errback=self._after_save, dont_filter=True,
                meta={"feed": f, "wayback": True, "saved": True, "download_timeout": 60,
                      "handle_httpstatus_list": [400, 401, 403, 429, 500, 502, 503]})
            return
        try:
            rows = adapters.run(f, f["url"], response.body)
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            self._health(f, ok=False, status=response.status, count=0, via="wayback", error=str(exc)[:300])
            return
        self._health(f, ok=True, status=response.status, count=len(rows), via="wayback",
                     snapshot=m[1] if m else None, snapshot_age_days=age)
        self.rows.extend(rows)
        yield from rows

    def _detail_requests(self, f, response, rows):
        """Listing rows whose URL matches ``detail_include`` are pages that
        themselves list the notice's documents (UIIC's /recruitment/details/N);
        read each one with the feed's own recipe."""
        pattern = f.get("detail_include")
        if not pattern:
            return
        limit = int(f.get("detail_limit", 10))
        for r in [r for r in rows if re.search(pattern, r["url"], re.I)][:limit]:
            yield scrapy.Request(
                r["url"], callback=self.parse_detail, errback=self.detail_failed,
                meta={"feed": f, "parent": r, "render": f.get("render", "http")},
                dont_filter=True,
            )

    def parse_detail(self, response):
        f, parent = response.meta["feed"], response.meta["parent"]
        if response.status >= 400:
            self.partial.add(f["id"])
            return
        # `detail_link_include` replaces `include`: a detail page also carries
        # the site's footer documents, which are not this notice's.
        sub = {**f, "include": f.get("detail_link_include") or f.get("include"),
               "item_selector": f.get("detail_item_selector"), "link_selector": None}
        try:
            rows = adapters.run(sub, response.url, response.body)
        except (ValueError, json.JSONDecodeError, KeyError):
            self.partial.add(f["id"])
            return
        for r in rows:
            if r["url"] == parent["url"]:
                continue
            # The document's own title ("Information Handout") rarely names
            # the exam; the listing row's title does.
            r["title"] = f"{parent['title']} - {r['title']}"[:500]
            r["published"] = r.get("published") or parent.get("published")
            self.rows.append(r)
            yield r

    def detail_failed(self, failure):
        self.partial.add(failure.request.meta["feed"]["id"])

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
        if _UNREACHABLE.search(error) and (retry := self._try_wayback(f, req, error)):
            yield retry
            return
        self._health(f, ok=False, count=0, error=error[:300])

    def _closed(self, spider, reason):
        # Only a feed that answered with links can say a notice has gone.
        # (an archived copy is old: it never says a notice has gone)
        ran = {h["id"] for h in self.health if h.get("ok") and h.get("count") and not h.get("via")} - self.partial
        counts = harvest.merge_notices(self.cat, self.rows, ran)
        new_ids = counts.pop("new_ids")
        alerts = harvest.write_health(self.health)
        ok = sum(1 for h in self.health if h.get("ok") and (h.get("count") or h.get("not_modified")))
        log.info("feeds[%s]: %d/%d feeds answered (%d not modified); notices %s",
                 self.tier, ok, len(self.health), self.not_modified, counts)
        for a in alerts:
            log.warning("feed %s: %s (was %s)", a["id"], a["alert"], a.get("previous_count"))
        # `alerts` is only this run's new transitions, so a feed broken for
        # weeks never shows up here again after its one-time alert. Count
        # every feed still carrying an "alert" in the just-written health
        # file, so a maintainer sees the standing total every run, not just
        # the moment something newly broke.
        broken = [r["id"] for r in harvest.read_jsonl(harvest.HARVEST_DIR / "feed-health.jsonl") if r.get("alert")]
        if broken:
            log.warning("feeds[%s]: %d feeds currently broken: %s", self.tier, len(broken),
                        ", ".join(sorted(broken)[:10]) + (", ..." if len(broken) > 10 else ""))
        summary = {"reason": reason, "tier": self.tier, "feeds_run": len(self.health), "feeds_ok": ok,
                   "not_modified": self.not_modified, "alerts": [a["id"] for a in alerts],
                   "currently_broken": len(broken), "currently_broken_ids": sorted(broken), **counts}
        out = C.PROJECT_ROOT / "work"
        out.mkdir(exist_ok=True)
        (out / "last-crawl.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        # For the notifier: exactly this run's new notices.
        new = set(new_ids)
        harvest.write_jsonl(out / "new-notices.jsonl",
                            (r for r in harvest.read_jsonl(harvest.HARVEST_DIR / "notices.jsonl") if r["id"] in new))
