"""Which conducting bodies are worth re-checking tonight.

The nightly recheck has a request budget -- it cannot afford to walk every
seed source every night. This looks at the exam records already on the site,
finds the soonest date each one has coming up (an application closing, an
exam sitting, a result due), and picks the sources behind the records whose
next date falls soon. An exam closing tomorrow is worth checking tonight; one
whose next date is eight months off is not.

A source with nothing due is still worth a look occasionally -- a notice can
change outside its listed dates -- so a slow rotation fills in the rest.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable

from . import catalogue as catalogue_mod
from . import record
from .sources import SEED_SOURCES

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
EXAMS_DIR = Path(__file__).resolve().parents[2] / "site" / "content" / "exams"


def _dates_in(obj: object) -> Iterable[dt.date]:
    """Every actual date tomllib parsed out of a ``dates`` block, recursively.

    A sentinel ("unknown", "not_announced") is a string, never a ``date``, so
    it is never mistaken for a real one.
    """
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _dates_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _dates_in(v)
    elif isinstance(obj, dt.date) and not isinstance(obj, dt.datetime):
        yield obj


def nearest_date(rec: dict, today: dt.date) -> dt.date | None:
    """The soonest date in the record's ``dates`` block that has not passed."""
    upcoming = [d for d in _dates_in(rec.get("dates", {})) if d >= today]
    return min(upcoming) if upcoming else None


def due_bodies(exams_dir: Path = EXAMS_DIR, within_days: int = 5,
               today: dt.date | None = None) -> dict[str, dt.date]:
    """Conducting-body id -> its soonest due date, for records due within the window."""
    today = today or dt.datetime.now(IST).date()
    horizon = today + dt.timedelta(days=within_days)
    due: dict[str, dt.date] = {}
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, _ = record.load(path)
        except (OSError, ValueError) as exc:
            record.log.warning("priority: could not read %s: %s", path, exc)
            continue
        nd = nearest_date(rec, today)
        if nd is None or nd > horizon:
            continue
        for b in rec.get("bodies") or []:
            code = b.get("body") if isinstance(b, dict) else None
            if not code or code in ("unknown", "none"):
                continue
            if code not in due or nd < due[code]:
                due[code] = nd
    return due


def due_sources(exams_dir: Path = EXAMS_DIR, within_days: int = 5,
                 today: dt.date | None = None,
                 catalogue_dir: Path = catalogue_mod.CATALOGUE_DIR) -> list[str]:
    """Seed source keys worth checking tonight, soonest due date first.

    A seed source names the body it watches by its ExamHub taxonomy name
    (``Source.taxonomy``), which is the catalogue body's ``short_name`` --
    "IBPS", not "in-ibps" or "Institute of Banking Personnel Selection".
    """
    due = due_bodies(exams_dir, within_days, today)
    if not due:
        return []
    cat = catalogue_mod.load(catalogue_dir)
    by_short_name: dict[str, dt.date] = {}
    for code, date in due.items():
        body = cat.bodies.get(code)
        if not body:
            continue
        name = (body.get("short_name") or "").lower()
        if name and (name not in by_short_name or date < by_short_name[name]):
            by_short_name[name] = date
    hits = [
        (by_short_name[name], source.key)
        for source in SEED_SOURCES
        if (name := (source.taxonomy or source.name or "").lower()) in by_short_name
    ]
    hits.sort()
    return [key for _, key in hits]


def rotation_source(today: dt.date | None = None) -> str:
    """One source, picked deterministically by the day, so every source gets
    an occasional look even with nothing due."""
    today = today or dt.datetime.now(IST).date()
    ordered = sorted(SEED_SOURCES, key=lambda s: s.key)
    return ordered[today.toordinal() % len(ordered)].key


def tonight_sources(exams_dir: Path = EXAMS_DIR, within_days: int = 5, cap: int = 5,
                     today: dt.date | None = None, *, rotation: bool = True) -> list[str]:
    """What a recheck run should pass as ``--source``: due sources first,
    capped to fit the request budget.

    ``rotation=True`` (the once-a-day run) tops up with the day's rotation
    pick, so a source with nothing due still gets an occasional look. The
    hourly run passes ``rotation=False``: with nothing urgently due, it
    should do nothing at all, not spend a run on routine coverage.
    """
    today = today or dt.datetime.now(IST).date()
    picked = list(dict.fromkeys(due_sources(exams_dir, within_days, today)))[:cap]
    if rotation and len(picked) < cap:
        rot = rotation_source(today)
        if rot not in picked:
            picked.append(rot)
    return picked
