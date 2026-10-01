"""Exam records in the site's format (docs/exam-template.md).

Load and write the TOML front matter, start a record for a new exam, put a
verified value at its place in the record, and flatten a record for diffing.
Records are plain dicts in template order; convert.emit writes them.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from . import template
from .convert import emit

log = logging.getLogger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

#: Section headings written above each top-level block.
HEADINGS = {
    "section": "identity (pipeline)", "title": "titles (readers)",
    "purpose": "who runs it, what it is", "bodies": "who runs it",
    "posts": "posts and vacancies", "pay": "pay", "service": "terms of service",
    "dates": "dates and stages", "eligibility": "eligibility", "fee": "fee",
    "exam_rules": "exam-wide rules", "links": "links",
    "provenance": "provenance (never shown)",
}

#: Validator field -> where it goes. Stage fields go to the first written stage,
#: the result to the last stage.
DATE_FIELDS = {
    "registration_open": ("application", "from"),
    "registration_deadline": ("application", "to"),
    "payment_deadline": ("fee_payment", "to"),
    "admit_card_from": ("stage:admit_card", "from"),
    "admit_card_to": ("stage:admit_card", "to"),
    "exam_date": ("stage:exam", "both"),
    "result_date": ("last:result", "both"),
}

#: Validator fields with no structured place in the template; they are logged, not written.
TEXT_FIELDS = {"fee", "negative_marking", "duration", "venue", "eligibility"}

#: Fetch tier -> links.documents document_type.
TIER_DOCUMENT = {"notification_pdf": "notification", "corrigendum": "corrigendum",
                 "press_release": "press_release", "official_portal": "other", "other": "other"}


# --------------------------------------------------------------------------
# read / write
# --------------------------------------------------------------------------

FENCE = "+++"


def split_front_matter(text: str) -> tuple[str, str]:
    """``(front matter, page body)``; a missing or unclosed +++ fence is an error."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != FENCE:
        raise ValueError("page does not open with a +++ front matter fence")
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    raise ValueError("front matter fence is never closed")


def parse(text: str) -> tuple[dict, str]:
    """Front matter as a dict, and the page body."""
    front, body = split_front_matter(text)
    return tomllib.loads(front), body


def load(path: Path) -> tuple[dict, str]:
    return parse(Path(path).read_text(encoding="utf-8"))


def dumps(rec: dict, body: str = "") -> str:
    text = emit.dump(rec, HEADINGS)
    return text + (body if body.startswith("\n") or not body else "\n" + body)


# --------------------------------------------------------------------------
# a new exam
# --------------------------------------------------------------------------

def _window(status: str = "not_announced") -> dict:
    return {"status": status, "change": "none", "changed_from": "none"}


def _blank(value: Any) -> Any:
    """The template's example with every fact replaced by 'unknown'."""
    if isinstance(value, dict):
        if template.is_window(value):
            return _window()
        if template.is_open_map(value):
            return "unknown"
        return {k: _blank(v) for k, v in value.items()}
    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        return [_blank(value[0])]
    return "unknown"


def skeleton(*, title: str, slug: str, body: str, exam_id: str = "unknown",
             cycle: str = "unknown") -> dict:
    """A record for an exam the site does not have yet: every fact 'unknown'."""
    rec = _blank(tomllib.loads(template.template_text()))
    rec.update({"section": "exams", "exam_id": exam_id, "cycle": cycle, "cycle_status": "active",
                "title": title, "slug": slug, "title_official": title,
                "title_series": "unknown", "title_aliases": "none"})
    rec["bodies"] = [{"body": body or "unknown", "body_role": "conducts"}]
    # rows nobody has read yet are empty lists; the site loops over them
    rec["posts"] = {**rec["posts"], "list": [], "groups": "none"}
    rec["pay"] = []
    rec["fee"]["rows"] = []
    stage = rec["dates"]["stages"][0]
    stage.update({"stage_name": "Examination", "stage_number": 1, "stage_format": "written",
                  "stage_posts": "all", "stage_conditions": "none", "stage_parts": "unknown"})
    rec["dates"]["stages"] = [stage]
    rec["links"]["documents"] = []
    rec["provenance"]["evidence"] = []
    return rec


# --------------------------------------------------------------------------
# updating
# --------------------------------------------------------------------------

def _first_written(stages: list[dict]) -> dict | None:
    for s in stages:
        if s.get("stage_format") == "written":
            return s
    return stages[0] if stages else None


def _window_for(rec: dict, where: str) -> tuple[dict, str] | tuple[None, str]:
    """The window a validator field writes into, and its record path."""
    dates = rec.setdefault("dates", {})
    if ":" not in where:
        return dates.setdefault(where, _window()), f"dates.{where}"
    pick, key = where.split(":")
    stages = dates.get("stages") if isinstance(dates.get("stages"), list) else []
    stage = _first_written(stages) if pick == "stage" else (stages[-1] if stages else None)
    if stage is None:
        return None, ""
    n = stage.get("stage_number", stages.index(stage) + 1)
    return stage.setdefault(key, _window()), f"dates.stages[{n}].{key}"


def set_date(rec: dict, field: str, day: dt.date, *, provisional: bool) -> str | None:
    """Put one verified date in place. Returns the record path, or None."""
    if field not in DATE_FIELDS:
        return None
    where, end = DATE_FIELDS[field]
    win, path = _window_for(rec, where)
    if win is None:
        log.warning("no stage to hold %s; record left unchanged", field)
        return None
    ends = ("from", "to") if end == "both" else (end,)
    for e in ends:
        win[e] = day
    # a window keeps both ends; an end nobody has stated is 'unknown'
    for e in ("from", "to"):
        win.setdefault(e, "unknown")
    win["status"] = "tentative" if provisional else "confirmed"
    # keep key order: from, to, status, change, changed_from
    ordered = {k: win[k] for k in template.WINDOW_KEYS if k in win}
    win.clear()
    win.update(ordered)
    # fee payment opens with the application when the notice gives only its end
    if field == "payment_deadline" and win.get("from") == "unknown":
        app_from = rec["dates"].get("application", {}).get("from")
        if isinstance(app_from, dt.date):
            win["from"] = app_from
    return f"{path}.{end}" if end != "both" else path


