"""Write what the PDFs said into the exam records, when it is safe to.

``documents build`` merges every exam's notices into a profile
(``data/harvest/exams/<exam>.json``), but nothing carried those into the
records. This does, under rules the data forced: measured on the harvest, most
profile values belong to another cycle (a 2017 exam date on a 2026 record) or
come from garbled text, so a value is written only when

* the profile's cycle year is the record's cycle year,
* the date is within a year of that cycle (an application for a 2027 exam may
  open in 2026),
* the record's own value is a sentinel -- a real value is never overwritten,
* vacancies come from a table whose category columns add up to its total (the
  table reader has misread a column before: 705 against columns summing to
  2,059) and the exam has one record that cycle (a series split into posts, or
  UGC NET into subjects, shares no single total),
* the value carries its source page, kept in ``provenance.evidence``.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from . import record as record_mod
from .crawl.harvest import HARVEST_DIR, read_jsonl

#: A date may sit this many years from the cycle's year.
YEAR_SLACK = 1
SENTINELS = {"unknown", "not_announced", "none", None}
#: Reservations that overlap the main categories rather than add to them.
HORIZONTAL = {"PwBD", "ESM", "Freedom Fighter Dependant"}
#: Reservation columns that cut across the main categories (PwBD-A, Ex-Servicemen, Disabled Ex-Servicemen):
#: their people are already counted under a main category, so they never add to the total.
_HORIZONTAL_NAME = re.compile(r"^(?:PwBD|PwD|PH\b|Ex-?\s*Servicem[ae]n|Disabled|ESM|Freedom|Women|Sports)", re.I)
#: Relaxation categories safe to copy as read; the reader has mislabelled the rest
#: (a widows-only relaxation came out as "Women").
RELAXATION_CATEGORIES = {"SC", "ST", "OBC-NCL", "OBC", "EWS", "PwBD", "Ex-Servicemen"}


def _adds_up(value: dict) -> bool:
    """Whether the vacancy table's category columns sum to its total."""
    cats = value.get("by_category") or {}
    if cats:
        return sum(n for k, n in cats.items() if k not in HORIZONTAL and not _HORIZONTAL_NAME.match(k) and isinstance(n, int)) == value["total"]
    # a table by zone or post (RRB) has no category columns: its rows must add up instead
    rows = [r.get("total") for r in value.get("rows") or []]
    return bool(rows) and all(isinstance(n, int) for n in rows) and sum(rows) == value["total"]


def _year(label: Any) -> int | None:
    text = str(label or "")[:4]
    return int(text) if text.isdigit() else None


