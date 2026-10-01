"""The observation store: ``data/harvest/*.jsonl``.

Files are sorted by id and written with sorted keys, one object per line, so
that a scheduled run's git diff *is* its change report: a new notice is one
added line, a notice that vanished from its feed is one changed `last_seen`.

* ``notices.jsonl``      every notice ever seen; `gone_since` when it left its feed
* ``unmatched.jsonl``    notices no exam's patterns claimed: the worklist
* ``ambiguous.jsonl``    notices two exams claimed: a pattern defect
* ``feed-health.jsonl``  one line per feed for the latest run
* ``proposals-*.jsonl``  exam series proposed by the seed spiders
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from ..catalogue import PROJECT_ROOT, Catalogue, Matcher, cycle_label
from .adapters import classify_doc_type, stamped_date

HARVEST_DIR = PROJECT_ROOT / "data" / "harvest"
IST = timezone(timedelta(hours=5, minutes=30))


def now() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def write_jsonl(path: Path, rows: Iterable[dict], key: str = "id") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (str(r.get(key, "")),))
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)
    return len(rows)


def classify(cat: Catalogue, matcher: Matcher, row: dict) -> dict:
    """Attach exam and cycle, deterministically, to a notice row."""
    if cat.feeds.get(row.get("feed", ""), {}).get("match_scope") == "all":
        hits = matcher.match_any_body(row["title"], row["url"])
    else:
        hits = matcher.match(row["body"], row["title"], row["url"])
    row.pop("exam", None)
    row.pop("ambiguous", None)
    row.pop("cycle", None)
    if len(hits) == 1:
        row["exam"] = hits[0]
        label = cycle_label(row["title"])
        if label:
            row["cycle"] = f"{hits[0]}/{label}"
    elif len(hits) > 1:
        row["ambiguous"] = hits
    return row


def _load_canonical(path: Path) -> dict[str, dict]:
    """Stored notices, re-keyed under the current URL canonicalisation.

    When canonicalisation improves (say, dropping S3 signature parameters),
    the notices it now considers one are collapsed into one: the earliest
    first_seen wins, and it is live if any copy was live. A notice's id is
    therefore always sha256(canonical_url(url)) for today's rules."""
    from .adapters import canonical_url, notice_id

    out: dict[str, dict] = {}
    for r in read_jsonl(path):
        url = canonical_url(r["url"])
        if url != r["url"]:
            titled = r["id"] == notice_id(r["url"], r["title"])
            r = {**r, "url": url, "id": notice_id(url, r["title"] if titled else None)}
        prev = out.get(r["id"])
        if prev:
            if prev["first_seen"] < r["first_seen"]:
                r["first_seen"] = prev["first_seen"]
            if "gone_since" not in prev or "gone_since" not in r:
                r.pop("gone_since", None)
        out[r["id"]] = r
    return out


