"""Notification PDFs -> structured, readable records.

A recruitment advertisement or an information brochure says the same dozen
things in a hundred layouts: how many posts, for whom, what they pay, who may
apply, what it costs, by when. This module reads those out deterministically,
with no model:

* **Tables first.** pymupdf's table finder recovers the vacancy matrix, the
  fee table, the age-relaxation table, the schedule and the exam pattern
  from text PDFs. A table is classified by its header row, never by its
  position.
* **Prose second.** :mod:`candidates` finds dates, pay and eligibility in
  clauses; the fee, age and selection readers below handle the phrasings
  that are not tables ("Rs. 850/- for all candidates except SC/ST ...").
* **Every value carries its page.** A reader checks a number against the
  PDF, not against this code. OCR'd documents say so at the top.

The output is a record (JSON) plus a Markdown rendering of it. Values that
could not be read are absent, not guessed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from . import candidates as cand
from . import reservation
from .config import Settings
from .extract import _pymupdf, pdf_pages

SCHEMA_VERSION = 2

#: Table detection is the slow part (~0.2 s a page). A brochure's tables that
#: matter are in its first pages; a 200-page list has nothing to structure.
MAX_TABLE_PAGES = 40

# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------

#: The jurisdiction of the notice being read. Reservation classes and their
#: abbreviations are scoped ("OSC" is an SC sub-group in Haryana and a
#: backward class in Jammu and Kashmir), so every reader below needs it.
#: Set once per document by :func:`structure`; a context variable rather than
#: a parameter because it is needed a dozen calls deep.
_JURISDICTION: ContextVar[str | None] = ContextVar("jurisdiction", default=None)


def categories_in(text: str) -> list[str]:
    """Every reservation class named in ``text``, first-seen order.

    "SC/ST/PwBD" -> ["SC", "ST", "PwBD"]. Spellings map to one class
    ("General", "UR" -> "Unreserved"); distinct classes are never merged. See
    ``data/catalogue/reservation.toml``.
    """
    return reservation.load().classes_in(text, _JURISDICTION.get())


def is_vertical(cls: str) -> bool:
    """A vertical class partitions the vacancies; horizontal ones cut across."""
    return reservation.load().is_vertical(cls)


_EXCEPT = re.compile(r"\b(?:other\s+than|except(?:ing)?|excluding|besides)\b", re.I)


def who(text: str) -> dict[str, Any]:
    """``{"categories": [...]}``, or ``{"categories": [...], "except": True}``.

    "All candidates other than SC/ST/PwBD" is everyone *but* those, and
    must never be read as those.
    """
    m = _EXCEPT.search(text)
    if m:
        cats = categories_in(text[m.end():])
        if cats:
            return {"categories": cats, "except": True}
    return {"categories": categories_in(text) or ["All candidates"]}


def category(label: str) -> str | None:
    """The single class a table header names, or None."""
    return reservation.load().one(label, _JURISDICTION.get())


def unmapped_headers(table: "Table") -> list[str]:
    """Header cells that look like a class column but name no known class.

    A short header over a column of counts ("BC-X", "SEBC-A") is almost
    certainly a reservation class the vocabulary does not have yet. These go
    to the worklist, so the vocabulary grows from what notices actually say.
    """
    out = []
    for i, head in enumerate(table.header):
        h = head.strip()
        if not h or len(h) > 14 or category(h) or _total_score(h) or _SERIAL.search(h):
            continue
        # Words the PDF's text layer broke apart ("VAC ANCY", "Tota l").
        if re.search(r"total|vacanc|posts?|seats?|remark|grand", h.replace(" ", ""), re.I):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.()/&\- ]*", h) or re.search(r"\b(?:posts?|name|sl|no)\b", h, re.I):
            continue
        cells = [r[i] for r in table.rows if i < len(r)]
        if cells and sum(cell_int(c) is not None for c in cells) * 2 >= len(cells):
            out.append(h)
    return out


# --------------------------------------------------------------------------
# Small parsers
# --------------------------------------------------------------------------

_INT_CELL = re.compile(r"^\s*(\d{1,3}(?:,\d{2,3})+|\d+)\s*\*?\s*(?:\(\s*\d+\s*\))?\s*$")
_WS = re.compile(r"\s+")


def _cell(value: Any) -> str:
    return _WS.sub(" ", str(value or "")).strip()


def cell_int(value: str) -> int | None:
    """An integer cell ("276", "1,234", "276*", "12 (3)"), else None."""
    m = _INT_CELL.match(value or "")
    return cand.parse_int(m.group(1)) if m else None


def _is_nil(text: str) -> bool:
    return bool(re.search(r"\b(?:nil|exempted?|no\s+fees?|free|not\s+required)\b", text, re.I))


_AMOUNT = re.compile(
    rf"(?:{cand._INR}\s*\.?\s*{cand._NUM}(?:\s*/\s*-|\s*-/|/-)?|{cand._NUM}\s*/-)", re.I
)


def amounts_in(text: str) -> list[tuple[int, int]]:
    """``(position, rupees)`` for every amount written as money."""
    out = []
    for m in _AMOUNT.finditer(text):
        raw = next(g for g in m.groups() if g)
        value = cand.parse_int(raw.replace(",", "").split(".")[0])
        if value is not None:
            out.append((m.start(), value))
    return out


def _first_date(text: str, reference: dt.date) -> tuple[str | None, str | None]:
    """First and second full date in a cell, ISO."""
    days = [d.value.isoformat() for d in cand.find_dates(text, reference) if d.is_day]
    first = days[0] if days else None
    second = days[1] if len(days) > 1 else None
    return first, second


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Table:
    page: int
    header: list[str]
    rows: list[list[str]]

    @property
    def header_text(self) -> str:
        return " | ".join(h for h in self.header if h)


def _collapse(rows: list[list[str]]) -> list[list[str]]:
    """Drop empty columns and repeated spanned cells.

    pymupdf returns a spanned cell once per grid column it covers, or as
    ``None`` in the columns after the first. Both are dropped column-wise:
    a column that is empty, or equal to its left neighbour, on every row
    carries no information of its own.
    """
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = []
    for c in range(width):
        column = [r[c] for r in rows]
        if not any(column):
            continue
        if keep and all(v == r[keep[-1]] or not v for v, r in zip(column, rows)):
            continue
        keep.append(c)
    return [[r[c] for c in keep] for r in rows]


def _looks_data(row: Sequence[str]) -> bool:
    return any(
        cell_int(c) is not None or cand._HAS_FULL_DATE.search(c) or amounts_in(c)
        for c in row
    )


def split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Leading non-data rows become one header, joined per column.

    A spanned header cell ("Category" over UR/SC/ST) is carried right over
    the empty cells beside it, so each column is named by both levels.
    """
    # A caption row ("Statement showing category-wise vacancies ...") is one
    # filled cell across a wide table; it names the table, not a column.
    while len(rows) > 2 and len(rows[0]) > 2 and sum(1 for c in rows[0] if c) == 1:
        rows = rows[1:]
    count = 0
    for row in rows:
        # A header cell is a short name. A long cell is content, even in a
        # table with no numbers at all (a key-value "Age limit | ..." box).
        if _looks_data(row) or count >= 4 or (count and any(len(c) > 40 for c in row)):
            break
        count += 1
    if count == len(rows):
        count = 1 if rows else 0
    head = [list(r) for r in rows[:count]]
    for level in range(len(head) - 1):
        for c in range(1, len(head[level])):
            if not head[level][c] and head[level + 1][c]:
                head[level][c] = head[level][c - 1]
    header = [
        " ".join(dict.fromkeys(h[c] for h in head if h[c])) for c in range(len(rows[0]))
    ] if rows else []
    return header, rows[count:]