def set_value(rec: dict, field: str, value: str, *, provisional: bool = False) -> str | None:
    """Put one verified validator value in place. Returns the record path, or None."""
    if field in DATE_FIELDS:
        try:
            day = dt.date.fromisoformat(value)
        except ValueError:
            log.warning("%s: %r is not a date; skipped", field, value)
            return None
        return set_date(rec, field, day, provisional=provisional)
    if field == "vacancies":
        try:
            rec.setdefault("posts", {})["vacancies_total"] = int(value)
        except (TypeError, ValueError):
            log.warning("vacancies: %r is not a number; skipped", value)
            return None
        rec["posts"]["vacancies_status"] = "tentative" if provisional else "confirmed"
        return "posts.vacancies_total"
    if field == "age_as_on":
        try:
            day = dt.date.fromisoformat(value)
        except ValueError:
            return None
        rows = rec.get("eligibility") if isinstance(rec.get("eligibility"), list) else []
        for row in rows:
            if isinstance(row.get("age"), dict):
                row["age"]["age_as_of"] = day
        return "eligibility.age.age_as_of" if rows else None
    if field == "mode":
        mode = _mode(value)
        stage = _first_written(rec.get("dates", {}).get("stages") or [])
        if mode and stage is not None:
            stage["stage_mode"] = mode
            return f"dates.stages[{stage.get('stage_number', 1)}].stage_mode"
        return None
    if field in TEXT_FIELDS:
        log.info("%s has no structured place in the template; not written", field)
    return None


def path_of(rec: dict, field: str) -> str | None:
    """The record path a validator field would write to, without writing it."""
    if field in DATE_FIELDS:
        where, end = DATE_FIELDS[field]
        _, path = _window_for(copy.deepcopy(rec), where)
        return (path if end == "both" else f"{path}.{end}") if path else None
    if field == "vacancies":
        return "posts.vacancies_total"
    if field == "age_as_on":
        return "eligibility.age.age_as_of"
    if field == "mode":
        stage = _first_written(rec.get("dates", {}).get("stages") or [])
        return f"dates.stages[{stage.get('stage_number', 1)}].stage_mode" if stage else None
    return None


def _mode(text: str) -> str | None:
    t = text.lower()
    if re.search(r"computer|cbt|online", t):
        return "cbt"
    if "omr" in t:
        return "omr"
    if re.search(r"offline|pen|paper", t):
        return "pen_paper"
    return None


def add_evidence(rec: dict, *, field: str, url: str, words: str, method: str = "model",
                 page: int = 0, tier: str = "other", published: Any = "unknown") -> None:
    """Record where a value came from, and list the document it came from."""
    links = rec.setdefault("links", {})
    docs = links.get("documents") if isinstance(links.get("documents"), list) else []
    if url and not any(d.get("document_url") == url for d in docs):
        docs.append({"document_type": TIER_DOCUMENT.get(tier, "other"), "document_stage": "all",
                     "document_published": published, "document_url": url,
                     "document_archive": "not_archived"})
    links["documents"] = docs
    prov = rec.setdefault("provenance", {})
    rows = prov.get("evidence") if isinstance(prov.get("evidence"), list) else []
    rows = [r for r in rows if r.get("evidence_field") != field]  # the newest source wins
    rows.append({"evidence_field": field, "evidence_document": url, "evidence_page": page,
                 "evidence_words": (words or "")[:300], "evidence_method": method})
    prov["evidence"] = rows


def touch(rec: dict, now: dt.datetime | None = None) -> None:
    """Mark the record checked now (and retrieved, the first time)."""
    now = (now or dt.datetime.now(IST)).replace(microsecond=0)
    prov = rec.setdefault("provenance", {})
    if not isinstance(prov.get("provenance_retrieved"), dt.datetime):
        prov["provenance_retrieved"] = now
    prov["provenance_last_checked"] = now
    # retrieved and last_checked lead the block
    rest = {k: v for k, v in prov.items() if k not in ("provenance_retrieved", "provenance_last_checked")}
    rec["provenance"] = {"provenance_retrieved": prov["provenance_retrieved"],
                         "provenance_last_checked": now, **rest}


def copy_of(rec: dict) -> dict:
    return copy.deepcopy(rec)


# --------------------------------------------------------------------------
# diffing
# --------------------------------------------------------------------------

def _text(v: Any) -> str:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return ", ".join(_text(x) for x in v)
    return str(v)


def flatten(rec: dict) -> dict[str, str]:
    """Every fact as 'path' -> text; a window reads 'from – to (status)'."""
    out: dict[str, str] = {}

    def walk(v: Any, path: str) -> None:
        if isinstance(v, dict):
            if template.is_window(v):
                span = _text(v.get("from", "")) + (f" – {_text(v['to'])}" if v.get("to") not in (None, v.get("from")) else "")
                out[path] = f"{span} ({v['status']})".strip() if span else v["status"]
                if v.get("change") not in (None, "none"):
                    out[f"{path}.change"] = f"{v['change']} from {_text(v.get('changed_from'))}"
                return
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else k)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for i, x in enumerate(v, start=1):
                n = x.get("stage_number", i) if isinstance(x, dict) else i
                walk(x, f"{path}[{n}]")
        else:
            out[path] = _text(v)

    walk(rec, "")
    return out
