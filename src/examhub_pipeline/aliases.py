"""Other names (``title_aliases``) that name a different kind of exam.

ExamHub's records mixed up the eligibility tests: "KTET" (the school Teacher
Eligibility Test) was listed as a name of KSET (the lecturers' State
Eligibility Test), and so on for Gujarat, Telangana, West Bengal and
Chhattisgarh. A search for one then finds the other.

An alias is dropped when it names one kind of eligibility test and the exam
is another kind. Only that: an alias shared with another exam ("NEET" on
NEET PG) is how people search, so it stays. Every drop is logged.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod
from . import record as record_mod

#: the eligibility tests, told apart by their last word: TET (school teachers),
#: SET (state lecturers), NET (national lecturers)
KINDS = {
    "tet": re.compile(r"TET\b|teacher\s+eligibility", re.I),
    "set": re.compile(r"(?<![A-Z])[A-Z]*SET\b|state\s+eligibility", re.I),
    "net": re.compile(r"(?<![A-Z])[A-Z]*NET\b|national\s+eligibility", re.I),
}


def kinds(text: str) -> set[str]:
    return {k for k, rx in KINDS.items() if rx.search(text or "")}


def wrong(rec: dict, cat) -> list[str]:
    """The aliases that name a different kind of eligibility test than the record's exam."""
    aliases = rec.get("title_aliases")
    if not isinstance(aliases, list):
        return []
    exam = cat.exams.get(rec.get("exam_id") or "") or {}
    own = kinds(f"{rec.get('title_official', '')} {exam.get('name', '')}")
    if len(own) != 1:
        return []
    return [a for a in aliases if kinds(a) and not kinds(a) & own]


def fill(exams_dir: Path, *, apply: bool = False, log: Callable[[str], None] = print) -> int:
    """Drop the wrong aliases everywhere. Returns how many records changed."""
    cat = catalogue_mod.load()
    changed = 0
    for path in sorted(exams_dir.glob("*.md")):
        try:
            rec, body = record_mod.load(path)
        except (OSError, ValueError) as exc:
            log(f"aliases: {path.name}: skipped, unreadable ({exc})")
            continue
        bad = wrong(rec, cat)
        if not bad:
            continue
        changed += 1
        log(f"aliases: {path.name}: dropped {', '.join(map(repr, bad))} (another kind of exam than {rec.get('title_official')!r})")
        if apply:
            rec["title_aliases"] = [a for a in rec["title_aliases"] if a not in bad] or "none"
            path.write_text(record_mod.dumps(rec, body), encoding="utf-8")
    log(f"aliases: {changed} record(s) {'fixed' if apply else 'to fix (dry run)'}")
    return changed