def page_tables(doc: Any, limit: int = MAX_TABLE_PAGES) -> list[Table]:
    out = []
    for page in list(doc)[:limit]:
        try:
            found = page.find_tables().tables
        except Exception:
            continue
        for table in found:
            rows = [[_cell(c) for c in row] for row in table.extract()]
            rows = _collapse([r for r in rows if any(r)])
            if len(rows) < 2 or not rows[0]:
                continue
            header, body = split_header(rows)
            out.append(Table(page=page.number + 1, header=header, rows=body))
    return out


_PATTERN_HEAD = re.compile(r"question|marks|duration|time\s+allowed|syllabus", re.I)
_FEE_HEAD = re.compile(r"\bfees?\b|amount|payable", re.I)
_RELAX_HEAD = re.compile(r"relax|concession", re.I)
_TOTAL = re.compile(r"\btotal\b|vacanc|no\.?\s+of\s+posts|posts?\b|seats?", re.I)


def classify(table: Table) -> str | None:
    header = table.header_text
    cats = [category(h) for h in table.header]
    verticals = {c for c in cats if c and is_vertical(c)}
    if _RELAX_HEAD.search(header):
        return "relaxation"
    if len(verticals) >= 2 and any(
        cell_int(c) is not None for r in table.rows for c in r
    ):
        if _FEE_HEAD.search(header) and not re.search(r"vacanc|posts?", header, re.I):
            return "fee"
        return "vacancy"
    body = " ".join(" ".join(r) for r in table.rows)
    if (_FEE_HEAD.search(header) or re.search(r"\bfees?\b", body, re.I)) and not re.search(
        r"pay\s*(?:scale|level|matrix|band)|salary|emolument", header + " " + body, re.I
    ) and any(amounts_in(" ".join(r)) for r in table.rows):
        return "fee"
    if len(_PATTERN_HEAD.findall(header)) >= 2:
        return "pattern"
    if re.search(r"vacanc|no\.?\s+of\s+posts", header, re.I):
        return "vacancy"
    dated = sum(1 for r in table.rows if any(cand._HAS_FULL_DATE.search(c) for c in r))
    if dated and dated >= len(table.rows) / 2:
        return "schedule"
    if all(1 <= len([c for c in r if c]) <= 3 for r in table.rows) and len(table.header) <= 3:
        return "keyvalue"
    return None


_SERIAL = re.compile(r"^\(?(?:\d{1,3}|[ivx]{1,4}|[a-h])[.)]?\)?$", re.I)


def _label(cells: Iterable[str]) -> str:
    parts = [c for c in cells if c and cell_int(c) is None and not _SERIAL.match(c)]
    return " / ".join(dict.fromkeys(parts))


#: "Out of total vacancy, reserved for ..." is a subset column, never the total.
_SUBSET = re.compile(r"out\s+of|reserved\s+for|of\s+which|included", re.I)


def _total_score(head: str) -> int:
    """How surely a header names the row total. 0 means it does not."""
    if not head or _SUBSET.search(head) or re.search(r"\b(?:code|name|sl|sr|s\.?\s*no|serial)\b", head, re.I):
        return 0
    if re.search(r"\btotal\b", head, re.I):
        return 3
    if re.search(r"no\.?\s+of\s+(?:posts|vacanc\w*|seats)|vacanc", head, re.I):
        return 2
    if re.search(r"\bposts?\b|\bseats?\b", head, re.I) and not categories_in(head):
        return 1
    return 0


def parse_vacancy(table: Table) -> list[dict[str, Any]]:
    """One row per post/discipline/state line, with counts by category.

    The label is the row's text cells; an empty leading label cell repeats
    the one above it (a post split into Male/Female rows).
    """
    columns: dict[int, str] = {}
    total_col: int | None = None
    best = 0
    for i, head in enumerate(table.header):
        score = _total_score(head)
        # At a tie the rightmost wins: a row total sits at the end, a
        # post-level total spanning several rows sits near the start.
        if score and score >= best:
            best, total_col = score, i
        elif not score:
            # "Out of which, reserved for PwBD" is a horizontal count and is
            # kept; "out of which SC" would double-count a vertical one.
            cat = category(head)
            if cat and (not is_vertical(cat) or not _SUBSET.search(head)):
                columns[i] = cat
    text_cols = [
        i for i in range(len(table.header)) if i not in columns and i != total_col
    ]
    out: list[dict[str, Any]] = []
    last_label = ""
    for row in table.rows:
        label = _label(row[i] for i in text_cols if i < len(row))
        label = re.sub(r"^\d+\.?\s*/\s*", "", label).strip(" /")
        counts: dict[str, int] = {}
        for i, cat in columns.items():
            if i < len(row):
                n = cell_int(row[i])
                if n is not None:
                    counts[cat] = counts.get(cat, 0) + n
        total = cell_int(row[total_col]) if total_col is not None and total_col < len(row) else None
        if not counts and total is None:
            continue
        if re.fullmatch(r"(?:grand\s+)?total.*", label, re.I):
            out.append({"label": "Total", "is_total": True, "total": total, "by_category": counts, "page": table.page})
            continue
        if not label or re.fullmatch(r"(?:male|female|men|women)", label, re.I):
            label = f"{last_label} / {label}".strip(" /") if last_label else label
        else:
            last_label = label.split(" / ")[0]
        vertical_sum = sum(v for k, v in counts.items() if is_vertical(k))
        out.append({
            "label": label,
            "total": total if total is not None else (vertical_sum or None),
            "by_category": counts,
            "page": table.page,
        })
    return out