def merge_notices(cat: Catalogue, fresh: list[dict], ran_feeds: set[str], directory: Path = HARVEST_DIR) -> dict:
    """Merge a run's rows into ``notices.jsonl``. Returns counts."""
    matcher = Matcher(cat)
    ts = now()
    path = directory / "notices.jsonl"
    old = _load_canonical(path)
    new_ids = []
    for r in fresh:
        prev = old.get(r["id"])
        r = classify(cat, matcher, dict(r))
        r["first_seen"] = prev["first_seen"] if prev else ts
        # Keep what an earlier run knew and this one did not.
        if prev:
            for k in ("published", "content_sha256"):
                if not r.get(k) and prev.get(k):
                    r[k] = prev[k]
        else:
            new_ids.append(r["id"])
        old[r["id"]] = r
    # A notice with no printed date gets the one its title or file name states, on every
    # run, so old rows fill as the rule improves; `published_from` says it was inferred.
    for r in old.values():
        # a type added to the classifier reaches notices seen before it existed
        if r.get("doc_type") == "other":
            r["doc_type"] = classify_doc_type(r.get("title") or "", r.get("url") or "")
        if not r.get("published"):
            found = stamped_date(r.get("title") or "", r.get("url") or "", ts[:10])
            if found:
                r["published"], r["published_from"] = found
    # A notice missing from a feed that ran fine is marked gone, not deleted;
    # one that comes back is un-marked. No per-run timestamp is written, so a
    # run in which nothing changed leaves the file byte-identical.
    seen = {r["id"] for r in fresh}
    gone_ids, back_ids = [], []
    for r in old.values():
        if r["id"] in seen:
            if r.pop("gone_since", None):
                back_ids.append(r["id"])
        elif r.get("feed") in ran_feeds and "gone_since" not in r:
            r["gone_since"] = ts
            gone_ids.append(r["id"])
    # Re-classify everything: a catalogue edit re-matches old notices too.
    for r in old.values():
        classify(cat, matcher, r)
    write_jsonl(path, old.values())
    changes = ([dict(_change_view(old[i]), change="new", at=ts) for i in new_ids]
               + [dict(_change_view(old[i]), change="gone", at=ts) for i in gone_ids]
               + [dict(_change_view(old[i]), change="back", at=ts) for i in back_ids])
    append_changes(changes, directory)
    write_atom(old.values(), directory)
    write_jsonl(directory / "unmatched.jsonl",
                ({k: r[k] for k in ("id", "body", "feed", "title", "url", "doc_type", "first_seen") if k in r}
                 for r in old.values() if "exam" not in r and "ambiguous" not in r
                 and "gone_since" not in r),
                key="body")
    write_jsonl(directory / "ambiguous.jsonl",
                ({k: r[k] for k in ("id", "body", "title", "url", "ambiguous") if k in r}
                 for r in old.values() if "ambiguous" in r))
    return {
        "total": len(old),
        "new": len(new_ids),
        "gone": len(gone_ids),
        "new_ids": new_ids,
        "matched": sum(1 for r in old.values() if "exam" in r),
        "unmatched": sum(1 for r in old.values() if "exam" not in r and "ambiguous" not in r),
        "ambiguous": sum(1 for r in old.values() if "ambiguous" in r),
    }


_CHANGE_KEYS = ("id", "body", "feed", "title", "url", "doc_type", "exam", "cycle", "published")


def _change_view(r: dict) -> dict:
    return {k: r[k] for k in _CHANGE_KEYS if r.get(k)}


def append_changes(changes: list[dict], directory: Path = HARVEST_DIR) -> None:
    """The change log: ``changes/YYYY-MM.jsonl``, append-only, one line per
    notice that appeared, left its feed, or came back. This is what
    subscribers and the notifier read; it is never rewritten, so its git
    history is the audit trail."""
    if not changes:
        return
    month = changes[0]["at"][:7]
    path = directory / "changes" / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    order = {"new": 0, "back": 1, "gone": 2}
    with path.open("a", encoding="utf-8") as fh:
        for c in sorted(changes, key=lambda c: (order[c["change"]], c.get("exam", "~"), c["id"])):
            fh.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")


ATOM_ENTRIES = 300


def write_atom(notices: Iterable[dict], directory: Path = HARVEST_DIR) -> None:
    """``feed.atom``: the newest matched notices, for any feed reader.

    Deterministic: entries are ordered by (first_seen, id) and the feed's
    ``updated`` is the newest entry's first_seen, so the file is
    byte-identical until a new notice is matched."""
    from xml.sax.saxutils import escape

    live = [r for r in notices if r.get("exam") and "gone_since" not in r]
    live.sort(key=lambda r: (r["first_seen"], r["id"]), reverse=True)
    live = live[:ATOM_ENTRIES]
    updated = live[0]["first_seen"] if live else "1970-01-01T00:00:00+05:30"
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<feed xmlns="http://www.w3.org/2005/Atom">',
           "  <title>ExamHub: new official exam notices</title>",
           "  <id>urn:examhub:notices</id>",
           f"  <updated>{updated}</updated>"]
    for r in live:
        cat = f"{r['exam']} · {r.get('doc_type', 'other')}"
        out += ["  <entry>",
                f"    <id>urn:sha256:{r['id']}</id>",
                f"    <title>{escape(r['title'][:300])}</title>",
                f'    <link href="{escape(r["url"], {chr(34): "&quot;"})}"/>',
                f"    <updated>{r['first_seen']}</updated>",
                f'    <category term="{escape(r["exam"])}"/>',
                f"    <summary>{escape(cat)}{' · ' + r['cycle'] if r.get('cycle') else ''}</summary>",
                "  </entry>"]
    out.append("</feed>")
    (directory / "feed.atom").write_text("\n".join(out) + "\n", encoding="utf-8")