def _day(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_date(value: Any) -> bool:
    return isinstance(value, dt.date) and not isinstance(value, dt.datetime)


def load_profiles(directory: Path = HARVEST_DIR) -> dict[str, dict]:
    import json

    out: dict[str, dict] = {}
    for path in sorted((directory / "exams").glob("*.json")):
        try:
            out[path.stem] = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
    return out


def _evidence(rec: dict, field: str, source: dict, words: str) -> None:
    record_mod.add_evidence(rec, field=field, url=source.get("url") or "", words=words,
                            method="rule", page=int(source.get("page") or 0), tier="notification_pdf")


def _exam_window(rec: dict) -> tuple[dict, str] | None:
    win, path = record_mod._window_for(rec, "stage:exam")
    return (win, path) if win is not None else None


def fill_record(rec: dict, profile: dict, *, same_cycle_records: int) -> list[str]:
    """Fill one record from its exam's profile. Returns what was written."""
    cycle = _year(rec.get("cycle"))
    if cycle is None or _year(profile.get("cycle")) != cycle:
        return []
    fields = profile.get("fields") or {}
    dates = fields.get("dates") or {}
    notes: list[str] = []

    def plausible(day: dt.date | None) -> bool:
        return day is not None and abs(day.year - cycle) <= YEAR_SLACK

    # application window: each end on its own, only where the record has none
    app = (rec.get("dates") or {}).get("application") or {}
    for field, end, key in (("registration_open", "from", "date"), ("registration_deadline", "to", None)):
        got = dates.get(field)
        if field == "registration_deadline" and not got and (dates.get("registration_open") or {}).get("until"):
            # a notice that gives the window as one row ("7 Oct to 5 Nov") has no separate deadline
            opened = dates["registration_open"]
            got = {"date": opened["until"], "source": opened.get("source"), "provisional": opened.get("provisional")}
        if not got:
            continue
        day = _day(got.get("date") if key else (got.get("until") or got.get("date")))
        if not plausible(day) or _is_date(app.get(end)):
            continue
        path = record_mod.set_date(rec, field, day, provisional=bool(got.get("provisional")))
        if path:
            _evidence(rec, path, got.get("source") or {}, f"{field.replace('_', ' ')} {day.isoformat()}")
            notes.append(f"{path} = {day.isoformat()}")

    # exam date: the first day only, since the profile does not know the last
    got = dates.get("exam_date")
    day = _day((got or {}).get("date"))
    if got and plausible(day):
        held = _exam_window(rec)
        if held and not _is_date(held[0].get("from")):
            win, path = held
            win["from"] = day
            win.setdefault("to", "unknown")
            win["status"] = "tentative" if got.get("provisional") else "confirmed"
            ordered = {k: win[k] for k in record_mod.template.WINDOW_KEYS if k in win}
            win.clear()
            win.update(ordered)
            _evidence(rec, f"{path}.from", got.get("source") or {}, f"exam date {day.isoformat()}")
            notes.append(f"{path}.from = {day.isoformat()}")

    # vacancies: a table's total, for an exam with one record this cycle
    vac = fields.get("vacancies")
    posts = rec.get("posts") or {}
    # a corrigendum's table may list only the posts it changes, so it never sets a total
    from_corrigendum = "corrigendum" in str((vac or {}).get("source", {}).get("title", "")).lower()
    if (vac and not from_corrigendum and same_cycle_records == 1 and (vac.get("value") or {}).get("from") == "table"
            and isinstance(vac["value"].get("total"), int) and _adds_up(vac["value"]) and posts.get("vacancies_total") in SENTINELS):
        record_mod.set_value(rec, "vacancies", str(vac["value"]["total"]))
        _evidence(rec, "posts.vacancies_total", vac.get("source") or {}, vac["value"].get("evidence") or "")
        notes.append(f"posts.vacancies_total = {vac['value']['total']}")

    notes += _fill_age(rec, fields.get("age"), dates.get("age_as_on"), cycle)

    if notes:
        record_mod.touch(rec)
    return notes


#: Notice kinds worth listing on the page as the cycle's documents.
LISTED_DOC_TYPES = {"notification", "corrigendum", "press_release", "schedule", "calendar"}


#: Most useful first: the notice itself, then changes to it, then the rest.
_DOC_RANK = {"notification": 0, "brochure": 0, "corrigendum": 1, "schedule": 2, "calendar": 2,
             "press_release": 3, "admit_card": 4}


def _short_title(title: str) -> str:
    """A listing title built as 'EXAM NAME - Document name' keeps only the document's name."""
    head, sep, tail = title.partition(" - ")
    title = tail if sep and len(head) > 30 else title
    title = re.sub(r"\s*\bRead\s*More\s*$", "", " ".join(title.split()), flags=re.I)
    if len(title) > 110:  # cut at a word, not in the middle of one
        title = title[:110].rsplit(" ", 1)[0].rstrip(",;:-– ") + "…"
    return title


def _date_in_title(day: dt.date | None, title: str) -> bool:
    """Whether the title itself prints the date ("... Exam 26th July, 2026"): that is the
    event's date, not the day the file was published."""
    if day is None:
        return False
    month = day.strftime("%B")
    return bool(re.search(rf"(?<!\d){day.day}(?:st|nd|rd|th)?\W+(?:{month}|{month[:3]})\b", title, re.I))


def _titled(title: str) -> str:
    """The short title, or nothing when it says nothing ('2026', 'Notice')."""
    short = _short_title(title)
    return short if re.search(r"[A-Za-z]{4}", short) else ""


def _file_title(url: str) -> str:
    """A title from the file's own name when no notice gave one: 'Detailed-Notification_CRP-PO-XVI.pdf'
    -> 'Detailed Notification CRP PO XVI'. Names that are only a number or a stamp give nothing."""
    if not re.search(r"\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)", url, re.I):
        return ""  # a portal or a page is not a file with a name of its own
    stem = unquote(url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", stem)
    words = re.sub(r"[-_+\s]+", " ", stem).strip()
    return words if len(re.findall(r"[A-Za-z]{4,}", words)) >= 1 and not re.fullmatch(r"[\d\W_]*(?:notice|doc|file)?[\d\W_]*", words, re.I) else ""


def order_documents(docs: list[dict]) -> None:
    """Notifications, then corrigenda, schedules, press releases, admit cards, the rest;
    newest first within a kind, a document with no date after those with one."""
    docs.sort(key=lambda d: (_DOC_RANK.get(d.get("document_type"), 9),
                             -(_day(d.get("document_published")) or dt.date.min).toordinal(),
                             str(d.get("document_title") or d.get("document_url"))))


#: Most documents of one kind a page lists: a press release a week would bury the notification.
DOC_CAPS = {"notification": 6, "corrigendum": 6, "schedule": 3, "calendar": 3, "press_release": 3}


def cap_documents(docs: list[dict]) -> None:
    """Keep the first few of each kind (call after order_documents), dropping repeats of one title."""
    seen: dict[str, int] = {}
    titles: set[tuple] = set()
    keep = []
    for d in docs:
        kind = d.get("document_type")
        key = (kind, str(d.get("document_title") or "").lower())
        if d.get("document_title") and key in titles:
            continue
        titles.add(key)
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] <= DOC_CAPS.get(kind, 99):
            keep.append(d)
    docs[:] = keep


def attach_notices(rec: dict, notices: list[dict], *, same_cycle_records: int) -> list[str]:
    """List the exam's matched notice PDFs for this cycle as the record's documents.

    A notice counts when it is a file of a listed kind, still online, and names the
    cycle's year in its title or address; an exam with several records in one cycle
    (a series split into posts) cannot say which record a notice belongs to."""
    year = _year(rec.get("cycle"))
    exam = rec.get("exam_id")
    can_add = not (year is None or same_cycle_records != 1 or exam in SENTINELS)
    links = rec.get("links")
    if not isinstance(links, dict) or not isinstance(links.get("documents"), list):
        return []
    docs = links["documents"]
    have = {d.get("document_url") for d in docs}
    snapshot = [dict(d) for d in docs]
    added = []
    for n in notices if can_add else ():
        url = n.get("url") or ""
        if (n.get("exam") != exam or n.get("gone_since") or n.get("doc_type") not in LISTED_DOC_TYPES
                or not url.lower().endswith(".pdf") or url in have
                or not re.search(rf"(?<!\d){year}(?!\d)", f"{n.get('title', '')} {url}")):
            continue
        # a date the pipeline guessed from the title (an exam date in "to be held on ...") is no publication date
        published = _day(n.get("published"))
        if n.get("published_from") or _date_in_title(published, n.get("title") or ""):
            published = None
        title = _titled(n.get("title") or "")
        docs.append({"document_type": n["doc_type"], "document_stage": "all",
                     "document_published": published or "unknown",
                     **({"document_title": title} if title else {}),
                     "document_url": url, "document_archive": "not_archived"})
        added.append(url)
    by_url = {n.get("url"): n for n in notices}
    for d in docs:  # every listed document is titled: by its notice, else by its file name
        n = by_url.get(d.get("document_url"))
        title = (_titled(n.get("title") or "") if n else "") or _file_title(d.get("document_url") or "")
        if title:
            d["document_title"] = title  # derived, so it follows the rule as it improves
        else:
            d.pop("document_title", None)
        if n and d.get("document_published") == _day(n.get("published")) and (
                n.get("published_from") or _date_in_title(_day(n.get("published")), n.get("title") or "")):
            d["document_published"] = "unknown"  # an earlier run took a date out of the title
    order_documents(docs)
    cap_documents(docs)  # a document the cap drops is not added again on the next run
    links["documents"] = docs
    kept = {d.get("document_url") for d in docs}
    notes = [f"links.documents += {u.rsplit('/', 1)[-1]}" for u in added if u in kept]
    if not notes and docs != snapshot:
        notes.append("links.documents ordered")
    return notes


def _fill_age(rec: dict, age: dict | None, as_on: dict | None, cycle: int) -> list[str]:
    """One age band (min, max, reference date) and its plain relaxations, into a
    record whose age rule is still unknown. Several bands (by post) are left alone."""
    value = (age or {}).get("value") or {}
    limits = value.get("limits") or []
    rows = rec.get("eligibility") if isinstance(rec.get("eligibility"), list) else []
    if len(limits) != 1 or len(rows) != 1 or not isinstance(rows[0].get("age"), dict):
        return []
    lim, rule = limits[0], rows[0]["age"]
    day = _day(value.get("as_on") or (as_on or {}).get("date"))
    ok = all(isinstance(lim.get(k), int) for k in ("min", "max")) and 14 <= lim["min"] < lim["max"] <= 70
    if (not ok or day is None or abs(day.year - cycle) > YEAR_SLACK
            or any(rule.get(k) not in SENTINELS for k in ("age_min", "age_max", "age_as_of"))):
        return []
    source = (age or {}).get("source") or {}
    rule.update(applies="yes", age_as_of=day, age_min=lim["min"], age_max=lim["max"])
    relax = [{"relaxation_category": c, "relaxation": f"+{r['years']}"}
             for r in value.get("relaxations") or [] if isinstance(r.get("years"), int) and len(r.get("categories") or []) == 1
             for c in r["categories"] if c in RELAXATION_CATEGORIES]
    if relax and rule.get("relaxations") in SENTINELS:
        rule["relaxations"] = relax
    _evidence(rec, "eligibility.age", {**source, "page": lim.get("page") or source.get("page")}, lim.get("evidence") or "")
    return [f"eligibility.age = {lim['min']}-{lim['max']} as on {day.isoformat()}"]


def fill(exams_dir: Path, *, apply: bool = False, directory: Path = HARVEST_DIR,
         log: Callable[[str], None] = print) -> int:
    """Fill every record the profiles can fill. Returns how many records changed."""
    profiles = load_profiles(directory)
    notices = read_jsonl(directory / "notices.jsonl")
    loaded: list[tuple[Path, dict, str]] = []
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, body = record_mod.load(path)
        except (OSError, ValueError) as exc:
            log(f"fill: {path.name}: skipped, unreadable ({exc})")
            continue
        loaded.append((path, rec, body))
    per_cycle: dict[tuple[str, int | None], int] = {}
    for _, rec, _ in loaded:
        key = (rec.get("exam_id"), _year(rec.get("cycle")))
        per_cycle[key] = per_cycle.get(key, 0) + 1
    log(f"fill: {len(profiles)} profiles, {len(loaded)} records")
    changed = 0
    for path, rec, body in loaded:
        profile = profiles.get(rec.get("exam_id"))
        count = per_cycle[(rec.get("exam_id"), _year(rec.get("cycle")))]
        notes = fill_record(rec, profile, same_cycle_records=count) if profile else []
        notes += attach_notices(rec, notices, same_cycle_records=count)
        if notes:
            record_mod.touch(rec)
        if notes:
            changed += 1
            log(f"fill: {path.name}: {'; '.join(notes)}")
            if apply:
                path.write_text(record_mod.dumps(rec, body), encoding="utf-8")
    log(f"fill: {changed} record(s) {'filled' if apply else 'to fill (dry run)'}")
    return changed
