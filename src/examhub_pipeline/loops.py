"""Merge the work directories of the per-jurisdiction loops into one.

Each loop fetches its own feeds, so each has its own ``docs/`` (one file per
URL, so no two loops collide) and its own ``state/documents.jsonl`` ledger.
The aggregate job merges them so one review sees every loop's documents.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def merge_work(sources: list[Path], dest: Path) -> dict[str, int]:
    """Copy every loop's documents into ``dest`` and union their ledgers.

    A document file already in ``dest`` is kept as it is. Ledger lines are
    kept once each, in the order the loops are given."""
    docs_dest = dest / "docs"
    state_dest = dest / "state"
    docs_dest.mkdir(parents=True, exist_ok=True)
    state_dest.mkdir(parents=True, exist_ok=True)

    copied = skipped = 0
    seen: set[str] = set()
    ledger: list[str] = []
    for src in sources:
        for doc in sorted((src / "docs").glob("*")) if (src / "docs").is_dir() else []:
            target = docs_dest / doc.name
            if target.exists():
                skipped += 1
                continue
            shutil.copy2(doc, target)
            copied += 1
        ledger_path = src / "state" / "documents.jsonl"
        if ledger_path.is_file():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if line.strip() and line not in seen:
                    seen.add(line)
                    ledger.append(line)
    out = state_dest / "documents.jsonl"
    with out.open("a", encoding="utf-8") as fh:
        for line in ledger:
            json.loads(line)  # a corrupt ledger line should stop the merge, not spread
            fh.write(line + "\n")
    return {"docs_copied": copied, "docs_already_there": skipped, "ledger_lines": len(ledger)}
