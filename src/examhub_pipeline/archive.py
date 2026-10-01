"""Wayback Machine copies of every document the pipeline read.

Government sites move or delete notices, so each document a record links to
(``links.documents``), then each PDF in ``data/harvest/documents/index.jsonl``,
gets a Wayback snapshot, and the
snapshot URL is kept in ``data/harvest/archived.jsonl`` (one line per URL).

Gap-driven: a URL already archived is skipped; a failed one is retried after
``RETRY_AFTER_DAYS``, doubling with each failure up to ``RETRY_MAX_DAYS`` (some
government hosts block the archive's crawler, 520/523, and may never succeed). An existing snapshot is used as is (the availability
API), so only URLs the Wayback Machine has never seen are sent to Save Page
Now. Both endpoints are free and need no key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from . import record as record_mod
from .catalogue import PROJECT_ROOT
from .config import DEFAULT_CONTACT, USER_AGENT_TEMPLATE
from .crawl.harvest import HARVEST_DIR, read_jsonl, write_jsonl

EXAMS_DIR = PROJECT_ROOT / "site" / "content" / "exams"
AVAILABLE = "https://archive.org/wayback/available"
SAVE = "https://web.archive.org/save/"
RETRY_AFTER_DAYS = 7
RETRY_MAX_DAYS = 90
#: Save Page Now allows a few anonymous captures a minute.
SAVE_INTERVAL_S = 20.0

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class Result:
    archived: int = 0      # new snapshot made
    found: int = 0         # a snapshot already existed
    failed: int = 0
    skipped: int = 0       # already done, or retried too recently
    stopped: str = ""      # why the run ended early, if it did
    errors: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def record_urls(exams_dir: Path) -> list[str]:
    """The documents the site links to: every record's ``links.documents`` URL (read only)."""
    out = []
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, _ = record_mod.load(path)
        except (OSError, ValueError):
            continue
        for d in (rec.get("links") or {}).get("documents") or []:
            url = d.get("document_url")
            if isinstance(url, str) and url.startswith("http"):
                out.append(url)
    return out


def wanted(urls: list[str], done: dict[str, dict], today: datetime) -> list[str]:
    """URLs with no snapshot yet, in the order given, skipping failures still waiting to retry."""
    out = []
    for url in urls:
        if url in out:
            continue
        prev = done.get(url)
        if prev and prev.get("snapshot"):
            continue
        if prev and prev.get("tried") and datetime.fromisoformat(prev["tried"]) > today - timedelta(days=wait_days(prev)):
            continue
        out.append(url)
    return out


def wait_days(prev: dict) -> int:
    """Days before a failed URL is tried again: 7, 14, 28, ... up to 90."""
    return min(RETRY_AFTER_DAYS * 2 ** max(prev.get("failures", 1) - 1, 0), RETRY_MAX_DAYS)


def existing_snapshot(client: httpx.Client, url: str) -> str | None:
    r = client.get(AVAILABLE, params={"url": url})
    r.raise_for_status()
    snap = (r.json().get("archived_snapshots") or {}).get("closest") or {}
    return snap.get("url") if snap.get("available") else None


def save(client: httpx.Client, url: str) -> str:
    """Ask Save Page Now for a capture; returns the snapshot URL."""
    r = client.get(SAVE + url, follow_redirects=True)
    if r.status_code == 429:
        raise RateLimited("Save Page Now says too many requests")
    r.raise_for_status()
    loc = r.headers.get("content-location")
    if loc:
        return "https://web.archive.org" + loc
    if "/web/" in str(r.url):
        return str(r.url)
    raise httpx.HTTPError(f"no snapshot location in the reply ({r.status_code})")


class RateLimited(RuntimeError):
    """The archive asked us to slow down: end the run, keep what was done."""


def run(*, limit: int = 20, dry_run: bool = False, directory: Path = HARVEST_DIR,
        exams_dir: Path | None = EXAMS_DIR,
        client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print) -> Result:
    out = Result()
    docs = read_jsonl(directory / "documents" / "index.jsonl")
    # the site's documents first: they are the ones readers follow
    urls = list(dict.fromkeys([*(record_urls(exams_dir) if exams_dir else []),
                               *(d["url"] for d in docs if d.get("url") and d.get("status") == "ok")]))
    path = directory / "archived.jsonl"
    done = {r["url"]: r for r in read_jsonl(path)}
    todo = wanted(urls, done, datetime.now(IST))
    out.skipped = len(urls) - len(todo)
    log(f"archive: {len(todo)} documents without a snapshot, {out.skipped} done or waiting to retry; taking {min(limit, len(todo))}")
    if dry_run:
        for url in todo[:limit]:
            log(f"archive: would archive {url}")
        return out

    own = client is None
    client = client or httpx.Client(timeout=120, headers={
        "User-Agent": USER_AGENT_TEMPLATE.format(contact=DEFAULT_CONTACT)})
    saves = 0
    try:
        for url in todo[:limit]:
            row = {"url": url, "tried": _now()}
            failures = done.get(url, {}).get("failures", 0)
            try:
                snap = existing_snapshot(client, url)
                if snap:
                    out.found += 1
                    log(f"archive: already archived {url} -> {snap}")
                else:
                    if saves:
                        sleep(SAVE_INTERVAL_S)
                    saves += 1
                    snap = save(client, url)
                    out.archived += 1
                    log(f"archive: archived {url} -> {snap}")
                row["snapshot"] = snap
            except RateLimited as exc:
                out.stopped = str(exc)
                log(f"archive: stopping early: {exc}")
                break
            except (httpx.HTTPError, ValueError) as exc:
                out.failed += 1
                row["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"[:300]
                row["failures"] = failures + 1
                out.errors.append(f"{url}: {row['error']}")
                log(f"archive: failed {url}: {row['error']} (try {row['failures']}, next in {wait_days(row)} days)")
            done[url] = row
    finally:
        if own:
            client.close()
        # written even after an error, so a partial run keeps what it did
        write_jsonl(path, done.values(), key="url")
    log(f"archive: {out.archived} archived, {out.found} already there, {out.failed} failed")
    return out


def fill_records(exams_dir: Path = EXAMS_DIR, *, directory: Path = HARVEST_DIR, apply: bool = False,
                 log: Callable[[str], None] = print) -> int:
    """Set ``document_archive`` on each record document that has a snapshot and says
    'not_archived'. Returns how many records changed."""
    snaps = {r["url"]: r["snapshot"] for r in read_jsonl(directory / "archived.jsonl") if r.get("snapshot")}
    changed = 0
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, body = record_mod.load(path)
        except (OSError, ValueError) as exc:
            log(f"archive: {path.name}: skipped, unreadable ({exc})")
            continue
        n = 0
        for d in (rec.get("links") or {}).get("documents") or []:
            snap = snaps.get(d.get("document_url"))
            if snap and d.get("document_archive") in (None, "not_archived"):
                d["document_archive"] = snap
                n += 1
        if n:
            changed += 1
            log(f"archive: {path.name}: {n} document(s) given their Wayback copy")
            if apply:
                path.write_text(record_mod.dumps(rec, body), encoding="utf-8")
    log(f"archive: {changed} record(s) {'updated' if apply else 'would be updated (dry run)'}")
    return changed