def parse_fee_table(table: Table) -> list[dict[str, Any]]:
    out = []
    header_cats = {i: category(h) for i, h in enumerate(table.header)}
    if sum(1 for c in header_cats.values() if c) >= 2:
        # Categories across the top, one row per post or paper.
        for row in table.rows:
            label = _label(row[i] for i, c in header_cats.items() if not c and i < len(row))
            for i, cat in header_cats.items():
                if cat and i < len(row) and row[i]:
                    amount = _amount_of(row[i], bare=True)
                    if amount is not None:
                        out.append({"categories": [cat], "amount": amount, "for": label or None,
                                    "raw": row[i], "page": table.page})
        return out
    money_cols = {i for i, h in enumerate(table.header) if _FEE_HEAD.search(h)}
    for row in table.rows:
        text = " ".join(row)
        if max(len(c) for c in row) > 60:
            # A sentence in a box ("Fee payable: Rs 100/- for male
            # candidates of UR ..."), not a cell.
            out.extend(fees_prose([(table.page, text)]))
            continue
        amount = None
        for i in reversed(range(len(row))):
            amount = _amount_of(row[i], bare=i in money_cols)
            if amount is not None:
                break
        if amount is None or re.search(r"%|\bgst\b|bank\s+charges|convenience|processing", text, re.I):
            continue
        out.append({**who(" ".join(c for c in row if _amount_of(c, bare=True) is None)), "amount": amount,
                    "raw": text[:200], "page": table.page})
    return out


def _amount_of(cell: str, bare: bool = False) -> int | None:
    """A fee cell's rupees. A bare number counts only in a fee column."""
    if len(cell) < 40 and _is_nil(cell):
        return 0
    found = amounts_in(cell)
    if found:
        return found[0][1]
    n = cell_int(cell) if bare else None
    return n if n is not None and 0 < n <= 20000 else None


_YEARS = re.compile(r"(\d{1,2})\s*(?:\(\s*\w+\s*\)\s*)?years?", re.I)


def parse_relaxation(table: Table) -> list[dict[str, Any]]:
    out = []
    for row in table.rows:
        text = " ".join(row)
        m = _YEARS.search(text)
        if m and re.search(r"age\s+of\s*$", text[: m.start()], re.I):
            m = None
        cats = categories_in(" ".join(c for c in row if not _YEARS.search(c)))
        label = _label(c for c in row if not _YEARS.search(c))
        if not (cats or m) or len(label) > 120:
            continue
        out.append({
            "categories": cats,
            "for": label,
            "years": int(m.group(1)) if m else None,
            "raw": text[:200],
            "page": table.page,
        })
    return out


def parse_pattern(table: Table) -> list[dict[str, Any]]:
    idx = {}
    for i, head in enumerate(table.header):
        low = head.lower()
        if "question" in low and "q" not in idx:
            idx["q"] = i
        elif "mark" in low and "m" not in idx:
            idx["m"] = i
        elif re.search(r"duration|time", low) and "d" not in idx:
            idx["d"] = i
    out = []
    for row in table.rows:
        label = _label(row[i] for i in range(len(row)) if i not in idx.values()).split(" / ")[0]
        if not label:
            continue
        item: dict[str, Any] = {"paper": label, "page": table.page}
        if "q" in idx and idx["q"] < len(row):
            item["questions"] = cell_int(row[idx["q"]])
        if "m" in idx and idx["m"] < len(row):
            item["marks"] = cell_int(row[idx["m"]])
        if "d" in idx and idx["d"] < len(row) and row[idx["d"]]:
            item["duration"] = row[idx["d"]]
        if len(item) > 2:
            out.append(item)
    return out


#: Schedule row label -> date key. First match wins.
_EVENT_KEYS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.I), k)
    for p, k in (
        (r"correction|modif|edit", "correction_window"),
        (r"admit|call\s+letter|hall\s+ticket", "admit_card_from"),
        (r"answer\s+key", "answer_key"),
        (r"result", "result_date"),
        (r"(?:fee|payment).*(?:last|clos|end)|(?:last|clos|end).*(?:fee|payment)", "payment_deadline"),
        (r"(?:last|clos|end)\w*.*(?:regist|appl|submi|online)|(?:regist|appl|submi|online).*(?:last|clos|end)", "registration_deadline"),
        (r"(?:open|start|commence|begin)\w*.*(?:regist|appl|submi|online)|(?:regist|appl|submi|online).*(?:open|start|commence|begin)", "registration_open"),
        (r"exam|test|cbt|prelim|mains?\b|interview", "exam_date"),
        (r"as\s+on|cut[-\s]?off\s+date|crucial\s+date", "age_as_on"),
    )
)


def event_key(label: str) -> str | None:
    for pattern, key in _EVENT_KEYS:
        if pattern.search(label):
            return key
    return None


def parse_schedule(table: Table, reference: dt.date) -> list[dict[str, Any]]:
    out = []
    for row in [table.header] + table.rows:
        dated = [c for c in row if cand._HAS_FULL_DATE.search(c)]
        label = " ".join(c for c in row if c and c not in dated and cell_int(c) is None)
        if not dated or not label:
            continue
        start, end = _first_date(" ".join(dated), reference)
        if not start:
            continue
        item = {"event": label[:160], "key": event_key(label), "date": start, "page": table.page}
        if end and end != start:
            item["until"] = end
        out.append(item)
    return out


# --------------------------------------------------------------------------
# Prose
# --------------------------------------------------------------------------

