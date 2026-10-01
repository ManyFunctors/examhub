"""Tracked exams: a catalogue exam that recurs but has no live cycle page.

A reader who searches for a known, recurring exam (AIAPGET, NExT) before its
next notice is out gets a hard "not found" today, which reads as "we don't
cover this" rather than the truth: it's in the catalogue, nothing has been
published yet. This writes a small stub page for exams named explicitly
(never scanned from the whole catalogue -- most catalogue entries with no
page are ones whose cycle has simply come and gone, per "nothing is
archived", and listing all of them would be noise, not help).

A stub carries no invented dates or figures: name, conducting body and its
official site, and how often the exam is held. It lives in its own `tracked`
section, never `site/content/exams/`, so it never touches the exam record
schema or lint. ``browse.html`` folds it into the "Dates to Be Announced"
group alongside real undated cycles.

A stub is removed the moment a real page for that exam id exists, since at
that point the catalogue entry has a true cycle to show instead.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMS_DIR = PROJECT_ROOT / "site" / "content" / "exams"
TRACKED_DIR = PROJECT_ROOT / "site" / "content" / "tracked"

_EXAM_ID_RE_CACHE: dict[Path, re.Pattern] = {}


def _has_page(exam_id: str, exams_dir: Path) -> bool:
    pat = re.compile(r"^exam_id\s*=\s*'" + re.escape(exam_id) + r"'", re.M)
    for p in exams_dir.glob("*.md"):
        if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
            return True
    return False


def _body(cat: catalogue_mod.Catalogue, body_id: str) -> dict:
    return cat.bodies.get(body_id, {})


FREQUENCY_WORDS = {
    "annual": "once a year",
    "biannual": "twice a year",
    "multiple": "several times a year",
    "continuous": "on a rolling basis",
    "irregular": "on no fixed schedule",
}


def render(exam_id: str, cat: catalogue_mod.Catalogue) -> str:
    """The stub file's content for one catalogue exam id."""
    exam = cat.exams[exam_id]
    name = exam.get("name") or exam.get("short_name") or exam_id
    short = exam.get("short_name") or name
    body_id = exam.get("conducted_by") or exam.get("owned_by") or ""
    body = _body(cat, body_id)
    body_name = body.get("short_name") or body.get("name") or "its conducting body"
    body_url = body.get("website") or ""
    freq = FREQUENCY_WORDS.get(exam.get("frequency", ""), "regularly")
    slug = exam_id.split("-", 1)[1] if "-" in exam_id else exam_id

    lines = [
        "+++",
        f"title = {short!r}".replace('"', "'"),
        f"slug = {slug!r}".replace('"', "'"),
        f"exam_id = {exam_id!r}".replace('"', "'"),
        f"name = {name!r}".replace('"', "'"),
        f"body_name = {body_name!r}".replace('"', "'"),
        f"body_url = {body_url!r}".replace('"', "'"),
        f"frequency = {exam.get('frequency', 'unknown')!r}".replace('"', "'"),
        "+++",
        "",
        f"**{name}** is conducted {freq} by {body_name}. No notice has been "
        "published yet for its next cycle, so there is nothing to show beyond "
        "this: ExamHub takes nothing from anywhere but the body's own notice.",
        "",
        f"[Check {body_name}'s official site]({body_url}) for an announcement." if body_url
        else f"{body_name} has not published an official site in the catalogue yet.",
    ]
    return "\n".join(lines) + "\n"


def fill(exam_ids: list[str], *, tracked_dir: Path = TRACKED_DIR, exams_dir: Path = EXAMS_DIR,
         apply: bool = False, log: Callable[[str], None] = print) -> int:
    """Write a stub for each requested exam id, and remove any existing stub whose exam now
    has a real page. Only ever touches files for ids this run names or that are stale --
    an id left off this run's ``--exam`` list is simply not this run's business.
    Returns the number of files changed.
    """
    cat = catalogue_mod.load()
    changed = 0

    for exam_id in exam_ids:
        if exam_id not in cat.exams:
            log(f"tracked: {exam_id}: not in the catalogue, skipped")
            continue
        if _has_page(exam_id, exams_dir):
            log(f"tracked: {exam_id}: already has a real page, no stub needed")
            continue
        slug = exam_id.split("-", 1)[1] if "-" in exam_id else exam_id
        path = tracked_dir / f"{slug}.md"
        text = render(exam_id, cat)
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        changed += 1
        log(f"tracked: {'writing' if apply else 'would write'} {path.relative_to(PROJECT_ROOT)}")
        if apply:
            tracked_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    # a stub whose exam now has a real page is stale, regardless of this run's --exam list
    if tracked_dir.exists():
        id_pat = re.compile(r"^exam_id\s*=\s*'([^']+)'", re.M)
        for path in tracked_dir.glob("*.md"):
            m = id_pat.search(path.read_text(encoding="utf-8", errors="ignore"))
            if m and _has_page(m.group(1), exams_dir):
                changed += 1
                log(f"tracked: {'removing' if apply else 'would remove'} "
                    f"{path.relative_to(PROJECT_ROOT)} (its exam now has a real page)")
                if apply:
                    path.unlink()

    return changed