#: Poll cadence. A feed is hot while its body is in season -- it produced a
#: new notice recently -- and cools off by itself. No maintainer upkeep; a
#: catalogue ``tier`` overrides it for feeds that must always be hot.
HOT_DAYS, WARM_DAYS = 21, 120


def feed_tiers(cat: Catalogue, directory: Path = HARVEST_DIR, today: datetime | None = None) -> dict[str, str]:
    today = today or datetime.now(IST)
    rows = read_jsonl(directory / "notices.jsonl")
    # The first crawl of a feed "discovers" its whole backlog at once; that
    # says nothing about the season. Activity is a published date, or a
    # first_seen later than the feed's first crawl.
    boot: dict[str, str] = {}
    for r in rows:
        f = r.get("feed")
        if f and (f not in boot or r["first_seen"] < boot[f]):
            boot[f] = r["first_seen"]
    latest: dict[str, str] = {}
    for r in rows:
        f = r.get("feed")
        if not f:
            continue
        for ts in (r.get("published") and f"{r['published']}T00:00:00+05:30",
                   r["first_seen"] if r["first_seen"][:10] > boot[f][:10] else None):
            if ts and ts[:10] <= today.date().isoformat() and ts > latest.get(f, ""):
                latest[f] = ts
    tiers = {}
    for fid, f in cat.feeds.items():
        if f.get("tier"):
            tiers[fid] = f["tier"]
            continue
        seen = latest.get(fid)
        if not seen:
            tiers[fid] = "cold"
            continue
        age = (today - datetime.fromisoformat(seen)).days
        tiers[fid] = "hot" if age <= HOT_DAYS else "warm" if age <= WARM_DAYS else "cold"
    return tiers


def _hours_between(a: str, b: str) -> float:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    except ValueError:
        return 0.0


def write_health(results: list[dict], directory: Path = HARVEST_DIR) -> list[dict]:
    """Replace this run's feeds in ``feed-health.jsonl`` and flag regressions:
    a feed that used to yield links and now yields none has probably been
    redesigned, and that is the one thing a maintainer must hear about."""
    path = directory / "feed-health.jsonl"
    old = {r["id"]: r for r in read_jsonl(path)}
    alerts = []
    for r in results:
        prev = old.get(r["id"])
        checked = r.pop("checked")
        if r.pop("not_modified", False) and prev:
            # A 304 is the feed saying "same as last time".
            r = {**prev, **{k: v for k, v in r.items() if k in ("etag", "last_modified")}}
            old[r["id"]] = r
            continue
        # `since` moves only when the feed's state changes, so a healthy
        # feed's line is stable across runs.
        state = (r.get("ok"), r.get("status"), bool(r.get("count")))
        if prev and (prev.get("ok"), prev.get("status"), bool(prev.get("count"))) == state:
            r["since"] = prev.get("since", checked)
        else:
            r["since"] = checked
        # Two alerts, and only these: a page that answers but has lost its
        # notices (a redesign: fix the selector), and a page that has been
        # failing for a day (moved or dead). A single timeout is weather.
        if r.get("ok") and not r.get("count") and prev and (prev.get("count") or 0) > 0:
            r["alert"] = "yield dropped to zero"
            alerts.append(r)
        elif r.get("ok") and not r.get("count") and prev and prev.get("alert") == "yield dropped to zero":
            r["alert"] = prev["alert"]
        elif not r.get("ok") and _hours_between(r["since"], checked) >= 24:
            r["alert"] = "failing for a day"
            if not (prev and prev.get("alert") == r["alert"]):
                alerts.append(r)
        old[r["id"]] = r
    write_jsonl(path, old.values())
    return alerts
