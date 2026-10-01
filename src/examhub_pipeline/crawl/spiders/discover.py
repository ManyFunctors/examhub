"""Find sources the catalogue does not know about yet.

    scrapy crawl discover                    # everything below
    scrapy crawl discover -a only=ct         # just Certificate Transparency
    scrapy crawl discover -a jurisdiction=kl

Three deterministic sources, each written to ``data/harvest/`` as a
worklist that a maintainer turns into catalogue entries (or ignores):

``discovered-hosts.jsonl``
    New hostnames under each body's domain, from Certificate Transparency
    logs (crt.sh's public database, see crawl/ctlog.py). A new exam portal -- ``neet2027.nta.nic.in``,
    ``recruitment.somepsc.gov.in`` -- gets its TLS certificate days before
    the notification that links to it, so this is the earliest signal
    there is. Seen hosts are remembered; only new ones are added.

``discovered-feeds.jsonl``
    RSS/Atom feeds a body's homepage advertises (``<link rel=alternate>``)
    and sitemaps its robots.txt lists. A feed is the cheapest possible
    source: small, structured, dated.

``discovered-pages.jsonl``
    Links on a body's homepage whose text says notice board, recruitment,
    results, what's new ... and that no feed covers yet.

Nothing here edits the catalogue.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urljoin, urlsplit

import scrapy
from scrapy import signals

from ... import catalogue as C
from .. import adapters, ctlog, harvest

#: Hosts under a body's domain that are never a source of notices.
_BORING_HOST = re.compile(
    r"^(\*\.|www\.)|^(mail|webmail|smtp|imap|pop|mx|autodiscover|autoconfig|cpanel|whm|webdisk|"
    r"ftp|vpn|ns\d*|dns|sso|ldap|proxy|cdn|static|assets|img|images|media|api|dev|test|uat|staging|"
    r"demo|beta|old|backup|mysql|db|git|jenkins|grafana|monitor|status|remote|owa|lync|sip)\.", re.I)

#: Link text on a homepage that names a notice-bearing page.
_PAGE_WORDS = re.compile(
    r"\b(notice\s*board|notices?|notifications?|advertisements?|advt|recruitments?|vacanc(y|ies)|"
    r"careers?|jobs?|results?|examinations?|exam\s*calendar|what'?s\s*new|latest\s*(news|updates)|"
    r"announcements?|circulars?|admissions?|counsell?ing|admit\s*cards?|answer\s*keys?)\b", re.I)

#: Candidate pages fetched and scored per body per run.
TRIALS_PER_BODY = 8

_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")

# Suffixes under which a body's own domain is one label deeper than the
# registrable one: upsc.gov.in, bpsc.bih.nic.in, keralapsc.gov.in ...
_SHARED = ("gov.in", "nic.in", "ac.in", "edu.in", "org.in", "res.in", "co.in", "net.in")


def body_domain(url: str) -> str | None:
    """The domain that is the body's own: ``www.bpsc.bih.nic.in`` ->
    ``bpsc.bih.nic.in``; ``https://ssc.gov.in/`` -> ``ssc.gov.in``;
    ``https://www.ibps.in`` -> ``ibps.in``. None for hosts that are only a
    shared suffix."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host or host in _SHARED or host.count(".") < 1:
        return None
    return host


