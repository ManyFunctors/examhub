"""Which notices get their PDF read, and where the structured records go.

    scrapy crawl documents                  # fetch: work/documents/*.pdf
    python -m examhub_pipeline documents build   # structure: data/harvest/documents/

Fetching and structuring are separate steps. The fetch is network-bound and
polite; the structuring is CPU-bound (OCR) and runs in a process pool with no
network, so it can be re-run and tested on its own.

Harvest layout::

    documents/index.jsonl          one line per notice tried: status + summary
    documents/<id[:2]>/<id>.json   the structured record
    documents/<id[:2]>/<id>.md     the same, rendered for people

The PDFs are not kept: they are the body's to host. A record carries the
PDF's sha256, so a changed PDF at the same URL is noticed on a re-fetch.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .. import documents
from ..config import Settings
from . import harvest

WORK_DIR = harvest.PROJECT_ROOT / "work" / "documents"

#: Notice types whose PDF is a list of roll numbers or marks, not terms.
SKIP_TYPES = {"result", "answer_key", "admit_card", "application_status"}
_SKIP_TITLE = re.compile(
    r"\bresult|answer\s*key|admit\s*card|hall\s*ticket|call\s*letter|merit\s+list|\bmarks\b|"
    r"roll\s*(?:no|number)|list\s+of|shortlist|selected|rejected|cut[\s-]?off|\bscore|"
    r"attendance|seating|interview\s+schedule|document\s+verification|selection\s+list|"
    r"provisional(?:ly)?\s+selected|wait(?:ing)?\s*list",
    re.I,
)
_PDF_URL = re.compile(r"\.pdf(?:$|[?#])", re.I)

#: New documents per exam per run, before gap-filling takes over.
FRESH_PER_EXAM = 2

#: Documents per host per run.
MAX_PER_HOST = 3

#: A failed fetch is tried again on later runs, at most this many times.
MAX_ATTEMPTS = 3
#: Only notices first seen this recently are fetched on a normal run; the
#: backlog is for an explicit backfill.
RECENT_DAYS = 45

#: OCR is ~3.5 s a page on a runner. A scanned advertisement's terms are in
#: its first pages; the rest is annexures and forms.
OCR_MAX_PAGES = 20


def record_path(notice_id: str, suffix: str, directory: Path = harvest.HARVEST_DIR) -> Path:
    return directory / "documents" / notice_id[:2] / f"{notice_id}{suffix}"


def load_gaps(directory: Path = harvest.HARVEST_DIR) -> dict[str, dict]:
    return {r["id"]: r for r in harvest.read_jsonl(directory / "exams" / "gaps.jsonl")}


def load_index(directory: Path = harvest.HARVEST_DIR) -> dict[str, dict]:
    return {r["id"]: r for r in harvest.read_jsonl(directory / "documents" / "index.jsonl")}


def wanted(notice: dict) -> bool:
    """A notice whose document is worth structuring."""
    if not notice.get("exam") or notice.get("gone_since"):
        return False
    if notice.get("doc_type") in SKIP_TYPES or _SKIP_TITLE.search(notice.get("title") or ""):
        return False
    return bool(_PDF_URL.search(notice.get("url", ""))) or notice.get("doc_type") == "notification"


def select(
    notices: Iterable[dict],
    index: dict[str, dict],
    *,
    limit: int,
    recent_days: int | None = RECENT_DAYS,
    today: datetime | None = None,
    ocr: bool = True,
    gaps: dict[str, dict] | None = None,
) -> list[dict]:
    """Newest wanted notices not yet done, then gap-filling, then redos.

    **Gap-filling** spends what the new notices leave of the budget on the
    exams whose profile is missing the most (``gaps``, from
    ``exams/gaps.jsonl``): for each, its newest untried document of any
    age, one exam at a time, round after round. Over successive runs every
    exam's backlog is read, the emptiest first, without any single run
    fetching more than its budget.

    Done means a record at the current schema, or a final status (not a
    PDF, too large), or too many failed attempts. A failure is retried at
    most once a day. A scan read without OCR (the fast loop has none) is
    redone by the first run that has it.
    """
    today = today or datetime.now(harvest.IST)
    cutoff = (today - timedelta(days=recent_days)).date().isoformat() if recent_days else ""
    yesterday = (today - timedelta(hours=20)).isoformat(timespec="seconds")
    fresh, redo = [], []
    backlog: dict[str, list[dict]] = defaultdict(list)
    for n in notices:
        if not wanted(n):
            continue
        seen = str(n.get("published") or n.get("first_seen") or "")[:10]
        done = index.get(n["id"])
        if done is None:
            if seen >= cutoff:
                fresh.append(n)
            else:
                backlog[n["exam"]].append(n)
            continue
        status = done.get("status")
        if status == "ok":
            if done.get("schema", 0) < documents.SCHEMA_VERSION:
                redo.append(n)
        elif (status == "needs_ocr" and ocr) or (
            status == "failed"
            and done.get("attempts", 0) < MAX_ATTEMPTS
            and done.get("tried", "") < yesterday
        ):
            fresh.append(n)
    key = lambda n: str(n.get("published") or n.get("first_seen") or "")  # noqa: E731
    fresh.sort(key=key, reverse=True)
    redo.sort(key=key, reverse=True)
    # A new feed's first crawl makes its whole archive look new. At most two
    # new documents per exam per run; the rest wait their turn as backlog.
    per_exam: dict[str, int] = defaultdict(int)
    kept = []
    for n in fresh:
        per_exam[n["exam"]] += 1
        (kept if per_exam[n["exam"]] <= FRESH_PER_EXAM else backlog[n["exam"]]).append(n)
    fresh = kept
    for queue in backlog.values():
        queue.sort(key=key, reverse=True)
    # Emptiest exams first: most gaps, then fewest documents already read.
    gaps = gaps or {}
    order = sorted(
        backlog,
        key=lambda e: (-len((gaps.get(e) or {}).get("gaps", ["?"] * 8)),
                       (gaps.get(e) or {}).get("documents", 0), e),
    )
    filling = []
    while any(backlog[e] for e in order):
        for exam in order:
            if backlog[exam]:
                filling.append(backlog[exam].pop(0))
    # A few per host per run: one slow host must not take the whole budget.
    per_host: dict[str, int] = {}
    out = []
    for n in fresh + filling + redo:
        host = urlsplit(n["url"]).hostname or ""
        if per_host.get(host, 0) >= MAX_PER_HOST:
            continue
        per_host[host] = per_host.get(host, 0) + 1
        out.append(n)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def _structure_one(pdf: str, notice: dict, fetched: str) -> dict:
    settings = Settings.from_env(ocr_max_pages=OCR_MAX_PAGES)
    with open(pdf, "rb") as fh:
        content = fh.read()
    return documents.structure(content, notice, settings, fetched=fetched)


def index_line(record: dict) -> dict:
    notice = record["notice"]
    doc = record["document"]
    # A scan read with OCR switched off has no text: say so, so a run with
    # OCR picks it up, instead of storing an empty record as done.
    needs_ocr = any("OCR is disabled" in w or "no OCR path" in w for w in record.get("warnings", []))
    return {
        "id": notice["id"],
        "status": "needs_ocr" if needs_ocr else "ok",
        "schema": record["schema"],
        "body": notice.get("body"),
        "exam": notice.get("exam"),
        "title": notice.get("title"),
        "url": notice.get("url"),
        "kind": record.get("kind"),
        "advertisement_no": record.get("advertisement_no"),
        "sha256": doc["sha256"],
        "pages": doc["pages"],
        "ocr": doc["ocr"],
        "summary": record.get("summary", {}),
        "tried": doc.get("fetched"),
    }


def build(
    work_dir: Path = WORK_DIR,
    directory: Path = harvest.HARVEST_DIR,
    *,
    jobs: int | None = None,
) -> dict[str, int]:
    """Structure every fetched PDF in ``work_dir`` and update the index.

    ``work_dir/fetched.jsonl`` is written by the spider: one line per
    notice it tried, with ``status`` and, when ok, the PDF's path.
    """
    index = load_index(directory)
    tried = harvest.read_jsonl(work_dir / "fetched.jsonl")
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    todo = []
    for row in tried:
        previous = index.get(row["id"], {})
        if row["status"] != "fetched":
            index[row["id"]] = {
                **{k: row["notice"].get(k) for k in ("id", "body", "exam", "title", "url")},
                "error": row.get("error"),
                "status": row["status"],
                "attempts": previous.get("attempts", 0) + 1,
                "tried": row["tried"],
            }
            counts["skipped" if row["status"] != "failed" else "failed"] += 1
            continue
        todo.append(row)

    jobs = jobs or max(1, min(4, os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(_structure_one, row["pdf"], row["notice"], row["tried"]): row
            for row in todo
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                record = future.result()
                write_record(record, directory)
            except Exception as exc:  # a broken PDF is one line, not a crash
                index[row["id"]] = {
                    **{k: row["notice"].get(k) for k in ("id", "body", "exam", "title", "url")},
                    "status": "failed",
                    "error": f"structure: {type(exc).__name__}: {exc}"[:300],
                    "attempts": index.get(row["id"], {}).get("attempts", 0) + 1,
                    "tried": row["tried"],
                }
                counts["failed"] += 1
                continue
            index[row["id"]] = index_line(record)
            counts["ok"] += 1

    harvest.write_jsonl(directory / "documents" / "index.jsonl", index.values())
    counts.update(refresh_profiles(directory))
    counts["unmapped_classes"] = write_unmapped(directory)
    # Consumed: a second build must not count the same failures twice.
    fetched = work_dir / "fetched.jsonl"
    if fetched.exists():
        fetched.replace(work_dir / "fetched-built.jsonl")
    return counts


def refresh_profiles(directory: Path = harvest.HARVEST_DIR) -> dict[str, int]:
    """Re-merge every exam's documents into ``exams/`` and its gap list."""
    from .. import catalogue, profiles

    notices = harvest.read_jsonl(directory / "notices.jsonl")
    return profiles.write_all(profiles.build_all(catalogue.load(), directory, notices), directory)


