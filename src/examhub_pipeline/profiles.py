"""Per-exam profiles: the best value for each field, from every document read.

A notice's PDF answers some questions and not others. A one-line date
notice has an exam date and nothing else; the advertisement has the
vacancy table, the fee and the age limit; a corrigendum moves a date. The
profile merges every structured document of an exam into one record, a
field at a time, by a fixed rule, and lists the fields still missing. Those
**gaps** steer the next run's fetching (see :func:`ingest.select`), so each
run spends its budget where it fills the most.

The rule, per field:

1. **Current cycle only for what changes each cycle.** Dates, vacancies and
   fees are taken only from documents of the exam's newest cycle. A 2024
   fee is not this year's fee, and must never fill this year's gap.
2. **Stable facts may carry over.** Education level, selection stages, exam
   pattern and pay change rarely; when the current cycle has none, the
   newest earlier value is used and marked ``carried_from``.
3. **Among candidates:** a table beats prose, a text layer beats OCR, an
   advertisement or brochure beats a corrigendum beats anything else for
   the terms, and for dates the newest document wins (that is what a
   corrigendum is for).

Every value keeps its source: the notice id, the PDF URL and the page.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .catalogue import Catalogue

SCHEMA_VERSION = 1

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

#: Fields a candidate needs, by exam purpose. A field outside the list is
#: still merged when found; it just is not a gap when missing.
EXPECTED: dict[str, tuple[str, ...]] = {
    "recruitment": ("vacancies", "apply", "exam_date", "fee", "age", "pay", "eligibility", "selection"),
    "departmental": ("vacancies", "apply", "exam_date", "eligibility"),
    "admission": ("apply", "exam_date", "fee", "eligibility", "exam_pattern"),
    "eligibility": ("apply", "exam_date", "fee", "eligibility", "exam_pattern"),
    "scholarship": ("apply", "exam_date", "eligibility"),
    "certification": ("apply", "exam_date", "fee", "eligibility"),
    # A board exam has a timetable, not an application window.
    "school_board": ("exam_date",),
}
_DEFAULT_EXPECTED = ("apply", "exam_date")

#: Fields that may be carried over from an earlier cycle.
STABLE = ("eligibility", "selection", "exam_pattern", "pay")

_KIND_RANK = {"advertisement": 3, "brochure": 3, "corrigendum": 2}


def cycle_key(label: str | None) -> tuple[int, int]:
    """'2026-mar' -> (2026, 3); '2025' -> (2025, 0); unknown -> (0, 0)."""
    if not label:
        return (0, 0)
    m = re.search(r"(20\d\d)(?:-([a-z]{3}))?", label)
    if not m:
        return (0, 0)
    return (int(m.group(1)), _MONTHS.get(m.group(2) or "", 0))


def _doc_cycle(record: dict, cycles: dict[str, str]) -> tuple[int, int]:
    notice = record.get("notice", {})
    key = cycle_key((cycles.get(notice.get("id", "")) or "").split("/")[-1])
    if key != (0, 0):
        return key
    # No cycle in the title: the year the notice speaks from.
    for value in (notice.get("published"), *(d.get("date") for d in record.get("dates", {}).values())):
        if value:
            return (int(str(value)[:4]), 0)
    return (0, 0)


def _when(record: dict) -> str:
    n = record.get("notice", {})
    return str(n.get("published") or record.get("document", {}).get("fetched") or "")


def _source(record: dict, page: Any = None) -> dict[str, Any]:
    n = record.get("notice", {})
    out = {"notice": n.get("id"), "url": n.get("url"), "title": n.get("title"), "kind": record.get("kind")}
    if page is not None:
        out["page"] = page
    if record.get("document", {}).get("ocr"):
        out["ocr"] = True
    return out


def _term_rank(record: dict, from_table: bool) -> tuple:
    return (
        _KIND_RANK.get(record.get("kind", ""), 1),
        1 if from_table else 0,
        0 if record.get("document", {}).get("ocr") else 1,
        _when(record),
    )


def _pick(cands: list[tuple[tuple, Any, dict]]) -> tuple[Any, dict, int] | None:
    if not cands:
        return None
    cands.sort(key=lambda c: c[0], reverse=True)
    _, value, source = cands[0]
    return value, source, len(cands)


def build_profile(exam: dict, records: list[dict], cycles: dict[str, str]) -> dict[str, Any]:
    """Merge one exam's document records into its profile."""
    by_cycle: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in records:
        by_cycle[_doc_cycle(r, cycles)].append(r)
    current_key = max(by_cycle) if by_cycle else (0, 0)
    current = by_cycle.get(current_key, [])
    older = [r for k in sorted(by_cycle, reverse=True) if k != current_key for r in by_cycle[k]]

    fields: dict[str, dict[str, Any]] = {}

    def put(name: str, picked, carried: tuple[int, int] | None = None) -> None:
        if not picked:
            return
        value, source, alternatives = picked
        entry = {"value": value, "source": source}
        if alternatives > 1:
            entry["alternatives"] = alternatives - 1
        if carried:
            entry["carried_from"] = f"{carried[0]}" + (f"-{carried[1]:02d}" if carried[1] else "")
        fields[name] = entry

    # -- per-cycle fields
    put("vacancies", _pick([
        (_term_rank(r, r["vacancies"].get("from") == "table"), r["vacancies"], _source(r, r["vacancies"].get("page")))
        for r in current if r.get("vacancies", {}).get("total")
    ]))
    put("fee", _pick([
        (_term_rank(r, "for" in json.dumps(r["fees"]) or len(r["fees"]) > 1), r["fees"], _source(r, r["fees"][0].get("page")))
        for r in current if r.get("fees")
    ]))
    put("age", _pick([
        (_term_rank(r, False), r["age"], _source(r, (r["age"].get("limits") or [{}])[0].get("page")))
        for r in current if (r.get("age") or {}).get("limits")
    ]))
    dates: dict[str, Any] = {}
    for key in sorted({k for r in current for k in r.get("dates", {})}):
        picked = _pick([
            ((_when(r), 1 if r["dates"][key].get("from") == "table" else 0,
              0 if r.get("document", {}).get("ocr") else 1),
             {k: v for k, v in r["dates"][key].items() if k in ("date", "until", "provisional")},
             _source(r, r["dates"][key].get("page")))
            for r in current if key in r.get("dates", {})
        ])
        if picked:
            value, source, alternatives = picked
            dates[key] = {**value, "source": source, **({"alternatives": alternatives - 1} if alternatives > 1 else {})}
    if dates:
        fields["dates"] = dates
    if "registration_open" in dates or "registration_deadline" in dates:
        fields["apply"] = {"value": {
            "from": (dates.get("registration_open") or {}).get("date"),
            "until": (dates.get("registration_deadline") or {}).get("until")
            or (dates.get("registration_deadline") or {}).get("date"),
        }, "source": (dates.get("registration_deadline") or dates.get("registration_open"))["source"]}
    if "exam_date" in dates:
        fields["exam_date"] = {"value": dates["exam_date"]["date"], "source": dates["exam_date"]["source"]}
    advt = _pick([(_term_rank(r, True), r["advertisement_no"], _source(r)) for r in current if r.get("advertisement_no")])
    put("advertisement_no", advt)
    links = _pick([(_term_rank(r, True), r["links"]["apply"], _source(r)) for r in current if (r.get("links") or {}).get("apply")])
    put("apply_links", links)

    # -- stable fields: current cycle, else the newest earlier one
    for name, getter in (
        ("eligibility", lambda r: r.get("eligibility") if (r.get("eligibility") or {}).get("clauses") else None),
        ("selection", lambda r: r.get("selection") or None),
        ("exam_pattern", lambda r: r.get("exam_pattern") or None),
        ("pay", lambda r: r.get("pay") or None),
    ):
        picked = _pick([(_term_rank(r, name == "exam_pattern"), getter(r), _source(r)) for r in current if getter(r)])
        if picked:
            put(name, picked)
            continue
        for k in sorted(by_cycle, reverse=True):
            if k == current_key:
                continue
            picked = _pick([(_term_rank(r, False), getter(r), _source(r)) for r in by_cycle[k] if getter(r)])
            if picked:
                put(name, picked, carried=k)
                break

    expected = EXPECTED.get(exam.get("purpose", ""), _DEFAULT_EXPECTED)
    gaps = [f for f in expected if f not in fields]
    return {
        "schema": SCHEMA_VERSION,
        "exam": exam["id"],
        "name": exam.get("name"),
        "body": exam.get("conducted_by"),
        "purpose": exam.get("purpose"),
        "cycle": (f"{current_key[0]}" + (f"-{current_key[1]:02d}" if current_key[1] else "")) if current_key[0] else None,
        "documents": len(records),
        "documents_in_cycle": len(current),
        "fields": fields,
        "gaps": gaps,
        "older_documents": len(older),
    }