class DiscoverSpider(scrapy.Spider):
    name = "discover"
    custom_settings = {"HTTPCACHE_ENABLED": False, "DOWNLOAD_TIMEOUT": 60, "RETRY_TIMES": 1}

    def __init__(self, only: str = "", jurisdiction: str = "", **kw):
        super().__init__(**kw)
        self.cat = C.load()
        self.only = set(filter(None, only.split(","))) or {"ct", "feeds", "pages"}
        self.jurs = set(filter(None, jurisdiction.split(",")))
        self.hosts: dict[str, dict] = {}
        self.feeds: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.matcher = C.Matcher(self.cat)
        self.tried: dict[str, int] = {}
        self.cursor_path = harvest.HARVEST_DIR / "ct-cursors.json"
        self.cursors: dict[str, str] = (json.loads(self.cursor_path.read_text())
                                        if self.cursor_path.exists() else {})
        self.known_hosts = set()
        self.known_urls = set()
        for b in self.cat.bodies.values():
            self.known_hosts.add((urlsplit(b["website"]).hostname or "").removeprefix("www."))
            self.known_hosts.update(h.removeprefix("www.") for h in b.get("hosts", []))
        for f in self.cat.feeds.values():
            self.known_hosts.add((urlsplit(f["url"]).hostname or "").removeprefix("www."))
            self.known_urls.add(adapters.canonical_url(f["url"]).rstrip("/"))
        for e in self.cat.exams.values():
            if e.get("official_url"):
                self.known_hosts.add((urlsplit(e["official_url"]).hostname or "").removeprefix("www."))

    @classmethod
    def from_crawler(cls, crawler, *a, **kw):
        spider = super().from_crawler(crawler, *a, **kw)
        crawler.signals.connect(spider._closed, signal=signals.spider_closed)
        return spider

    def _bodies(self):
        for b in self.cat.bodies.values():
            if b.get("status") != "active":
                continue
            if self.jurs and b["jurisdiction"] not in self.jurs:
                continue
            yield b

    async def start(self):
        domains: dict[str, str] = {}
        for b in self._bodies():
            if "ct" in self.only:
                for u in [b["website"], *(f"https://{h}/" for h in b.get("hosts", []))]:
                    d = body_domain(u)
                    if d:
                        domains.setdefault(d, b["id"])
            if "feeds" in self.only or "pages" in self.only:
                yield scrapy.Request(b["website"], callback=self.parse_home, errback=self.ignore,
                                     meta={"body": b["id"]}, dont_filter=True)
            if "feeds" in self.only:
                yield scrapy.Request(urljoin(b["website"], "/robots.txt"), callback=self.parse_robots,
                                     errback=self.ignore, meta={"body": b["id"], "dont_obey_robotstxt": True},
                                     dont_filter=True)
        key = os.environ.get("CERTSPOTTER_API_KEY")
        for d, bid in sorted(domains.items()) if key else ():
            meta = {"body": bid, "domain": d, "download_timeout": 90}
            if key:
                # Cert Spotter, incremental: only issuances after the last one
                # seen for this domain.
                after = self.cursors.get(d)
                yield scrapy.Request(
                    f"https://api.certspotter.com/v1/issuances?domain={d}&include_subdomains=true"
                    f"&expand=dns_names{'&after=' + after if after else ''}",
                    headers={"Authorization": f"Bearer {key}"}, callback=self.parse_certspotter,
                    errback=self.ignore, meta=meta, dont_filter=True)
        if domains and not key:
            # crt.sh's database (its web pages bar crawlers): a time-boxed worker thread
            budget = float(os.environ.get("EXAMHUB_CT_BUDGET", "1500"))
            found = await asyncio.to_thread(ctlog.lookup, sorted(domains), self.cursors, budget)
            for d, rows in found.items():
                self._add_hosts(domains[d], d, rows)

    def ignore(self, failure):
        self.logger.info("discover: %s: %s", failure.request.url, failure.value)

    def parse_certspotter(self, response):
        try:
            issuances = json.loads(response.text)
        except ValueError:
            return
        if not isinstance(issuances, list) or not issuances:
            return
        d = response.meta["domain"]
        self.cursors[d] = issuances[-1]["id"]
        rows = [{"name_value": "\n".join(i.get("dns_names", [])), "not_before": i.get("not_before", "")}
                for i in issuances]
        self._add_hosts(response.meta["body"], d, rows)
        if len(issuances) >= 100:  # a full page: there is more
            yield response.request.replace(
                url=re.sub(r"&after=[^&]*|$", f"&after={self.cursors[d]}", response.request.url, count=1))

    def _add_hosts(self, bid: str, domain: str, certs: list[dict]) -> None:
        for c in certs:
            for name in str(c.get("name_value", "")).lower().split():
                name = name.strip().removeprefix("www.")
                if not name.endswith(domain) or _BORING_HOST.match(name) or name in self.known_hosts:
                    continue
                first = (c.get("not_before") or "")[:10]
                cur = self.hosts.get(name)
                if not cur or (first and first < cur["cert_first"]):
                    self.hosts[name] = {"id": name, "body": bid, "cert_first": first,
                                        "url": f"https://{name}/"}

    def parse_robots(self, response):
        if response.status != 200:
            return
        for m in re.finditer(r"(?im)^\s*sitemap:\s*(\S+)", response.text):
            u = m.group(1)
            self.feeds.setdefault(u, {"id": u, "body": response.meta["body"], "kind": "sitemap"})

    def parse_home(self, response):
        if not hasattr(response, "css"):
            return
        bid = response.meta["body"]
        if "feeds" in self.only:
            for link in response.css("link[rel~=alternate][href]"):
                t = (link.attrib.get("type") or "").lower()
                if t in _FEED_TYPES:
                    u = adapters.canonical_url(response.urljoin(link.attrib["href"]))
                    host = urlsplit(u).hostname or ""
                    # WordPress advertises a comments feed beside the posts
                    # feed; static-site builds leak their dev server.
                    if re.search(r"/comments/feed/?$", u) or host in ("localhost", "0.0.0.0", "127.0.0.1") or "." not in host:
                        continue
                    if u.rstrip("/") not in self.known_urls and u not in self.feeds:
                        self.feeds[u] = {"id": u, "body": bid, "kind": t.split("/")[1].split("+")[0],
                                         "title": adapters.clean(link.attrib.get("title"))}
                        yield self._trial(u, bid, "rss")
        if "pages" in self.only:
            home_host = (urlsplit(response.url).hostname or "").removeprefix("www.")
            for a in response.css("a[href]"):
                text = adapters.clean(" ".join(a.css("::text").getall()) or a.attrib.get("title"))
                if not text or len(text) > 60 or not _PAGE_WORDS.search(text):
                    continue
                href = a.attrib["href"].strip()
                if href.lower().startswith(("mailto:", "javascript:", "tel:", "#")) or adapters.DOC_EXT.search(href):
                    continue
                u = adapters.canonical_url(response.urljoin(href))
                host = (urlsplit(u).hostname or "").removeprefix("www.")
                if host != home_host and not host.endswith("." + home_host):
                    continue
                if u.rstrip("/") in self.known_urls or u in self.pages:
                    continue
                self.pages[u] = {"id": u, "body": bid, "text": text}
                self.tried[bid] = self.tried.get(bid, 0) + 1
                if self.tried[bid] <= TRIALS_PER_BODY:
                    yield self._trial(u, bid, "html_links")

    def _trial(self, url: str, bid: str, adapter: str) -> scrapy.Request:
        """Fetch a candidate and run the real adapter and matcher on it, so a
        proposal says what adopting it would yield, not just that it exists."""
        return scrapy.Request(url, callback=self.parse_trial, errback=self.ignore, dont_filter=True,
                              meta={"body": bid, "adapter": adapter, "download_timeout": 40})

    def parse_trial(self, response):
        bid, adapter = response.meta["body"], response.meta["adapter"]
        target = self.feeds if adapter == "rss" else self.pages
        key = response.request.url
        rec = target.get(key) or target.get(adapters.canonical_url(key))
        if rec is None or response.status >= 400:
            return
        feed = {"id": f"{bid}/trial", "body": bid, "url": response.url, "adapter": adapter}
        try:
            rows = adapters.run(feed, response.url, response.body)
        except Exception:  # a trial never fails the spider
            return
        hits = [r for r in rows if self.matcher.match(bid, r["title"], r["url"])]
        rec.update({"notices": len(rows), "matched": len(hits),
                    "sample": [r["title"][:120] for r in (hits or rows)[:3]]})

    def _closed(self, spider, reason):
        if self.cursors:
            self.cursor_path.write_text(json.dumps(self.cursors, indent=1, sort_keys=True) + "\n")
        for name, source, rows in (("discovered-hosts", "ct", self.hosts),
                                   ("discovered-feeds", "feeds", self.feeds),
                                   ("discovered-pages", "pages", self.pages)):
            if source not in self.only:
                continue
            path = harvest.HARVEST_DIR / f"{name}.jsonl"
            old = {r["id"]: r for r in harvest.read_jsonl(path)}
            added = 0
            for k, r in rows.items():
                if k not in old:
                    r["first_seen"] = harvest.now()
                    old[k] = r
                    added += 1
                else:
                    # A fresh trial replaces the old score; first_seen stays.
                    old[k] = {**old[k], **r, "first_seen": old[k]["first_seen"]}
            # Anything the catalogue has since adopted leaves the worklist.
            if name == "discovered-hosts":
                old = {k: v for k, v in old.items() if k not in self.known_hosts}
            else:
                old = {k: v for k, v in old.items() if k.rstrip("/") not in self.known_urls}
            harvest.write_jsonl(path, old.values())
            self.logger.info("discover: %s: %d new, %d open", name, added, len(old))
