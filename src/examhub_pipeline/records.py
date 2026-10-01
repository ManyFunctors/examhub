"""Find the harvested notices that belong to an existing ExamHub record.

An old record points at one source (often a portal home page), which is
rarely the notification itself. The harvest has already listed every notice
on each body's pages, so the notices of a record are found there: same body
(or same host), title words in common, published recently.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

HARVEST = Path("data/harvest/notices.jsonl")
BODIES = Path("site/data/bodies.json")
OLD = Path("data/old-records")

STOP = set("""a an and the of for in on to by with from at or exam examination exams test
recruitment notice notification notifications advertisement advt no post posts online
application applications apply form last date official website pdf click here download
new regarding various vacancies vacancy cum under dated important public
""".split())
KIND_WEIGHT = {"notification": 3.0, "corrigendum": 1.5, "schedule": 1.5, "press_release": 1.0,
               "admit_card": 0.5, "answer_key": 0.3, "result": 0.5, "calendar": 0.8, "other": 0.6,
               "walk_in": 2.0, "syllabus": 0.8, "application_status": 0.3, "counselling": 0.5}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in STOP and len(w) > 1 and not re.fullmatch(r"20\d\d|\d{1,2}", w)}


def host(url: str | None) -> str:
    h = (urlsplit(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def site_key(url: str | None) -> str:
    """'host:exams.nta.nic.in/jipmat' for a site that lives under a path on a shared host,
    'host:ibps.in' for one that owns its host."""
    first = next((p for p in urlsplit(url or "").path.split("/") if p), "")
    return "host:" + host(url) + (f"/{first.lower()}" if first else "")


def load_record(path: Path) -> dict:
    d = tomllib.loads(path.read_text(encoding="utf-8").split("+++")[1])
    d["slug"] = path.stem
    return d


def load_records(site: Path = OLD) -> list[dict]:
    return [load_record(p) for p in sorted(site.glob("*.md"))]


@lru_cache
def notices() -> list[dict]:
    return [json.loads(line) for line in HARVEST.open(encoding="utf-8")]


@lru_cache
def _body_index() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for bid, b in json.loads(BODIES.read_text()).items():
        for name in (b.get("short_name"), b.get("name")):
            if name:
                out.setdefault(name.lower(), set()).add(bid)
        if b.get("website"):
            # a body whose site is one folder of a shared host (NTA's exams.nta.nic.in/jipmat/)
            # owns that folder, not the whole host
            out.setdefault(site_key(b["website"]), set()).add(bid)
    return out


@lru_cache
def _by_source() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n in notices():
        out.setdefault(n.get("body") or "", []).append(n)
        out.setdefault("host:" + host(n["url"]), []).append(n)
    return out


@lru_cache
def _idf() -> dict[str, float]:
    import math
    df: dict[str, int] = {}
    ns = notices()
    for n in ns:
        for w in words(n.get("title", "")):
            df[w] = df.get(w, 0) + 1
    return {w: math.log(len(ns) / c) for w, c in df.items()}


def body_ids(record: dict) -> set[str]:
    idx = _body_index()
    ids: set[str] = set()
    for b in record.get("bodies", []):
        ids |= idx.get(b.lower(), set())
    for url in (record["provenance"]["source_url"], record.get("official_url"), record.get("apply_url")):
        ids |= idx.get("host:" + host(url), set()) | idx.get(site_key(url), set())
    return ids


def years(record: dict) -> set[int]:
    text = " ".join([record["slug"], record.get("title", "")])
    return {int(y) for y in re.findall(r"20[23]\d", text)}


def match(record: dict, today: dt.date | None = None, limit: int = 6) -> list[dict]:
    """The harvested notices most likely to be about this record, best first."""
    today = today or dt.date.today()
    ids = body_ids(record)
    hosts = {host(u) for u in (record["provenance"]["source_url"], record.get("official_url")) if u}
    want = words(" ".join([record.get("title", ""), *record.get("known_as", [])]))
    # the slug carries a short code (ups-epfo-apfc) that titles often print
    want |= {w for w in record["slug"].split("-")[1:] if len(w) > 2 and not w.isdigit()}
    want -= words(" ".join(record.get("bodies", [])))  # the body's name is in every title
    ys = years(record)
    idf = _idf()
    mass = sum(idf.get(w, 8.0) for w in want) or 1.0
    scored = []
    pool = {id(n): n for k in [*ids, *("host:" + h for h in hosts)] for n in _by_source().get(k, [])}
    for n in pool.values():
        common = want & words(n.get("title", "") + " " + urlsplit(n["url"]).path)
        share = sum(idf.get(w, 8.0) for w in common) / mass
        # A notice that names another cycle's year is about another cycle.
        ny = {int(y) for y in re.findall(r"(?<!\d)20[123]\d(?!\d)", n.get("title", ""))}
        # (a recruitment advertised in one year is often examined the next)
        if ys and ny and not (ny & (ys | {y - 1 for y in ys})):
            continue
        if share < 0.45:
            continue
        score = share * 10 + KIND_WEIGHT.get(n.get("doc_type"), 0.5)
        pub = n.get("published")
        if pub:
            age = (today - dt.date.fromisoformat(pub[:10])).days
            score += 2.0 if age < 200 else 1.0 if age < 400 else -1.0 if age > 800 else 0
        if ys and any(str(y) in n.get("title", "") for y in ys):
            score += 1.5
        scored.append((round(score, 2), sorted(common), n))
    scored.sort(key=lambda s: -s[0])
    return [dict(n, score=s, common=c) for s, c, n in scored[:limit]]
