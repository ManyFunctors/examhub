"""Keep the README's stats table from going stale.

Those five numbers (exam pages, catalogue size, notices seen) are a
point-in-time snapshot, and nothing updated them after they were first
written. This regenerates the table between the ``stats:start`` /
``stats:end`` markers from the catalogue and the site, so the README
stays honest without anyone remembering to edit it by hand.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import catalogue as catalogue_mod
from .crawl.harvest import HARVEST_DIR, read_jsonl

README = Path(__file__).resolve().parents[2] / "README.md"
EXAMS_DIR = Path(__file__).resolve().parents[2] / "site" / "content" / "exams"
_MARKERS = re.compile(r"(<!-- stats:start -->\n).*?(\n<!-- stats:end -->)", re.S)


def _round_down(n: int, step: int = 1000) -> int:
    return (n // step) * step


def table(exams_dir: Path = EXAMS_DIR, directory: Path = HARVEST_DIR) -> str:
    cat = catalogue_mod.load()
    stats = cat.stats()
    pages = len(list(exams_dir.glob("*.md")))
    notices_path = directory / "notices.jsonl"
    notices = sum(1 for _ in read_jsonl(notices_path)) if notices_path.exists() else 0
    rows = [
        ("Exam pages", f"{pages:,}"),
        ("Exams in the catalogue", f"{stats['exams']:,}"),
        ("Conducting bodies", f"{stats['bodies']:,}"),
        ("Feeds crawled daily", f"{stats['feeds']:,}"),
        ("Notices seen so far", f"{_round_down(notices):,}+" if notices else "0"),
    ]
    lines = ["| | |", "|---|---|", *(f"| {label} | {value} |" for label, value in rows)]
    return "\n".join(lines)


def fill(readme: Path = README, *, apply: bool = False, exams_dir: Path = EXAMS_DIR,
         directory: Path = HARVEST_DIR, log: Callable[[str], None] = print) -> int:
    """Replace the stats table. Returns 1 if it changed, 0 if not."""
    text = readme.read_text(encoding="utf-8")
    if not _MARKERS.search(text):
        log("readme_stats: no stats:start/stats:end markers found; nothing to do")
        return 0
    new_table = table(exams_dir, directory)
    new_text = _MARKERS.sub(lambda m: m.group(1) + new_table + m.group(2), text, count=1)
    if new_text == text:
        log("readme_stats: unchanged")
        return 0
    log("readme_stats: the table changed")
    if apply:
        readme.write_text(new_text, encoding="utf-8")
    return 1