_ADVT = re.compile(
    r"\b(?:advt\.?|advertisement|notification|vacancy\s+notice|cen|employment\s+notice)"
    r"\s*(?:no\.?|number|#)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9/().\-]{0,30}[A-Z0-9)])",
    re.I,
)


def advertisement_no(text: str) -> str | None:
    m = _ADVT.search(text[:6000])
    return m.group(1).strip(".-") if m else None


_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'()\[\]]+", re.I)
_APPLY_URL = re.compile(r"apply|online|regist|recruit|career|candidate|portal|ibps|exam", re.I)


def links_in(text: str, uris: Iterable[str] = ()) -> dict[str, list[str]]:
    seen: dict[str, None] = {}
    for u in list(uris) + _URL.findall(text):
        u = u.rstrip(".,;:)]}'\"")
        if u.lower().startswith("www."):
            u = "https://" + u
        if "@" in u or len(u) < 12 or u.lower().startswith("mailto"):
            continue
        if u.rstrip("/") in {k.rstrip("/") for k in seen}:
            continue
        seen.setdefault(u, None)
    apply = [u for u in seen if _APPLY_URL.search(u.split("//", 1)[-1])]
    other = [u for u in seen if u not in apply]
    return {"apply": apply[:8], "other": other[:12]}


_AGE_RANGE = re.compile(
    r"(?:between|from)?\s*(\d{2})\s*(?:years?\s*)?(?:and|to|-|–)\s*(\d{2})\s*years?", re.I
)
_AGE_MIN = re.compile(r"(?:minimum\s+age|not\s+(?:be\s+)?less\s+than|at\s+least)\D{0,40}?(\d{2})\s*years?", re.I)
_AGE_MAX = re.compile(
    r"(?:maximum\s+age|upper\s+age\s+limit|not\s+(?:be\s+)?(?:more\s+than|exceed\w*|above)|"
    r"below|under)\D{0,40}?(\d{2})\s*years?", re.I
)
_AGE_CLAUSE = re.compile(r"\bage\b", re.I)
#: Clauses that state an age but not the post's limit: relaxations, caps on
#: cumulative relaxation, and the ages of a candidate's dependants.
_AGE_NOISE = re.compile(
    r"relax|concession|cumulative|children|spouse|\bsons?\b|daughters?|\bward\b|dependent|"
    r"widow|retire|superannuation|service\s+of|served", re.I
)


def age_limits(pages: Sequence[tuple[int, str]]) -> list[dict[str, Any]]:
    """Distinct (min, max) pairs, each with the clause it came from."""
    out: list[dict[str, Any]] = []
    seen = set()
    for page, text in pages:
        previous = ""
        for clause in cand.clauses(text):
            labelled = _AGE_CLAUSE.search(clause) or (
                _AGE_CLAUSE.search(previous) and len(previous) < 60
            )
            previous = clause
            if not labelled or _AGE_NOISE.search(clause):
                continue
            low = high = None
            m = _AGE_RANGE.search(clause)
            if m:
                low, high = int(m.group(1)), int(m.group(2))
            else:
                a = _AGE_MIN.search(clause)
                b = _AGE_MAX.search(clause)
                low = int(a.group(1)) if a else None
                high = int(b.group(1)) if b else None
            if low is not None and not 14 <= low <= 60:
                low = None
            if high is not None and not 16 <= high <= 70:
                high = None
            if low is not None and high is not None and low >= high:
                continue
            if low is None and high is None:
                continue
            if (low, high) in seen:
                continue
            seen.add((low, high))
            out.append({"min": low, "max": high, "evidence": cand._clean_sentence(clause, 240), "page": page})
    return out[:8]


def relaxation_prose(pages: Sequence[tuple[int, str]]) -> list[dict[str, Any]]:
    """"upper age limit is relaxable by 5 years for SC/ST" and the like."""
    out = []
    for page, text in pages:
        for clause in cand.clauses(text):
            if not re.search(r"relax|concession", clause, re.I):
                continue
            for m in _YEARS.finditer(clause):
                years = int(m.group(1))
                if not 1 <= years <= 15:
                    continue
                window = clause[max(0, m.start() - 90): m.end() + 90]
                cats = [c for c in categories_in(window) if c != "Unreserved"]
                if cats:
                    out.append({"categories": cats, "years": years,
                                "raw": cand._clean_sentence(clause, 200), "page": page})
    return _dedupe(out, ("categories", "years"))[:12]


def fees_prose(pages: Sequence[tuple[int, str]]) -> list[dict[str, Any]]:
    """Fee amounts in sentences, each tied to the categories beside it.

    "Rs. 850/- for General/OBC/EWS and Rs. 175/- for SC/ST/PwBD": each
    amount takes the categories between it and the next amount. When the
    clause names categories first ("SC/ST: Rs 175"), it takes those before.
    An exemption ("SC/ST ... are exempted") is a fee of nil, and may be the
    sentence after the one with the amount.
    """
    out = []
    for page, text in pages:
        previous = ""
        fee_context = False
        for clause in cand.clauses(text):
            # A fee table flattened to text puts the category on one line
            # and its amount on the next.
            if previous and len(previous) < 80 and not amounts_in(previous) and (
                categories_in(previous) and not categories_in(clause.split("Rs")[0])
            ):
                clause = f"{previous} {clause}"
            previous = clause if not amounts_in(clause) else ""
            about_fee = bool(re.search(r"\bfees?\b|charges", clause, re.I))
            near_fee, fee_context = fee_context, about_fee
            if re.search(r"refund|penalty|late\s+fee|re-?evaluation|photocopy|%|\bgst\b|"
                         r"bank\s+charges|convenience|processing", clause, re.I):
                continue
            found = amounts_in(clause) if about_fee else []
            cats_first = bool(found) and bool(categories_in(clause[: found[0][0]]))
            bounds = [p for p, _ in found] + [len(clause)]
            for i, (pos, amount) in enumerate(found):
                if cats_first:
                    seg = clause[(bounds[i - 1] if i else 0): pos]
                else:
                    seg = clause[pos: bounds[i + 1]]
                out.append({**who(seg), "amount": amount,
                            "raw": cand._clean_sentence(clause, 240), "page": page})
            if about_fee or near_fee:
                nil = re.search(r"(.{0,160}?)\b(?:(?:are|is|shall\s+be)\s+exempted|exempted\s+from|no\s+fee|nil)\b",
                                clause, re.I)
                if nil:
                    cats = categories_in(nil.group(1))
                    if cats:
                        out.append({"categories": cats, "amount": 0,
                                    "raw": cand._clean_sentence(clause, 240), "page": page})
                        fee_context = True
    return _dedupe(out, ("categories", "except", "amount"))[:12]