def load_records(directory: Path) -> dict[str, list[dict]]:
    """Every ok document record, grouped by exam."""
    out: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((directory / "documents").glob("*/*.json")):
        try:
            record = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        exam = record.get("notice", {}).get("exam")
        if exam:
            out[exam].append(record)
    return out


def build_all(cat: Catalogue, directory: Path, notices: Iterable[dict]) -> dict[str, dict]:
    """A profile for every active exam; those with no documents are all gaps."""
    cycles = {n["id"]: n.get("cycle", "") for n in notices if n.get("exam")}
    records = load_records(directory)
    return {
        exam_id: build_profile(exam, records.get(exam_id, []), cycles)
        for exam_id, exam in sorted(cat.exams.items())
        if exam.get("status", "active") == "active"
    }


def write_all(profiles: dict[str, dict], directory: Path) -> dict[str, int]:
    """``exams/<id>.json`` for exams with documents, and ``exams/gaps.jsonl``."""
    out_dir = directory / "exams"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for exam_id, profile in profiles.items():
        if not profile["documents"]:
            continue
        path = out_dir / f"{exam_id}.json"
        text = json.dumps(profile, ensure_ascii=False, indent=1) + "\n"
        if not path.exists() or path.read_text("utf-8") != text:
            path.write_text(text, "utf-8")
        written += 1
    with (out_dir / "gaps.jsonl").open("w", encoding="utf-8") as fh:
        for exam_id, profile in profiles.items():
            fh.write(json.dumps({"id": exam_id, "documents": profile["documents"], "cycle": profile["cycle"],
                                 "gaps": profile["gaps"]}, ensure_ascii=False, sort_keys=True) + "\n")
    complete = sum(1 for p in profiles.values() if p["documents"] and not p["gaps"])
    return {"profiles": written, "complete": complete, "exams": len(profiles)}
