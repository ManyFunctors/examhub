"""Tracked exams: a catalogue exam with no live cycle page.

A reader who searches for a known exam (AIAPGET, NExT) before its next
notice is out got a hard "not found", which reads as "we don't cover this"
rather than the truth: it's in the catalogue, nothing has been published
yet. This writes a small stub page for every active catalogue exam that has
no page in ``site/content/exams/`` -- automatically, on every run, no exam
picked out by hand.

A stub carries no invented dates or figures: name, conducting body and its
official site, and how often the exam is held. It lives in its own
``tracked`` section, never ``site/content/exams/``, so it never touches the
exam record schema or lint. ``browse.html`` folds it into the "Dates to Be
Announced" group alongside real undated cycles, built to look exactly like
one of those cards.

Regenerated wholesale each run, the same way ``readme-stats`` rewrites its
table: a stub disappears the moment its exam gets a real page or leaves the
catalogue (``status`` no longer ``active``), with no separate cleanup step.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMS_DIR = PROJECT_ROOT / "site" / "content" / "exams"
TRACKED_DIR = PROJECT_ROOT / "site" / "content" / "tracked"

_EXAM_ID_RE = re.compile(r"^exam_id\s*=\s*'([^']+)'", re.M)


def pages_by_exam_id(exams_dir: Path) -> set[str]:
    """Every catalogue exam id that already has a real page."""
    out: set[str] = set()
    for p in exams_dir.glob("*.md"):
        m = _EXAM_ID_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
        if m:
            out.add(m.group(1))
    return out


def candidates(cat: catalogue_mod.Catalogue, exams_dir: Path = EXAMS_DIR) -> list[str]:
    """Every active catalogue exam id with no real page, sorted."""
    have = pages_by_exam_id(exams_dir)
    return sorted(
        eid for eid, exam in cat.exams.items()
        if exam.get("status") == "active" and eid not in have
    )


def slugs_for(exam_ids: list[str]) -> dict[str, str]:
    """exam id -> filename stem, dropping the jurisdiction prefix only where that
    stays unique across this batch (two jurisdictions can share a short id,
    'ka-kpsc' and 'kl-kpsc', the same clash the catalogue itself calls out)."""
    bare = {eid: (eid.split("-", 1)[1] if "-" in eid else eid) for eid in exam_ids}
    counts: dict[str, int] = {}
    for b in bare.values():
        counts[b] = counts.get(b, 0) + 1
    return {eid: (b if counts[b] == 1 else eid) for eid, b in bare.items()}


FREQUENCY_WORDS = {
    "annual": "once a year",
    "biannual": "twice a year",
    "multiple": "several times a year",
    "continuous": "on a rolling basis",
    "irregular": "on no fixed schedule",
}


def render(exam_id: str, cat: catalogue_mod.Catalogue, slug: str) -> str:
    """The stub file's content for one catalogue exam id."""
    exam = cat.exams[exam_id]
    name = exam.get("name") or exam.get("short_name") or exam_id
    short = exam.get("short_name") or name
    body_id = exam.get("conducted_by") or exam.get("owned_by") or ""
    body = cat.bodies.get(body_id, {})
    body_name = body.get("short_name") or body.get("name") or "its conducting body"
    body_url = body.get("website") or ""
    freq = FREQUENCY_WORDS.get(exam.get("frequency", ""), "regularly")
    tv = catalogue_mod._toml_value  # a name or title can carry an apostrophe or a quote

    lines = [
        "+++",
        f"title = {tv(short)}",
        "section = 'tracked'",
        f"slug = {tv(slug)}",
        f"exam_id = {tv(exam_id)}",
        f"name = {tv(name)}",
        f"body_name = {tv(body_name)}",
        f"body_url = {tv(body_url)}",
        f"frequency = {tv(exam.get('frequency', 'unknown'))}",
        "+++",
        "",
        f"It is held {freq}.",
    ]
    return "\n".join(lines) + "\n"


def fill(*, tracked_dir: Path = TRACKED_DIR, exams_dir: Path = EXAMS_DIR,
         apply: bool = False, log: Callable[[str], None] = print) -> int:
    """Regenerate every stub from the catalogue. Returns the number of files changed."""
    cat = catalogue_mod.load()
    wanted = candidates(cat, exams_dir)
    slugs = slugs_for(wanted)
    changed = 0

    for exam_id in wanted:
        path = tracked_dir / f"{slugs[exam_id]}.md"
        text = render(exam_id, cat, slugs[exam_id])
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        changed += 1
        log(f"tracked: {'writing' if apply else 'would write'} {path.relative_to(PROJECT_ROOT)}")
        if apply:
            tracked_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if tracked_dir.exists():
        keep = {f"{s}.md" for s in slugs.values()}
        for path in tracked_dir.glob("*.md"):
            if path.name in keep:
                continue
            changed += 1
            log(f"tracked: {'removing' if apply else 'would remove'} "
                f"{path.relative_to(PROJECT_ROOT)} (its exam now has a real page, "
                "or left the catalogue)")
            if apply:
                path.unlink()

    log(f"tracked: {len(wanted)} exam(s) with no page, {changed} file(s) changed")
    return changed