_STAGES: tuple[tuple[str, str], ...] = (
    (r"preliminary|prelims?\b", "Preliminary examination"),
    (r"\bmain\s+(?:written\s+)?exam\w*|\bmains\b|\band\s+main\b", "Main examination"),
    (r"computer[\s-]*based\s+test|\bcbt\b|online\s+exam\w*|online\s+test", "Computer-based test"),
    (r"written\s+(?:exam\w*|test)|objective\s+type", "Written examination"),
    (r"physical\s+(?:efficiency|endurance|standard|measurement)|\bpet\b|\bpst\b|\bpmt\b", "Physical test"),
    (r"skill\s+test|typing\s+test|stenography\s+test|trade\s+test|proficiency\s+test", "Skill / trade test"),
    (r"group\s+discussion|\bgd\b", "Group discussion"),
    (r"interview|personality\s+test|viva", "Interview"),
    (r"document\s+verification|verification\s+of\s+documents|\bdv\b", "Document verification"),
    (r"medical\s+exam\w*|medical\s+test|medical\s+fitness", "Medical examination"),
)
_SELECTION = re.compile(r"selection\s+(?:process|procedure|shall|will|method)|mode\s+of\s+selection|scheme\s+of\s+(?:selection|exam)", re.I)


def selection_stages(text: str) -> list[str]:
    """Stages in the order the selection paragraph names them."""
    windows = [text[m.start(): m.start() + 1500] for m in _SELECTION.finditer(text)][:3]
    if not windows:
        return []
    hits: dict[str, tuple[int, int]] = {}
    for n, window in enumerate(windows):
        for pattern, name in _STAGES:
            m = re.search(pattern, window, re.I)
            if m and name not in hits:
                hits[name] = (n, m.start())
    return sorted(hits, key=hits.get)


_EDU_LEVELS: tuple[tuple[str, str], ...] = (
    (r"\bph\.?\s*d\b|doctorate", "Doctorate"),
    (r"post[\s-]*graduat\w*|master'?s?\s+degree|\bm\.?\s?(?:sc|a|com|tech|e|ba|ca|phil)\b\.?|\bmba\b|\bllm\b|\bmd\b|\bms\b", "Postgraduate"),
    (r"\bgraduat\w*|bachelor'?s?\s+degree|\bdegree\b|\bb\.?\s?(?:sc|a|com|tech|e|ed|ba|ca|pharm)\b\.?|\bmbbs\b|\bllb\b", "Graduate"),
    (r"\bdiploma\b|\biti\b|\bpolytechnic\b", "Diploma / ITI"),
    (r"\b10\s*\+\s*2\b|\b12th\b|intermediate|higher\s+secondary|\bhsc\b|senior\s+secondary|class\s+xii\b", "Class 12"),
    (r"\b10th\b|matricul\w*|\bssc\b(?!\s+(?:cgl|chsl|gd|mts|je|cpo|steno))|class\s+x\b|high\s+school|secondary\s+school", "Class 10"),
)
_QUAL = re.compile(
    r"educational\s+qualification|essential\s+qualification|qualification\s*[:\-]|"
    r"eligibility\s+criteri|minimum\s+qualification|must\s+(?:have|possess)|should\s+(?:have|possess)|"
    r"passed\s+(?:the\s+)?(?:\w+\s+){0,3}(?:exam|degree)|degree\s+in", re.I
)


