"""List this run's new notices on the Actions run page.

    python -m examhub_pipeline.crawl.notify            # reads work/new-notices.jsonl
    python -m examhub_pipeline.crawl.notify --dry-run  # print them instead

Only notices matched to an exam are listed, plus feeds marked
``notify = "all"``; unmatched ones are the maintainer's worklist.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import harvest

WORK = harvest.PROJECT_ROOT / "work"

_DOC_LABEL = {
    "notification": "Notification", "corrigendum": "Corrigendum", "admit_card": "Admit card",
    "answer_key": "Answer key", "result": "Result", "calendar": "Calendar", "syllabus": "Syllabus",
    "schedule": "Schedule", "counselling": "Counselling", "walk_in": "Walk-in",
    "application_status": "Application status",
}


def _line(r: dict, cat_names: dict[str, str], bodies: dict[str, str]) -> tuple[str, str]:
    label = _DOC_LABEL.get(r.get("doc_type", ""), "Notice")
    who = cat_names.get(r["exam"], r["exam"]) if r.get("exam") else bodies.get(r["body"], r["body"])
    return f"{label}: {who}", r["title"][:400]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(WORK / "new-notices.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    from ..catalogue import load

    cat = load()
    names = {e["id"]: e.get("short_name") or e["name"] for e in cat.exams.values()}
    push_all = {fid for fid, f in cat.feeds.items() if f.get("notify") == "all"}
    rows = [r for r in harvest.read_jsonl(Path(a.input)) if r.get("exam") or r.get("feed") in push_all]
    for r in rows:
        # a feed with notify = "all" is listed under its body's name
        r.setdefault("exam", "")
    rows.sort(key=lambda r: (r["exam"], r["id"]))
    bodies = {b["id"]: b.get("short_name") or b["name"] for b in cat.bodies.values()}

    # When the PDF was read in this run, the line says what it says:
    # "500 posts · apply by 2026-10-02 · fee ₹100–850", not just a title.
    from .ingest import load_index, summary_line

    documents = load_index()

    if a.dry_run:
        for r in rows:
            title, text = _line(r, names, bodies)
            doc = documents.get(r["id"])
            if doc and doc.get("status") == "ok" and summary_line(doc):
                text = f"{text}\n{summary_line(doc)}"
            print(f"- {title}\n  {text}\n  {r['url']}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {len(rows)} new matched notice(s)\n\n")
            if rows:
                fh.write("| exam | type | notice |\n|---|---|---|\n")
                for r in rows[:200]:
                    t = r["title"][:140].replace("|", "/")
                    doc = documents.get(r["id"]) or {}
                    if doc.get("status") == "ok" and summary_line(doc):
                        t += f"<br>{summary_line(doc).replace('|', '/')}"
                    fh.write(f"| `{r['exam'] or r['body']}` | {r.get('doc_type', '')} | [{t}]({r['url']}) |\n")
            fh.write("\n")
    print(f"notify: {len(rows)} matched new notice(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
