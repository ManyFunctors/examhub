"""Give a catalogue exam its page once a live cycle shows up in the harvest.

A tracked exam (see ``tracked``) stays a stub until something makes a real
page. Its profile may already hold a cycle whose notices were read -- AIAPGET
2026 had application dates, an exam date and 18 documents and still showed as
"nothing published yet". This writes a blank record for such an exam; the
steps after it (``fill-profiles``, ``links``) fill it, and ``tracked`` drops
the stub because the exam now has a page.

Live means the profile's cycle has a date (application end or exam day) no
older than ``RECENT_DAYS``, so a long-finished cycle is not resurrected.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod
from . import record as record_mod
from . import tracked as tracked_mod
from .crawl.harvest import HARVEST_DIR

RECENT_DAYS = 120

#: Only a recurring, named exam is one page per cycle. A body's rolling recruitment
#: ("HC Staff", "Direct Recruitment") is a new drive with every notice, so a page
#: for it would mix unrelated advertisements.
RECURRING = {"annual", "biannual", "quarterly", "monthly"}


def eligible(exam: dict) -> bool:
    return exam.get("frequency") in RECURRING and "umbrella" not in str(exam.get("name", ""))


def _last_date(profile: dict) -> dt.date | None:
    fields = profile.get("fields") or {}
    found = [(fields.get("exam_date") or {}).get("value"), ((fields.get("apply") or {}).get("value") or {}).get("until")]
    days = []
    for value in found:
        try:
            days.append(dt.date.fromisoformat(str(value)))
        except ValueError:
            pass
    return max(days) if days else None


def live(profile: dict, today: dt.date) -> bool:
    last = _last_date(profile)
    return bool(profile.get("documents_in_cycle")) and last is not None and (today - last).days <= RECENT_DAYS


def prune(exams_dir: Path, cat, *, apply: bool, log: Callable[[str], None]) -> int:
    """Remove pages this step made for a rolling recruitment (recognised by the bare title
    it gives them: the exam's short name and the year)."""
    gone = 0
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, _ = record_mod.load(path)
        except (OSError, ValueError):
            continue
        exam = cat.exams.get(str(rec.get("exam_id")))
        if exam is None or eligible(exam):
            continue
        short = exam.get("short_name") or exam.get("name") or ""
        if rec.get("title") == f"{short} {rec.get('cycle')}" and rec.get("title_series") == "unknown":
            gone += 1
            log(f"promote: {'removing' if apply else 'would remove'} {path.name} (a rolling recruitment is not one exam)")
            if apply:
                path.unlink()
    return gone


def fill(exams_dir: Path = tracked_mod.EXAMS_DIR, *, directory: Path = HARVEST_DIR, apply: bool = False,
         today: dt.date | None = None, log: Callable[[str], None] = print) -> int:
    """Write a blank record per tracked exam with a live cycle. Returns how many."""
    today = today or dt.date.today()
    cat = catalogue_mod.load()
    wanted = tracked_mod.candidates(cat, exams_dir)
    slugs = tracked_mod.slugs_for(wanted)
    made = 0
    for eid in wanted:
        path = directory / "exams" / f"{eid}.json"
        if not path.exists():
            continue
        profile = json.loads(path.read_text(encoding="utf-8"))
        year = str(profile.get("cycle") or "")[:4]
        if not year.isdigit() or not live(profile, today):
            continue
        exam = cat.exams[eid]
        if not eligible(exam):
            continue
        short = exam.get("short_name") or exam.get("name") or eid
        slug = f"{slugs[eid]}-{year}"
        target = exams_dir / f"{slug}.md"
        if target.exists():
            continue
        made += 1
        log(f"promote: {'writing' if apply else 'would write'} {target.name} ({short} {year})")
        if apply:
            rec = record_mod.skeleton(title=f"{short} {year}", slug=slug, body=exam.get("conducted_by") or "unknown",
                                      exam_id=eid, cycle=year)
            target.write_text(record_mod.dumps(rec, ""), encoding="utf-8")
    removed = prune(exams_dir, cat, apply=apply, log=log)
    log(f"promote: {made} exam(s) {'given a page' if apply else 'would be given a page (dry run)'}, {removed} page(s) removed")
    return made + removed