def qualifications(pages: Sequence[tuple[int, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Qualification clauses, and the education levels they name."""
    clauses_out: list[dict[str, Any]] = []
    levels: dict[str, None] = {}
    for page, text in pages:
        for clause in cand.clauses(text):
            if not _QUAL.search(clause) or len(clause) < 25:
                continue
            if re.search(r"date\s+of\s+birth|proof\s+of\s+age|for\s+age", clause, re.I):
                continue
            clauses_out.append({"text": cand._clean_sentence(clause, 300), "page": page})
            for pattern, level in _EDU_LEVELS:
                if re.search(pattern, clause, re.I):
                    levels.setdefault(level, None)
            if len(clauses_out) >= 10:
                break
    order = [lvl for _, lvl in _EDU_LEVELS]
    return clauses_out, sorted(levels, key=order.index)


def pay_scales(pages: Sequence[tuple[int, str]], source_url: str) -> list[dict[str, Any]]:
    out = []
    for page, text in pages:
        for clause in cand.clauses(text):
            if not re.search(r"pay|salary|scale|emolument|stipend|remuneration|ctc|level", clause, re.I):
                continue
            if re.search(r"\bfees?\b|payment|payable|pay\s+(?:the|online|through|via)", clause, re.I):
                continue
            c = cand._pay_candidate(clause, page, False, source_url)
            if c and c.pay:
                p = dict(c.pay)
                if p.get("low") and p.get("high") and not (5000 <= p["low"] < p["high"] <= 500000):
                    p.pop("low"), p.pop("high")
                if not ({"levels", "low", "initial", "grade"} & p.keys()):
                    continue
                out.append({**p, "text": pay_text(p), "evidence": c.evidence, "page": page})
    return _dedupe(out, ("text",))[:10]


def pay_text(pay: dict[str, Any]) -> str:
    parts = []
    if pay.get("levels"):
        lv = pay["levels"]
        parts.append(f"Pay Level {lv[0]}" if len(lv) == 1 else f"Pay Levels {', '.join(map(str, lv))}")
    if pay.get("grade"):
        parts.append(f"Grade {pay['grade']}")
    if pay.get("low") and pay.get("high"):
        parts.append(f"₹{pay['low']:,}–{pay['high']:,}")
    if pay.get("initial"):
        parts.append(f"initial basic ₹{pay['initial']:,}")
    return ", ".join(parts)


def _dedupe(items: list[dict[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        k = tuple(str(item.get(key)) for key in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


# --------------------------------------------------------------------------
# Kind
# --------------------------------------------------------------------------

_KINDS: tuple[tuple[str, str], ...] = (
    (r"answer\s*key", "answer_key"),
    (r"admit\s*card|call\s*letter|hall\s*ticket|e-?admit", "admit_card"),
    (r"corrigendum|addendum|erratum|extension|extended|revised|postpone|reschedul", "corrigendum"),
    (r"result|merit\s+list|select(?:ed|ion)\s+list|recommend|shortlist|provisional(?:ly)?\s+selected|marks\s+obtained|cut[\s-]?off", "result"),
    (r"information\s+(?:brochure|bulletin|booklet)|prospectus|brochure|bulletin", "brochure"),
    (r"time[\s-]*table|schedule|date\s*sheet|programme", "schedule"),
    (r"advertisement|advt|recruitment|vacanc|applications?\s+are\s+invited|notification\s+for|detailed\s+notification|employment\s+notice", "advertisement"),
    (r"syllabus", "syllabus"),
)


def document_kind(title: str, first_page: str) -> str:
    for text in (title, first_page[:1500]):
        for pattern, kind in _KINDS:
            if re.search(pattern, text or "", re.I):
                return kind
    return "notice"


def _indic_share(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if "\u0900" <= ch <= "\u0dff") / len(text)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


#: Date fields worth reading out of prose. A result date or an admit-card
#: closing date in an advertisement is nearly always a stray date.
_PROSE_DATES = {"registration_open", "registration_deadline", "payment_deadline",
                "exam_date", "admit_card_from", "age_as_on"}


def structure(
    content: bytes,
    notice: dict[str, Any],
    settings: Settings,
    *,
    fetched: str | None = None,
) -> dict[str, Any]:
    """One notice's PDF -> one record. Raises ExtractionError on a bad PDF."""
    token = _JURISDICTION.set(jurisdiction_of(notice))
    try:
        return _structure(content, notice, settings, fetched)
    finally:
        _JURISDICTION.reset(token)


def jurisdiction_of(notice: dict[str, Any]) -> str | None:
    """A body id starts with its jurisdiction ("kl-kpsc" -> "kl"); lint enforces it."""
    body = notice.get("body") or ""
    return body.split("-", 1)[0] or None


def _structure(content: bytes, notice: dict[str, Any], settings: Settings, fetched: str | None) -> dict[str, Any]:
    url = notice.get("url", "")
    pages_text, is_ocr, engine, warnings = pdf_pages(content, settings)
    pages = [(i + 1, t) for i, t in enumerate(pages_text)]
    # Prose readers see sentences, not the PDF's hard-wrapped lines.
    prose = [(n, cand.unwrap_soft_breaks(t)) for n, t in pages]
    text = "\n\n".join(pages_text)
    reference = _reference(notice, pages_text[0] if pages_text else "")

    tables: list[Table] = []
    uris: list[str] = []
    if not is_ocr:
        pymupdf = _pymupdf()
        doc = pymupdf.open(stream=content, filetype="pdf")
        try:
            tables = page_tables(doc)
            for page in list(doc)[:MAX_TABLE_PAGES]:
                uris.extend(link.get("uri") for link in page.get_links() if link.get("uri"))
        finally:
            doc.close()

    by_kind: dict[str, list[Table]] = {}
    for table in tables:
        kind = classify(table)
        if kind:
            by_kind.setdefault(kind, []).append(table)

    record: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "notice": {k: notice.get(k) for k in ("id", "url", "title", "body", "exam", "feed", "published", "doc_type")},
        "document": {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "pages": len(pages_text),
            "chars": len(text),
            "ocr": is_ocr,
            "ocr_engine": engine,
            "indic_share": round(_indic_share(text), 2),
            "fetched": fetched,
        },
        "kind": document_kind(notice.get("title") or "", pages_text[0] if pages_text else ""),
        "advertisement_no": advertisement_no(text),
    }

    # -- dates: table rows are the body's own summary; prose fills gaps.
    events: list[dict[str, Any]] = []
    for table in by_kind.get("schedule", []) + by_kind.get("keyvalue", []):
        events.extend(parse_schedule(table, reference))
    # A date years before the notice is a citation ("registered on or before
    # 29.09.2015"), not this notice's schedule.
    stale = (reference - dt.timedelta(days=400)).isoformat()
    events = [e for e in events if e["date"] >= stale]
    dates: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["key"] and event["key"] not in dates:
            dates[event["key"]] = {"date": event["date"], **({"until": event["until"]} if "until" in event else {}),
                                   "evidence": event["event"], "page": event["page"], "from": "table"}
    found = cand.find_candidates(text, url, pages=[(n, t, is_ocr) for n, t in pages], reference=reference)
    judged = cand.adjudicate(found)
    for key, adj in judged.items():
        c = adj.chosen
        if not c or c.ambiguous or key in dates or key not in _PROSE_DATES or c.hint < 0.7:
            continue
        if c.value < stale:
            continue
        dates[key] = {"date": c.value, "provisional": c.provisional or None,
                      "evidence": c.evidence[:240], "page": c.page, "from": "text"}
    record["dates"] = {k: {kk: vv for kk, vv in v.items() if vv is not None} for k, v in dates.items()}
    record["schedule"] = events[:40]

    # -- class columns the vocabulary does not know: the worklist
    record["unmapped_classes"] = list({
        h: {"label": h, "page": t.page}
        for kind in ("vacancy", "fee", "relaxation") for t in by_kind.get(kind, []) for h in unmapped_headers(t)
    }.values())[:20]

    # -- vacancies
    groups: dict[str, list[dict[str, Any]]] = {}
    for table in by_kind.get("vacancy", []):
        rows = parse_vacancy(table)
        if rows:
            groups.setdefault(table.header_text.lower(), []).extend(rows)
    record["vacancies"] = summarise_vacancies(groups, found)

    # -- fees
    fees = [f for t in by_kind.get("fee", []) for f in parse_fee_table(t)]
    record["fees"] = _dedupe(fees, ("categories", "except", "amount", "for")) or fees_prose(prose)

    # -- age
    relax = [r for t in by_kind.get("relaxation", []) for r in parse_relaxation(t)]
    as_on = dates.get("age_as_on", {}).get("date")
    record["age"] = {
        "limits": age_limits(prose),
        "as_on": as_on,
        "relaxations": relax or relaxation_prose(prose),
    }

    record["pay"] = pay_scales(prose, url)
    quals, levels = qualifications(prose)
    record["eligibility"] = {"education_levels": levels, "clauses": quals}
    record["selection"] = selection_stages(text)
    record["exam_pattern"] = [p for t in by_kind.get("pattern", []) for p in parse_pattern(t)][:30]

    text_fields = {}
    for key in ("mode", "negative_marking", "duration"):
        adj = judged.get(key)
        if adj and adj.chosen:
            text_fields[key] = {"value": adj.chosen.value, "page": adj.chosen.page}
    record["exam"] = text_fields
    record["links"] = links_in(text, uris)
    record["summary"] = summarise(record)
    if is_ocr:
        warnings.append("read by OCR: numbers and names may be misread; check against the PDF")
    record["warnings"] = warnings
    return _prune(record)


def summarise_vacancies(groups: dict[str, list[dict[str, Any]]], found: Sequence[cand.Candidate]) -> dict[str, Any]:
    """Pick the vacancy table group with the largest total.

    A notice often has a summary table and a detailed one that repeat the
    same posts; adding them would double-count. The largest single group
    is the conservative reading.
    """
    best: dict[str, Any] = {}
    for rows in groups.values():
        totals = [r for r in rows if r.get("is_total")]
        lines = [r for r in rows if not r.get("is_total")]
        by_cat: dict[str, int] = {}
        if totals:
            total = sum(r["total"] or 0 for r in totals) or None
            for r in totals:
                for k, v in r["by_category"].items():
                    by_cat[k] = by_cat.get(k, 0) + v
        else:
            total = sum(r["total"] or 0 for r in lines) or None
            for r in lines:
                for k, v in r["by_category"].items():
                    by_cat[k] = by_cat.get(k, 0) + v
        if total and (total, bool(by_cat)) > (best.get("total") or 0, bool(best.get("by_category"))):
            best = {"total": total, "by_category": _ordered(by_cat), "rows": lines[:200], "from": "table"}
    if best:
        return best
    # Only a sentence that says "vacancies" is trusted: "Post 12/26" is a
    # post code, and "12 posts" in a scheme paragraph is often a citation.
    counts = [c for c in found if c.field == "vacancies" and c.as_int()
              and re.search(r"vacanc", c.evidence, re.I) and c.hint >= 0.6]
    if counts:
        top = max(counts, key=lambda c: (c.hint, -(c.page or 0)))
        return {"total": top.as_int(), "evidence": top.evidence[:240], "page": top.page, "from": "text"}
    return {}


def _ordered(by_cat: dict[str, int]) -> dict[str, int]:
    """Vertical classes first, then the rest, each in the vocabulary's order."""
    v = reservation.load()
    return {k: by_cat[k] for k in sorted(by_cat, key=lambda k: (not v.is_vertical(k), v.rank(k)))}


def summarise(record: dict[str, Any]) -> dict[str, Any]:
    """The at-a-glance line: one readable value per question a candidate asks."""
    out: dict[str, Any] = {}
    vac = record.get("vacancies") or {}
    if vac.get("total"):
        out["vacancies"] = vac["total"]
    dates = record.get("dates") or {}
    if "registration_open" in dates or "registration_deadline" in dates:
        out["apply"] = {
            "from": dates.get("registration_open", {}).get("date"),
            "until": dates.get("registration_deadline", {}).get("until")
            or dates.get("registration_deadline", {}).get("date")
            or dates.get("registration_open", {}).get("until"),
        }
    if "exam_date" in dates:
        out["exam_date"] = dates["exam_date"]["date"]
    fees = record.get("fees") or []
    if fees:
        amounts = [f["amount"] for f in fees]
        out["fee"] = {"min": min(amounts), "max": max(amounts)}
    limits = (record.get("age") or {}).get("limits") or []
    # The first stated limits: the post's own, before any per-post exception.
    low = next((a["min"] for a in limits if a.get("min") is not None), None)
    high = next((a["max"] for a in limits if a.get("max") is not None), None)
    if low is not None or high is not None:
        out["age"] = {"min": low, "max": high}
    if record.get("pay"):
        out["pay"] = record["pay"][0]["text"]
    levels = (record.get("eligibility") or {}).get("education_levels") or []
    if levels:
        out["education"] = levels
    if record.get("selection"):
        out["selection"] = " → ".join(record["selection"])
    return out


def _reference(notice: dict[str, Any], first_page: str = "") -> dt.date:
    """The date the notice speaks from.

    Its published date when the feed gave one. Otherwise the latest full date
    on the first page that is not after the crawl first saw it: the "Dated"
    line of a notice, or its closing date, either of which anchors the rest.
    """
    value = notice.get("published")
    if value:
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    seen = dt.date.today()
    if notice.get("first_seen"):
        try:
            seen = dt.date.fromisoformat(str(notice["first_seen"])[:10])
        except ValueError:
            pass
    stated = [d.value for d in cand.find_dates(first_page[:2500], seen) if d.is_day and d.value <= seen]
    return max(stated) if stated else seen


def _prune(value: Any) -> Any:
    """Drop empty containers and Nones, so absence means 'not found'."""
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _d(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return dt.date.fromisoformat(iso).strftime("%-d %b %Y")
    except ValueError:
        return iso


def _money(n: int) -> str:
    return "Nil" if n == 0 else f"₹{n:,}"


def _cats(cats: Sequence[str]) -> str:
    v = reservation.load()
    return "/".join(v.short(c) for c in cats) if cats else "All candidates"


def _who(item: dict[str, Any]) -> str:
    cats = _cats(item.get("categories") or [])
    return f"All except {cats}" if item.get("except") else cats


def _md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(record: dict[str, Any]) -> str:
    notice = record.get("notice", {})
    doc = record.get("document", {})
    lines = [f"# {_md(notice.get('title') or 'Untitled notice')}", ""]
    meta = [f"**{notice.get('body')}**"]
    if notice.get("exam"):
        meta.append(f"exam `{notice['exam']}`")
    meta.append(record.get("kind", "notice").replace("_", " "))
    if record.get("advertisement_no"):
        meta.append(f"Advt. No. {record['advertisement_no']}")
    meta.append(f"{doc.get('pages', '?')} pages")
    lines += [" · ".join(meta), "", f"Source: <{notice.get('url')}>", ""]
    if doc.get("ocr"):
        lines += ["> **Read by OCR.** Numbers and names may be misread; check against the PDF.", ""]

    s = record.get("summary") or {}
    glance = []
    if "vacancies" in s:
        by = (record.get("vacancies") or {}).get("by_category") or {}
        split = " · ".join(f"{_cats([k])} {v:,}" for k, v in by.items())
        glance.append(("Vacancies", f"{s['vacancies']:,}" + (f" ({split})" if split else "")))
    if "apply" in s:
        glance.append(("Apply", f"{_d(s['apply'].get('from'))} – {_d(s['apply'].get('until'))}"))
    if "exam_date" in s:
        glance.append(("Exam", _d(s["exam_date"])))
    if record.get("fees"):
        glance.append(("Fee", "; ".join(
            f"{_who(f)} {_money(f['amount'])}" + (f" ({f['for']})" if f.get("for") else "")
            for f in record["fees"][:6])))
    age = record.get("age") or {}
    if "age" in s:
        a = s["age"]
        text = f"{a.get('min') or '?'}–{a.get('max') or '?'} years"
        if age.get("as_on"):
            text += f" as on {_d(age['as_on'])}"
        relax = age.get("relaxations") or []
        rel = ", ".join(f"{(_cats(r['categories']) if r.get('categories') else r.get('for', ''))} +{r['years']}"
                        for r in relax if r.get("years"))[:200]
        if rel:
            text += f"; relaxation: {rel}"
        glance.append(("Age", text))
    if "pay" in s:
        glance.append(("Pay", s["pay"]))
    if "education" in s:
        glance.append(("Education named", ", ".join(s["education"])))
    if "selection" in s:
        glance.append(("Selection", s["selection"]))
    for key, label in (("mode", "Mode"), ("negative_marking", "Negative marking")):
        if key in (record.get("exam") or {}):
            glance.append((label, record["exam"][key]["value"]))
    if glance:
        lines += ["## At a glance", "", "| | |", "|---|---|"]
        lines += [f"| {k} | {_md(v)} |" for k, v in glance]
        lines.append("")

    vac = record.get("vacancies") or {}
    if vac.get("rows"):
        cats = list(dict.fromkeys(k for r in vac["rows"] for k in r.get("by_category", {})))
        lines += ["## Posts and vacancies", "",
                  "| Post | " + " | ".join(_cats([c]) for c in cats) + " | Total | p. |",
                  "|---|" + "---:|" * (len(cats) + 1) + "---|"]
        for r in vac["rows"][:60]:
            counts = " | ".join(str(r.get("by_category", {}).get(c, "")) for c in cats)
            lines.append(f"| {_md((r.get('label') or '—')[:80])} | {counts} | {r.get('total') or ''} | {r['page']} |")
        if len(vac["rows"]) > 60:
            lines.append(f"| … {len(vac['rows']) - 60} more rows | |")
        lines.append("")
    elif vac.get("evidence"):
        lines += ["## Vacancies", "", f"> {_md(vac['evidence'])} (p. {vac.get('page')})", ""]

    dates = record.get("dates") or {}
    if dates:
        lines += ["## Important dates", "", "| Event | Date | p. |", "|---|---|---|"]
        for key, d in sorted(dates.items(), key=lambda kv: kv[1]["date"]):
            when = _d(d["date"]) + (f" – {_d(d['until'])}" if d.get("until") else "")
            if d.get("provisional"):
                when += " (tentative)"
            label = cand.FIELD_BY_KEY[key].label if key in cand.FIELD_BY_KEY else key.replace("_", " ")
            lines.append(f"| {label} | {when} | {d.get('page', '')} |")
        lines.append("")

    if record.get("fees"):
        lines += ["## Application fee", "", "| Category | Fee | p. |", "|---|---:|---|"]
        for f in record["fees"]:
            who = _who(f) + (f" — {f['for']}" if f.get("for") else "")
            lines.append(f"| {_md(who)} | {_money(f['amount'])} | {f.get('page', '')} |")
        lines.append("")

    if age.get("limits") or age.get("relaxations"):
        lines += ["## Age", ""]
        for a in age.get("limits", []):
            lines.append(f"- {a.get('min') or '?'}–{a.get('max') or '?'} years: “{_md(a['evidence'])}” (p. {a['page']})")
        if age.get("as_on"):
            lines.append(f"- Age reckoned as on **{_d(age['as_on'])}**")
        for r in age.get("relaxations", []):
            who = _cats(r.get("categories") or []) if r.get("categories") else r.get("for", "")
            yrs = f"{r['years']} years" if r.get("years") else _md(r.get("raw", ""))
            lines.append(f"- Relaxation, {_md(who)}: {yrs} (p. {r.get('page')})")
        lines.append("")

    if record.get("pay"):
        lines += ["## Pay", ""]
        lines += [f"- **{p['text']}**: “{_md(p['evidence'][:200])}” (p. {p['page']})" for p in record["pay"]]
        lines.append("")

    elig = record.get("eligibility") or {}
    if elig.get("clauses"):
        lines += ["## Eligibility", ""]
        if elig.get("education_levels"):
            lines += ["Education levels named: " + ", ".join(elig["education_levels"]), ""]
        lines += [f"- “{_md(c['text'])}” (p. {c['page']})" for c in elig["clauses"][:8]]
        lines.append("")

    if record.get("exam_pattern"):
        lines += ["## Exam pattern", "", "| Paper | Questions | Marks | Duration |", "|---|---:|---:|---|"]
        for p in record["exam_pattern"]:
            lines.append(f"| {_md(p['paper'][:70])} | {p.get('questions', '')} | {p.get('marks', '')} | {_md(p.get('duration', ''))} |")
        lines.append("")

    links = record.get("links") or {}
    if links.get("apply") or links.get("other"):
        lines += ["## Links", ""]
        lines += [f"- Apply / portal: <{u}>" for u in links.get("apply", [])]
        lines += [f"- <{u}>" for u in links.get("other", [])[:6]]
        lines.append("")

    if record.get("warnings"):
        lines += ["## Notes", ""] + [f"- {_md(w)}" for w in record["warnings"]] + [""]
    lines.append(f"<sub>Extracted mechanically from the PDF (sha256 {doc.get('sha256', '')[:12]}); page numbers point at the evidence.</sub>")
    return "\n".join(lines) + "\n"
