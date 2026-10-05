"""The official page is the exam's page, the apply link is where candidates apply, and
the documents are its files: each link placed by what it is, not by what its address looks like.

What each link is comes from ``scrapy crawl links`` (``data/harvest/link-check.jsonl``,
see crawl/linkcheck.py): a file, a portal (a login or application form), or a page,
with the page's title and text and its own "Apply Online" links. Then, per record:

* a file is a document, never the official page or the apply link;
* the apply link is a portal: one of the record's links, or one its pages link to
  for applying. With none, a page that offers an apply link may stand in; with no
  such page either, it is ``unknown`` (no link beats a wrong one);
* the official page is the page that names the exam (its title, short name or other
  names), preferring a specific page to the site's front page; with none, the page
  already there if it works, else the conducting body's website;
* every other link is kept as a document. Nothing is dropped except a repeat.

A link not checked yet is judged only by one fact of its address: a ``.pdf`` is a file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod
from . import record as record_mod
from .crawl.adapters import classify_doc_type
from .crawl.harvest import HARVEST_DIR, read_jsonl

#: the one fact an address gives away: a file extension
FILE = re.compile(r"\.(pdf|docx?|xlsx?|zip|jpe?g|png)(?:$|[?#&])", re.I)
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(-\d{2,4})?(?!\d)")


def load_checks(directory: Path = HARVEST_DIR) -> dict[str, dict]:
    return {r["id"]: r for r in read_jsonl(directory / "link-check.jsonl")}


def official_page(rec: dict, cat) -> str | None:
    """The catalogue's page for this exam, else the conducting body's website."""
    exam = cat.exams.get(rec.get("exam_id") or "") or {}
    if exam.get("official_url"):
        return exam["official_url"]
    for b in rec.get("bodies") or []:
        if isinstance(b, dict) and b.get("body_role") == "conducts":
            site = (cat.bodies.get(b.get("body")) or {}).get("website")
            if site:
                return site
    return None


def names(rec: dict, cat) -> list[str]:
    """What the exam is called: its short name, other names and official name, without the year."""
    exam = cat.exams.get(rec.get("exam_id") or "") or {}
    raw = [rec.get("title"), rec.get("title_official"), exam.get("short_name"), exam.get("name"),
           *(rec.get("title_aliases") if isinstance(rec.get("title_aliases"), list) else [])]
    out: list[str] = []
    for n in raw:
        n = " ".join(_YEAR.sub(" ", re.sub(r"[(),:—–-]", " ", str(n or ""))).split())
        if len(n) >= 3 and n.lower() not in (x.lower() for x in out):
            out.append(n)
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 4}


def names_exam(info: dict, called: list[str]) -> bool:
    """A page names the exam when it has one of its names as a phrase, or most (two
    thirds) of the words of its longest name, however they are ordered."""
    hay = " ".join(f"{info.get('title', '')} {info.get('text', '')}".lower().split())
    if any(re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", hay) for n in called):
        return True
    longest = _words(max(called, key=len)) if called else set()
    return len(longest) >= 3 and len(longest & _words(hay)) >= 2 * len(longest) / 3


def kind(url: str, checks: dict[str, dict]) -> str:
    """file · portal · page · broken (gone) · unknown (not checked, or no answer)."""
    info = checks.get(url)
    if FILE.search(url) and (not info or info.get("state") != "ok"):
        return "file"
    if not info:
        return "unknown"
    if info.get("state") in ("not_found", "soft_404"):
        return "broken"
    if info.get("state") != "ok":
        return "unknown"  # blocked, timed out, server error: can't tell, so no change
    return info.get("kind", "unknown")


def fix(rec: dict, cat, checks: dict[str, dict] | None = None) -> list[str]:
    """Place the record's links; returns what changed (empty when nothing did)."""
    checks = checks or {}
    links = rec.setdefault("links", {})
    docs = links.setdefault("documents", [])
    official, apply = links.get("link_official_page"), links.get("link_apply")
    official = official if isinstance(official, str) and official.startswith("http") else None
    apply = apply if isinstance(apply, str) and apply.startswith("http") else None
    urls = [u for u in [official, apply, *(d.get("document_url") for d in docs)]
            if isinstance(u, str) and u.startswith("http")]
    urls = list(dict.fromkeys(urls))
    called = names(rec, cat)
    notes: list[str] = []

    # the apply link: a portal among the links, or one a page links to for applying
    offered = [t for u in urls for t in (checks.get(u) or {}).get("apply_links") or []]
    portals = list(dict.fromkeys(u for u in [*urls, *offered] if kind(u, checks) == "portal"))
    new_apply = apply
    if portals:
        new_apply = apply if apply in portals else portals[0]
    elif apply and kind(apply, checks) in ("file", "broken"):
        new_apply = None
    elif apply and kind(apply, checks) == "page" and not checks[apply].get("apply_links"):
        new_apply = None  # a page with no way to apply on it

    # the official page: a page that names the exam, a specific one before the front page
    named = [u for u in urls if kind(u, checks) == "page" and names_exam(checks[u], called)]
    named.sort(key=lambda u: (bool(checks[u].get("home")), u != official))
    if named:
        new_official = named[0]
    elif official and kind(official, checks) in ("page", "unknown"):
        new_official = official
    elif checks or (official and kind(official, checks) == "file"):
        # A file as the official page is always wrong, so it is replaced even unchecked.
        new_official = official_page(rec, cat) or official
    else:
        # No link checks and the page is not a file: the catalogue's page is a guess, so keep it.
        new_official = official

    # every link not placed stays, as a document
    for u in urls:
        if u in (new_official, new_apply) or any(d.get("document_url") == u for d in docs):
            continue
        dtype = classify_doc_type((checks.get(u) or {}).get("title", ""), u)
        if dtype == "other" and kind(u, checks) == "file":
            dtype = "notification"  # ExamHub's own source for the cycle, which was its notification
        docs.append({"document_type": dtype, "document_stage": "all", "document_published": "unknown",
                     "document_url": u, "document_archive": "not_archived"})
        notes.append(f"{u} kept as a document")
    before = len(docs)
    docs[:] = [d for d in docs if d.get("document_url") not in (new_official, new_apply)]
    if len(docs) < before:
        notes.append("a link no longer repeated as a document")
    if new_official and new_official != links.get("link_official_page"):
        notes.append(f"official page {links.get('link_official_page')} -> {new_official}")
        links["link_official_page"] = new_official
    # a sentinel already there ('none': no online application) says more than 'unknown'
    if not new_apply and not apply:
        new_apply = links.get("link_apply")
    if (new_apply or "unknown") != links.get("link_apply"):
        notes.append(f"apply link {links.get('link_apply')} -> {new_apply or 'unknown'}")
        links["link_apply"] = new_apply or "unknown"
    return notes


def fill(exams_dir: Path, *, apply: bool = False, directory: Path = HARVEST_DIR,
         log: Callable[[str], None] = print) -> int:
    """Place the links of every record. Returns how many changed."""
    cat = catalogue_mod.load()
    checks = load_checks(directory)
    log(f"links: {len(checks)} checked links known")
    changed = 0
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, body = record_mod.load(path)
        except (OSError, ValueError) as exc:
            log(f"links: {path.name}: skipped, unreadable ({exc})")
            continue
        notes = fix(rec, cat, checks)
        if notes:
            changed += 1
            log(f"links: {path.name}: {'; '.join(notes)}")
            if apply:
                path.write_text(record_mod.dumps(rec, body), encoding="utf-8")
    log(f"links: {changed} record(s) {'fixed' if apply else 'to fix (dry run)'}")
    return changed
