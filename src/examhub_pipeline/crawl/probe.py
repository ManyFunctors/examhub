"""Show what a feed would extract from a page, without touching the harvest.

    python -m examhub_pipeline.crawl.probe in-upsc/active-exams
    python -m examhub_pipeline.crawl.probe https://example.gov.in/notices --browser
    python -m examhub_pipeline.crawl.probe in-upsc/active-exams --save page.html

This is the maintainer's tool for fixing a feed after a site redesign: edit
the selectors in the catalogue, re-run, compare. No LLM is involved at any
point; the adapter is the same code the spider runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from .. import catalogue as C
from . import adapters, settings


def fetch(url: str, browser: bool) -> tuple[str, str, int]:
    if browser:
        from .middlewares import FirefoxMiddleware

        mw = FirefoxMiddleware(settings.GECKODRIVER, settings.FIREFOX_PAGE_WAIT, settings.USER_AGENT)
        try:
            final, html = mw._render(url, settings.FIREFOX_PAGE_WAIT)
            return final, html, 200
        finally:
            mw.close()
    headers = {"User-Agent": settings.USER_AGENT, **settings.DEFAULT_REQUEST_HEADERS}
    with httpx.Client(follow_redirects=True, timeout=45, verify=False, headers=headers) as c:
        r = c.get(url)
        return str(r.url), r.text, r.status_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a feed id from the catalogue, or a URL")
    ap.add_argument("--browser", action="store_true", help="render with headless Firefox")
    ap.add_argument("--save", help="write the fetched page here")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    cat = C.load()
    if a.target in cat.feeds:
        feed = dict(cat.feeds[a.target])
        url = feed["url"]
    else:
        url = a.target
        feed = {"id": "probe/probe", "body": "probe", "url": url, "adapter": "html_links"}
    browser = a.browser or feed.get("render") == "browser"
    final, body, status = fetch(url, browser)
    if a.save:
        Path(a.save).write_text(body, encoding="utf-8")
    rows = adapters.run(feed, final, body)
    matcher = C.Matcher(cat)
    for r in rows:
        r["exam"] = matcher.match(r["body"], r["title"], r["url"])
    if a.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
        return 0
    print(f"{status} {final}  ({len(body)} bytes, {'firefox' if browser else 'http'})  -> {len(rows)} notices")
    for r in rows[: a.limit]:
        ex = ",".join(r["exam"]) or "-"
        print(f"  [{r['doc_type'][:10]:10}] {r.get('published') or '':10} {r['title'][:80]:80} | {ex} | {r['url'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