def write_unmapped(directory: Path = harvest.HARVEST_DIR) -> int:
    """``documents/unmapped-classes.jsonl``: class columns no vocabulary entry
    names, with how often and where they were seen. The maintainer's worklist
    for ``data/catalogue/reservation.toml``; most frequent first."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((directory / "documents").glob("*/*.json")):
        try:
            record = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        j = documents.jurisdiction_of(record.get("notice", {})) or ""
        for item in record.get("unmapped_classes", []):
            row = seen.setdefault((j, item["label"]), {"jurisdiction": j, "label": item["label"], "count": 0,
                                                      "examples": []})
            row["count"] += 1
            if len(row["examples"]) < 3:
                row["examples"].append({"notice": record["notice"].get("id"), "url": record["notice"].get("url"),
                                        "page": item.get("page")})
    rows = sorted(seen.values(), key=lambda r: (-r["count"], r["jurisdiction"], r["label"]))
    with (directory / "documents" / "unmapped-classes.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def write_record(record: dict, directory: Path = harvest.HARVEST_DIR) -> None:
    notice_id = record["notice"]["id"]
    path = record_path(notice_id, ".json", directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    record_path(notice_id, ".md", directory).write_text(documents.render_markdown(record), encoding="utf-8")


def summary_line(entry: dict[str, Any]) -> str:
    """One line for a notification: what the PDF says, not just its title."""
    s = entry.get("summary") or {}
    parts = []
    if s.get("vacancies"):
        parts.append(f"{s['vacancies']:,} posts")
    apply = s.get("apply") or {}
    if apply.get("until"):
        parts.append(f"apply by {apply['until']}")
    if s.get("exam_date"):
        parts.append(f"exam {s['exam_date']}")
    if s.get("fee"):
        fee = s["fee"]
        parts.append(f"fee ₹{fee['min']}" if fee["min"] == fee["max"] else f"fee ₹{fee['min']}–{fee['max']}")
    if s.get("age"):
        a = s["age"]
        parts.append(f"age {a.get('min') or '?'}–{a.get('max') or '?'}")
    if s.get("pay"):
        parts.append(s["pay"])
    return " · ".join(parts)
