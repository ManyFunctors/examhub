"""The "find" layer: deterministic regex/heuristic extraction of candidates.

**This is where extraction happens, and there is no model in this file.** A
322M non-autoregressive classifier cannot pull a date out of a 60-page PDF,
and asking one to is how you get a hallucinated date in a site's front
matter. Regex finds the candidates; :mod:`examhub_pipeline.validate` decides
whether the source really says them.

The output is deliberately *candidates*, not values: several may be wrong,
several may disagree, and one per field has to be adjudicated. The rules that
make the adjudication safe:

* **A candidate carries its evidence.** The sentence it was found in, its
  character span, its page, and whether that page is OCR output.
* **Granularity is explicit.** ``day`` | ``month`` | ``none``. "June 2027" is
  a month, and a month is not a date -- the data model says so -- so it
  becomes a note, never an ``exam_date``.
* **Hedging is detected, not guessed.** "tentative", "proposed", "expected",
  "subject to change" within the same clause demote a date to
  ``provisional``. Nothing in this pipeline can promote a provisional date to
  confirmed; that is a human decision.
* **One value per field.** :func:`adjudicate` returns one winner plus the
  losers, and says so when the disagreement is real.

The patterns are written against the shapes Indian exam notices actually
use: "15.06.2027", "15/06/2027", "15th June, 2027", "2nd week of June 2027",
"₹100/-", "Rs. 100/-", "100/- only", "1,044 posts", "Pay Matrix Level 7",
"24,050-1340(3)-28,070".
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------
# Text normalisation
# --------------------------------------------------------------------------

#: OCR and portal exports produce all of these for the same character. Fold
#: them before matching, or "Rs.100/-" and "Rs 100" become different things.
_LOOKALIKE = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
    "\u20b9": "Rs", "\u20b8": "Rs",  # ₹ / ৳
    "\ufffd": "", "\u00ad": "",
}
_LOOKALIKE_RE = re.compile("|".join(map(re.escape, _LOOKALIKE)))

_ORDINALS = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7,
    "8th": 8, "9th": 9, "10th": 10, "11th": 11, "12th": 12, "13th": 13,
    "14th": 14, "15th": 15, "16th": 16, "17th": 17, "18th": 18, "19th": 19,
    "20th": 20, "21st": 21, "22nd": 22, "23rd": 23, "24th": 24, "25th": 25,
    "26th": 26, "27th": 27, "28th": 28, "29th": 29, "30th": 30, "31st": 31,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))


def normalise(text: str) -> str:
    """Fold lookalikes, strip zero-width, collapse runs of spaces.

    NFKC also turns the fullwidth digits and full stops that several
    government portals emit (``２０２７`` -> ``2027``) back into ASCII, which
    is a surprisingly common failure mode on ``.nic.in`` notice pages.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _LOOKALIKE_RE.sub(lambda m: _LOOKALIKE[m.group(0)], text)
    return re.sub(r"[ \t]+", " ", text)


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Soft line breaks
# --------------------------------------------------------------------------

#: A PDF text layer is hard-wrapped at whatever column the typesetter used.
#: Splitting clauses on that newline means "Last date to apply: 22.02.2027" and
#: its own continuation live in different clauses, and half of every real
#: notice's date table is thrown away. So soft breaks are joined first.
#:
#: A break is soft when the line does not end in sentence punctuation AND the
#: next line does not begin a new numbered clause or heading. Both halves of
#: that test matter: a line ending in "." is a real break even if the next
#: line starts lowercase, and a line starting "3." is a new clause even if
#: the previous line ended mid-word.
_SENTENCE_END = re.compile(r"[.!?:;]\s*$")
# The negative lookahead is essential: a PDF line-wrapped clause very often
# *starts* with the date, because that is what filled the last line of the
# previous one ("... will be held on\n15.06.2026 at 10:00 AM"). Without it,
# every such line is read as a new numbered clause, the clause is split in
# half, and the label is separated from its own value.
_NEW_CLAUSE_START = re.compile(
    r"^(?!\s*\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.])"
    r"\s*(?:\d{1,2}\s*[.)]|\(\d{1,2}\)|[A-Z][A-Z0-9 /&()-]{5,60}\s*$|"
    r"(?:Page|Para|Clause|S\.?No\.?|Sl\.?\.?|Item)\b)"
)


#: A clause that is only a table cell: a date, a time, a bracketed note, and
#: nothing that looks like prose or another label.
# The month alternation has to be wrapped. Unwrapped, the leading
# ``\d{1,2}...`` prefix binds only to the first month name and the rest of the
# pattern degrades into a bare ``february|november|...``, which is why this
# matched "07.05.2025" and not "07th May 2025".
_CELL_RE = re.compile(
    r"^[^A-Za-z]{0,4}(?:\(?\s*(?:upto|up\s*to|till|until)\b[^)]*\)?\s*)?"
    r"(?:(?:tentatively|provisionally|from)\s+)?"
    r"(?:\d{1,2}\s*(?:st|nd|rd|th)?(?:\s*(?:,|&|and)\s*\d{1,2}(?:st|nd|rd|th)?)*"
    r"(?:\s+of)?[\s-]+(?:" + MONTH_ALT + r")"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
    # the rest: digits and punctuation, or a time / weekday such as "(5:00 PM)"
    r"(?:[^A-Za-z]|\b(?:[ap]\.?\s?m\b\.?|hrs?\b|noon\b|ist\b|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day\b))*$",
    re.I,
)
MAX_ROW_CELLS = 4

#: A bracketed time note: the cell between two dates in the same row.
_NOTE_CELL_RE = re.compile(
    r"^\s*(?:\(?\s*(?:upto|up\s*to|till|until|on)\b[^)]*\)?|[:\-–]+)\s*$", re.I
)


#: A full day-level date, used to spot table cells.
_HAS_FULL_DATE = re.compile(
    rf"(?<![-\d/.])\d{{1,2}}\s*[-/.]\s*\d{{1,2}}\s*[-/.]\s*\d{{2,4}}(?![-\d])"
    rf"|(?<![-\d/.])\d{{1,2}}(?:st|nd|rd|th)?(?:\s+|\s*-\s*)(?:{MONTH_ALT})\.?(?:\s*,?\s*|\s*-\s*)\d{{4}}(?![\d])"
    rf"|(?<![-\d/.])\d{{4}}\s*[-/]\s*\d{{1,2}}\s*[-/]\s*\d{{1,2}}(?![-\d])",
    re.I,
)


_RUNS_ON = re.compile(r"(?:\bi\.\s?e\.|\bviz\.|\bas\s+on|\bw\.?e\.?f\.?)\s*[,:\-]?\s*$", re.I)


def unwrap_soft_breaks(text: str) -> str:
    """Join hard-wrapped lines into whole sentences, keeping real breaks.

    A break is treated as a *table cell boundary* -- and therefore hard --
    when the continuation is itself a bare cell, or when both sides carry a
    full date. A PDF text layer prints a date table as one line per cell, with
    no delimiters:

        Events
        Earlier Date
        Extended Date
        Online submission of application form
        07th May 2025
        (Upto 11:59 P.M.)
        12th May 2025

    Soft-wrapping that into one clause put the word "examination" from the fee
    row next to the fee row's date, and the fee row's date became the exam
    date. Keeping the breaks gives the row logic in `_row_dates_after`
    something to work with, and stops the pairing that produced the wrong
    value in the first place.

    The output is built by appending, never by mutating the last element. An
    earlier version joined onto ``out[-1]`` and then appended a hard break to
    it, so after the first hard break ``out[-1]`` held two lines and every
    later comparison was against the wrong text -- which is why
    "Last date for Payment" and the date under it ended up in different
    clauses, in a document that had no tables at all.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if not out:
            out.append(line)
            continue
        current = out[-1]
        following = line
        if not current.strip() or not following.strip():
            out.append(following)
            continue
        # "i.e." or "as on" at a line end always runs on to its value
        soft = _RUNS_ON.search(current) is not None or (
            not _SENTENCE_END.search(current)
            and not _NEW_CLAUSE_START.match(following)
            # A table row is "| a | b |": never join it into the row above.
            and "|" not in current
            and "|" not in following
            # A boundary beside a table cell is a cell boundary, not a soft
            # wrap. Only *that*, though: "will be held on 15.06.2026 at\n10:00
            # AM" is a sentence that happens to wrap after a date, and joining
            # it is exactly right. So the test is whether the continuation is
            # itself a cell, or whether both sides carry a full date -- which
            # is the earlier | extended case.
            and not (
                _CELL_RE.match(following)
                or _CELL_RE.match(current)
                or _NOTE_CELL_RE.match(following)
                or (_HAS_FULL_DATE.search(current) and _HAS_FULL_DATE.search(following))
            )
        )
        if soft:
            out[-1] = f"{current} {following}"
        else:
            out.append(following)
    return "\n".join(out)



# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

#: A clause holding this many full dates is a table or a schedule, not a
#: sentence, and "the date nearest the label" is a coin toss inside it.
#:
#: Found in the wild: NTA's "Extension of last date" press notice prints an
#: Earlier Date / Extended Date table whose cells arrive from the PDF text
#: layer as bare lines with no delimiters. Once soft-wrapped into one clause,
#: the word "examination" in the *fee* row paired with the fee row's date and
#: produced `exam_date = 2025-05-08` for an exam held on 25 June 2025. The
#: model then "verified" it at 0.61, because it was being asked about a
#: candidate the regex layer had already got wrong -- which is precisely the
#: failure this architecture is supposed to prevent, and why the ambiguity
#: flag lives here and not in the validator.
AMBIGUOUS_DATE_COUNT = 3


_INR = r"(?:rs\.?|inr|\u20b9|rupees?)"
_NUM = r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"


# --------------------------------------------------------------------------
# Clause splitting
# --------------------------------------------------------------------------

# A clause boundary is a newline, a semicolon, or a full stop that ends a
# sentence. Note what is *not* a boundary:
#
#   ":" -- Indian notices put the label and the value either side of a colon
#          ("Last date to apply: 22.02.2027") more often than not, and
#          splitting on it destroys the association on every one of them.
#   "." between digits -- "15.06.2027" and "Rs. 100" are single values.
#   "." before a lowercase letter -- "No. of Posts", "e.g.", "i.e."
_CLAUSE_SPLIT = re.compile(r"\n+|[;!?]|\.(?=\s+[A-Z])|\.\s*$")


def clauses(text: str) -> list[str]:
    """Split a page into clauses. A candidate's label and value must share one.

    The label and the value of a field have to end up in the same clause, or
    "last date to apply" on one line will happily pick up the exam date
    printed on the next.
    """
    out: list[str] = []
    for chunk in _CLAUSE_SPLIT.split(text):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


def parse_int(raw: str) -> int | None:
    """Parse an Indian-grouped or plain integer. ``1,04,233`` -> ``104233``."""
    try:
        return int(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

# 15.06.2027 | 15/06/2027 | 15-06-2027 | 15.06.27 | 06-15-2027
#
# The trailing guard deliberately does NOT exclude ".". A date at the end of a
# sentence is the single commonest position for one ("... will be held on
# 15.06.2026."), and excluding "." silently dropped every one of them. The
# guard only needs to stop a partial match inside a longer number or a
# hyphenated/slashed identifier.
_DATE_DMY = re.compile(
    r"(?<![-\d/.])(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2,4})(?![-\d])(?![-_/])"
)
# 2027-06-15
_DATE_YMD = re.compile(r"(?<![-\d/.])(\d{4})-(\d{1,2})-(\d{1,2})(?![-\d])(?![-_/])")
# 15th June 2027 | 15 June, 2027 | June 15, 2027 | 15th June
# 29th of January, 2021 | 18th & 19th July, 2024 (a day list gives its first day)
_DATE_TEXT_DMY = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:,|&|and)\s*\d{{1,2}}(?:st|nd|rd|th)?)*"
    rf"(?:\s+of)?(?:\s+|\s*-\s*)({MONTH_ALT})\.?(?:\s*-\s*|\s*,?\s*)(\d{{4}})?\b", re.I
)
_DATE_TEXT_MDY = re.compile(
    rf"\b({MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})?\b", re.I
)
# "in June 2027" / "during the month of June, 2027" -- month granularity only
_MONTH_YEAR = re.compile(rf"\b(?:in|during|for|of|scheduled for)\s+(?:the\s+month\s+of\s+)?({MONTH_ALT})\.?\s+(\d{{4}})\b", re.I)
_MONTH_YEAR_BARE = re.compile(rf"\b({MONTH_ALT})\s+(\d{{4}})\b", re.I)
# "1st/2nd week of June 2027", "first half of June 2027"
_PARTIAL_DAY = re.compile(
    rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)|first|second|third|last)\s*(?:week|half|fortnight)\s+of\s+({MONTH_ALT})\.?\s*(\d{{4}})\b",
    re.I,
)

#: Hedges that always mean the date itself is not fixed.
_HEDGE_NEAR = re.compile(
    r"\b(tentative|tentatively|proposed|proposing|expected|"
    r"indicative|likely|approximately|approx\.?|subject to change|subject to "
    r"approval|to be (?:confirmed|notified|declared|announced|intimated)|"
    r"may (?:be|change|be revised)|is likely|shall be notified|not yet "
    r"published|awaited|to be intimated|may change)\b",
    re.I,
)

#: "Provisional" and "tentative" hedge a *date* only when they modify it.
#: On a real notice "Provisional Answer Key", "provisional merit list" and
#: "tentative list of shortlisted candidates" are the names of documents, and
#: a date in the same sentence has nothing to do with them. Treating those as
#: hedges marked the UGC-NET exam date provisional, which it is not.
_DOCUMENT_NOUN = (
    r"(?:answer\s*keys?|question\s*papers?|merit\s*lists?|shortlist(?:ed)?|"
    r"list\s+of|score\s*cards?|select(?:ion)?\s+lists?|admission\s+lists?|"
    r"intimation|notices?|circulars?|letters?|orders?)"
)
_HEDGE_MODIFIES_DATE = re.compile(
    r"\b(?:tentative|tentatively|provisional|provisionally)\b(?!\s*" + _DOCUMENT_NOUN + r")",
    re.I,
)

#: Words that make a date *definitely* fixed even next to a hedge elsewhere
#: in the sentence.
_FIXED_NEAR = re.compile(
    r"\b(shall be|will be|is scheduled|scheduled on|is fixed|fixed on|"
    r"conducted on|examination will be held on|on)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ParsedDate:
    value: dt.date | None
    #: 'day' | 'month' | 'none'
    granularity: str
    text: str
    #: True when the text hedged around this date.
    hedged: bool
    partial: str | None = None  # e.g. "2nd week"

    @property
    def is_day(self) -> bool:
        return self.granularity == "day" and self.value is not None


def _mk_day(year: int, month: int, day: int, text: str, hedged: bool) -> ParsedDate:
    try:
        return ParsedDate(dt.date(year, month, day), "day", text.strip(), hedged)
    except ValueError:
        # 31 February, month 13. A real typo in a real notice, or an OCR
        # error. Either way it must not become a date.
        return ParsedDate(None, "none", text.strip(), hedged)


def _expand_year(raw: int, reference: dt.date) -> int:
    if raw >= 100:
        return raw
    # Two-digit year: 27 -> 2027. Window is chosen so that a notice written in
    # 2026 cannot accidentally mean 1997.
    century = reference.year // 100 * 100
    candidate = century + raw
    if candidate < reference.year - 1:
        candidate += 100
    return candidate


def _hedged(context: str) -> bool:
    """Does the text hedge *this date*?

    Two classes of hedge, and conflating them is a real error: a date in a
    sentence that also says "Provisional Answer Key" is not a provisional
    date, and storing it as one would show the candidate a countdown for a
    date the body fixed months ago.
    """
    return bool(_HEDGE_NEAR.search(context) or _HEDGE_MODIFIES_DATE.search(context))


def find_dates(text: str, reference: dt.date | None = None) -> list[ParsedDate]:
    """Every date in the text, with its granularity and hedge flag.

    Overlapping matches are deduplicated by position: "15.06.2027" matches the
    numeric pattern once and the text pattern never, but
    "15th June 2027" can be seen two ways, and a notice that prints
    "15.06.2027 (15th June 2027)" should yield one candidate, not two that
    disagree.
    """
    reference = reference or dt.date.today()
    text = normalise(text)
    out: list[ParsedDate] = []

    def context_for(start: int, end: int) -> str:
        """The sentence around a date, and only the sentence.

        A hedge three lines away says nothing about this date, and neither
        does one two sentences earlier. Bounding to the sentence is what
        stops "Provisional Answer Key for ... Examination conducted from
        25th June 2025" from marking the exam date provisional: there,
        "Provisional" qualifies the answer key, not the date.

        The window is capped so a notice with no sentence punctuation at all
        -- a PDF line wrapped mid-clause -- still gets a bounded look.
        """
        lo = max(0, start - 200)
        for stop in (".", ";", "\n"):
            position = text.rfind(stop, lo, start)
            if position != -1:
                lo = position + 1
        hi = end
        for stop in (".", ";", "\n"):
            position = text.find(stop, end, min(len(text), end + 200))
            if position != -1:
                hi = min(hi, position)
        return text[lo:hi]

    for match in _DATE_YMD.finditer(text):
        year, month, day = (int(g) for g in match.groups())
        out.append(_mk_day(year, month, day, match.group(0), _hedged(context_for(*match.span()))))

    for match in _DATE_DMY.finditer(text):
        a, b, c = (int(g) for g in match.groups())
        ctx = context_for(*match.span())
        if a > 31 or b > 31:
            continue
        # Disambiguate by magnitude. Where both readings are legal (a<=12,
        # b<=12) prefer DD-MM, which is what an Indian notice means; the
        # month-first form is nearly always written with the month spelled
        # out, which the text patterns catch.
        if a > 12:
            day, month = a, b
        else:
            day, month = a, b
        out.append(_mk_day(_expand_year(c, reference), month, day, match.group(0), _hedged(ctx)))

    for match in _DATE_TEXT_DMY.finditer(text):
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else None
        ctx = context_for(*match.span())
        if year is None:
            out.append(ParsedDate(None, "month", match.group(0), _hedged(ctx)))
        else:
            out.append(_mk_day(year, month, day, match.group(0), _hedged(ctx)))

    for match in _DATE_TEXT_MDY.finditer(text):
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        ctx = context_for(*match.span())
        if year is None:
            out.append(ParsedDate(None, "month", match.group(0), _hedged(ctx)))
        else:
            out.append(_mk_day(year, month, day, match.group(0), _hedged(ctx)))

    for pattern in (_MONTH_YEAR, _MONTH_YEAR_BARE):
        for match in pattern.finditer(text):
            month = MONTHS[match.group(1).lower()]
            year = int(match.group(2))
            out.append(
                ParsedDate(
                    dt.date(year, month, 1), "month", match.group(0),
                    _hedged(context_for(*match.span())),
                )
            )

    for match in _PARTIAL_DAY.finditer(text):
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        out.append(
            ParsedDate(
                dt.date(year, month, 1), "month", match.group(0),
                True,  # "2nd week of June" is never a fixed day
                partial=match.group(0),
            )
        )

    out.sort(key=lambda p: text.find(p.text))
    return _dedupe_dates(out)


def _dedupe_dates(dates: Sequence[ParsedDate]) -> list[ParsedDate]:
    """Collapse parses of the same date, keeping the most informative one."""
    out: list[ParsedDate] = []
    for candidate in dates:
        merged = False
        for existing in out:
            if existing.value is None or candidate.value is None:
                if existing.text == candidate.text:
                    merged = True
                    break
                continue
            if existing.value == candidate.value:
                merged = True
                # A day-granularity parse always beats a month parse, and a
                # hedged parse never un-hedges a clean one in the same spot.
                if existing.granularity != "day" and candidate.granularity == "day":
                    out[out.index(existing)] = candidate
                elif candidate.granularity == "day" and not existing.hedged and candidate.hedged:
                    pass
                elif existing.granularity == "month" and candidate.granularity == "day":
                    out[out.index(existing)] = candidate
                break
        if not merged:
            out.append(candidate)
    return out


# --------------------------------------------------------------------------
# Candidate
# --------------------------------------------------------------------------

#: Why we believe this candidate. Shown to the reviewer; the model never sees
#: it, because telling the model how confident the regex was would just
#: launder a guess through a calibrated head.
@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    kind: str  # 'date' | 'int' | 'text' | 'money' | 'pay'


FIELDS: tuple[Field, ...] = (
    Field("exam_date", "date of the examination", "date"),
    Field("registration_open", "date registration opens", "date"),
    Field("registration_deadline", "last date to apply", "date"),
    Field("payment_deadline", "fee payment deadline", "date"),
    Field("admit_card_from", "admit card availability", "date"),
    Field("admit_card_to", "admit card closing date", "date"),
    Field("result_date", "date of result", "date"),
    Field("vacancies", "number of vacancies", "int"),
    Field("fee", "application fee", "text"),
    Field("negative_marking", "negative marking", "text"),
    Field("mode", "mode of examination", "text"),
    Field("duration", "duration of the examination", "text"),
    Field("venue", "examination centres", "text"),
    Field("eligibility", "eligibility criteria", "text"),
    Field("pay", "pay scale", "pay"),
    Field("age_as_on", "age reference date", "date"),
)

FIELD_BY_KEY = {f.key: f for f in FIELDS}


@dataclass(slots=True)
class Candidate:
    """One possible value for one field, with everything needed to check it.

    ``hint`` is a deterministic prior in [0, 1] from label strength and
    proximity. It is **not** a confidence: it says how sure the *regex* is
    that it matched the right kind of sentence, and nothing about whether the
    document is telling the truth.
    """

    field: str
    #: String form. Dates are ISO ``YYYY-MM-DD``; ints are decimal.
    value: str
    hint: float = 0.5
    #: 'day' for a full date, 'month' for a coarser one, 'none' otherwise.
    granularity: str = "none"
    #: True when the surrounding text hedged. Forces ``provisional``.
    provisional: bool = False
    evidence: str = ""
    source_url: str = ""
    page: int | None = None
    chunk_index: int | None = None
    is_ocr: bool = False
    #: True when the label-value pairing could not be made unambiguously:
    #: the clause carries several full dates, so "the nearest one" is a guess.
    #: An ambiguous candidate is reported to a human and **never written**,
    #: however confident the model is about it. See AMBIGUOUS_DATE_COUNT.
    ambiguous: bool = False
    #: Optional structured payload for ``pay``.
    pay: dict[str, Any] | None = None
    raw: str = ""

    @property
    def key(self) -> str:
        return self.field


    def as_int(self) -> int | None:
        try:
            return int(self.value)
        except (TypeError, ValueError):
            return None

    def label(self) -> str:
        field = FIELD_BY_KEY.get(self.field)
        return field.label if field else self.field


# --------------------------------------------------------------------------
# Label patterns
# --------------------------------------------------------------------------

#: Each entry is (field key, pattern, base hint). The pattern is matched
#: against a *clause* (a line, or a sentence), never the whole page, so
#: "last date" on one line cannot attach a date printed two clauses later.
_LABEL_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("exam_date", re.compile(
        r"\b(date\s+of\s+(?:the\s+)?(?:main\s+|mains\s+|preliminary|prelims|written|"
        r"descriptive|final|actual|common)?\s*examin\w*|exam\w*\s+will\s+be\s+conducted|"
        r"examination\s+(?:date|shall\s+be\s+held|will\s+be\s+held|is\s+scheduled)|"
        r"conducted\s+on|exam\s+date|on\s+the\s+date\s+of\s+the\s+examination|"
        r"schedule\s+of\s+examination\w*|"
        r"conduct\s+the\s+[\w\s.-]{0,40}?(?:test|examination)\b[^.]{0,60}?\b(?:tentatively\s+)?on)\b", re.I), 0.85),
    # "The NTA will conduct UGC-NET June 2025 Examination ... from 25th June 2025"
    # and "The examination will be conducted from 01.06.2027 to 30.06.2027". These
    # are the two commonest real phrasings and neither matched the strong
    # patterns above.
    ("exam_date", re.compile(
        r"\b(?:will\s+be\s+)?conduct(?:s|ed)?\b|\bheld\s+on\b|\bscheduled\s+(?:on|for)\b|"
        r"\bexamination\s+will\s+be\b|\bfrom\s+(?:\d{1,2}(?:st|nd|rd|th)?[\s,]+)?(?:January|February|March|April|"
        r"May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|"
        r"Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)\b", re.I), 0.75),
    # A bare "Examination ... on <date>" is common and usually right, but it
    # is also the shape a stray date takes, so it scores below the labels.
    ("exam_date", re.compile(
        r"\b(?:examination|exam|prelims?|mains?|tier\s*[- ]?[ivx]+|paper\s*[- ]?[ivx]+)\b",
        re.I), 0.55),
    # Every branch is a complete phrase on purpose. An earlier version ended
    # the group with an optional object, so the bare words "last date "
    # matched on its own -- and the label then attached to whatever date
    # happened to be in the same clause, which on a real notice was the
    # date of the *previous* notice.
    ("registration_deadline", re.compile(
        r"\b(?:"
        r"last\s+date\s+to\s+apply"
        r"|last\s+date\s+for\s+(?:applying|application|registration|receipt|"
        r"online\s+application)"
        r"|last\s+date\s+of\s+(?:applying|application|registration|receipt|"
        r"submission)"
        r"|last\s+working\s+day"
        r"|last\s+date\s+of\s+online\s+(?:submission|registration|application)"
        r"|last\s+date\s+(?:of|for)\s+submitting\s+(?:the\s+)?(?:online\s+)?applications?"
        r"|last\s+date\s+and\s+time(?!\s+(?:for|of)\s+(?:the\s+)?(?:fee|payment|correction))"
        r"|registration\s+closing\s+(?:time\s+and\s+)?date"
        r"|last\s+date\s+for\s+fill\w*[\s-]*(?:up\s+)?(?:of\s+)?(?:the\s+)?(?:online\s+)?application"
        r"|(?:online\s+)?(?:registration|application)(?:\s+(?:process|window|portal))?"
        r"\s+(?:closes|will\s+close|will\s+be\s+closed)"
        r"|closing\s+of\s+(?:the\s+)?(?:online\s+)?(?:application|registration)(?:\s+portal)?"
        r"|closing\s+date(?:\s+of\s+(?:the\s+)?(?:online\s+)?"
        r"(?:application|registration))?"
        r"|date\s+of\s+closing(?:\s+of\s+(?:the\s+)?(?:online\s+)?application)?"
        r"|applications?\s+(?:will\s+be\s+received|are\s+invited)\s+up\s+to"
        r"|deadline\s+for\s+(?:applying|application|registration)"
        r"|deadline\s+to\s+apply"
        r"|on\s+or\s+before"
        # Real labels that are not about the *application*: a challenge window,
        # a fee-payment cut-off, a filing date. Each is a complete phrase for
        # the same reason the branches above are.
        r"|last\s+date\s+(?:and\s+time\s+)?(?:for|of|to)\s+(?:the\s+)?"
        r"(?:challenge|challenging|filing|uploading|downloading|payment)"
        # Table row labels rather than sentences. This is the shape NTA uses
        # in its extension notices, and the row that follows the label
        # carries an Earlier Date cell and an Extended Date cell.
        r"|(?:online\s+)?submission\s+of\s+(?:the\s+)?(?:online\s+)?"
        r"(?:application|exam(?:ination)?\s+form|form)"
        r")\b", re.I), 0.9),
    ("registration_open", re.compile(
        r"\b(commence\w*\s+(?:of\s+|from\s+|on\s+)?(?:the\s+)?(?:online\s+)?"
        r"(?:registration|application|filing|filling)|"
        r"registration\s+(?:opens?|commences?|starts?|begins?)|"
        r"(?:online\s+)?(?:application|registration)\s+(?:will\s+be\s+)?(?:open|"
        r"commence|start)\s+(?:on|from)|start\s+date\s+of\s+(?:registration|"
        r"online\s+application)|from\s+the\s+date\s+of\s+commencement|"
        r"opening\s+date\s+(?:of|for)\s+(?:the\s+)?(?:submission\s+of\s+)?(?:online\s+)?"
        r"(?:registration\s+of\s+)?(?:application|registration)s?|"
        r"opening\s+of\s+(?:the\s+)?(?:online\s+)?(?:application|registration)(?:\s+portal)?|"
        r"(?:online\s+)?(?:application|registration)(?:\s+(?:mode|window|portal))?\s+"
        r"(?:will\s+be\s+)?(?:opened|opens|begins)(?:\s+(?:w\.?e\.?f\.?|on|from|at))?|"
        r"start\s+(?:date\s+)?of\s+(?:the\s+)?online\s+(?:application|registration)|"
        r"start\s+date\s+for\s+.{0,80}?on-?line\s+application|"
        r"registration\s+start(?:ing)?\s+(?:time\s+and\s+)?date|"
        r"start\s+of\s+(?:the\s+)?online\s+application\s+process)\b", re.I), 0.9),
    ("payment_deadline", re.compile(
        r"\b(?:"
        r"fee\s+(?:must\s+be\s+)?paid\s+(?:on|by|not\s+later\s+than)"
        r"|payment\s+(?:deadline|on|by|not\s+later)"
        r"|last\s+date\s+(?:for|of)\s+(?:payment|paying)\s+of?\s*(?:the\s+)?fee"
        r"|date\s+of\s+payment\s+of?\s*(?:application\s+)?fee"
        r"|payments?\s+(?:should|must|can)\s+be\s+(?:made|completed)"
        r"|last\s+date\s+(?:for|of)\s+(?:the\s+)?(?:online\s+)?fee\s+payment"
        r"|last\s+date\s+for\s+submission\s+of\s+(?:the\s+)?fees?"
        r"|last\s+date\s+for\s+(?:online\s+|offline\s+)?payment\s+of\s+(?:the\s+)?"
        r"(?:examination\s+|application\s+)?fees?"
        # "Last date for submission of examination fee" -- the same table
        # shape as the application deadline, one row down.
        r"|last\s+date\s+(?:for|of)\s+(?:submission\s+of\s+)?(?:the\s+)?"
        r"(?:examination|application|online\s+application)\s+fees?"
        r")\b", re.I), 0.9),
    ("admit_card_from", re.compile(
        r"\b(admit\s*card|hall\s+ticket|e\W*admit\s*card|call\s+letter|"
        r"admission\s+card)\b.{0,160}?\b(will\s+be\s+)?(available|issued|uploaded|"
        r"released|published|admissible|downloadable|can\s+be\s+downloaded)\b", re.I), 0.85),
    # "Admit cards ... have been released today i.e. 22 June 2025" -- the date
    # follows the release verb, not the label, and a 160-character window
    # from the label would pick up the exam date in between instead.
    ("admit_card_from", re.compile(
        r"\b(?:released|issued|available|uploaded|published)\b\s*"
        r"(?:today\s*,?\s*)?(?:i\.?e\.?|on|with\s+effect\s+from|w\.?e\.?f\.?|from)\s*"
        r"[:\-]?\s*$", re.I), 0.9),
    ("admit_card_to", re.compile(
        r"\b(admit\s*card|hall\s+ticket|call\s+letter)\b.{0,70}?\b(closing\s+date|"
        r"valid\s+(?:up\s+)?(?:till|until|upto)|last\s+date\s+to\s+download|"
        r"exam\s+date)\b", re.I), 0.6),
    ("result_date", re.compile(
        r"\b(date\s+of\s+(?:publication\s+of\s+)?(?:the\s+)?result|"
        r"result\s+(?:will\s+be\s+)?(?:declared|published|announced|declared\s+on)|"
        r"declaration\s+of\s+(?:the\s+)?result|merit\s+list|"
        r"result\s+on|result\s+date)\b", re.I), 0.8),
    ("age_as_on", re.compile(
        r"\b(age\s+(?:limit|as\s+on|criteria|shall\s+not\s+exceed)|"
        r"as\s+on\s+\d|minimum\s+age|maximum\s+age|"
        r"upper\s+age\s+limit|born\s+(?:on|after|not\s+later\s+than)|"
        r"attained\s+the\s+age|age\s*\(\s*as\s+on|years?\s+as\s+on|age\s+criteri\w*|crucial\s+date|"
        r"cut[\s-]?off\s+date(?!\s+for\s+(?!(?:the\s+)?(?:purpose\s+of\s+)?(?:eligibility\s+in\s+)?age))|determined\s+as\s+on|"
        r"(?:calculated|reckoned|determined|counted)\s+(?:with\s+reference\s+to|as\s+on))\b", re.I), 0.7),
)

#: Text fields: the pattern defines what the value *is*, and the captured
#: clause becomes the stored prose.
_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("negative_marking", re.compile(
        r"\b(negative\s+marking|deduction\s+of\s+marks?|marks?\s+(?:will\s+be\s+)?"
        r"deducted|wrong\s+(?:answer|response)s?)\b", re.I), 0.85),
    ("negative_marking", re.compile(
        r"\bthere\s+(?:will\s+be|is)\s+no\s+negative\s+marking\b|"
        r"\bno\s+negative\s+marking\b", re.I), 0.9),
    ("mode", re.compile(
        r"\b(computer\s*based\s*test|\bcbt\b|online\s+examination|offline\s+examination|"
        r"omr\s*based|descriptive\s+paper|pen\s+and\s+paper|written\s+examination|"
        r"paper\s*based\s*examination|physical\s+mode|online\s+mode)\b", re.I), 0.7),
    ("eligibility", re.compile(
        r"\b(eligibility\s+criteri\w*|eligible\s+(?:if|only|to\s+apply)|"
        r"candidates?\s+(?:should|must)\s+(?:be|possess|hold)|"
        r"qualif\w+\s+(?:criteria|degree|examination)|educational\s+qualification)\b", re.I), 0.6),
    ("fee", re.compile(
        r"\b(application\s+fees?|fees?\s+(?:payable|payable\s+by|for)|"
        r"fee\s+(?:structure|details|table)|cost\s+of\s+application)\b", re.I), 0.7),
)

_VACANCY = re.compile(
    rf"\b(?:total\s+(?:no\.?|number)\s+of\s+)?(?:vacanc\w+|posts?|positions?|"
    rf"vacant\s+posts?)\b\s*(?:of|=|:|-)?\s*[:\-]?\s*{_NUM}"
    rf"|\b{_NUM}\s*(?:vacanc\w+|posts?|positions?|seats?)\b"
    rf"|\bno\.?\s+of\s+vacanc\w+\s*[:\-]?\s*{_NUM}",
    re.I,
)

_FEE_AMOUNT = re.compile(
    rf"{_INR}\s*\.?\s*{_NUM}\s*(?:/\s*-|-/\s*|-)?(?:\s*(?:only|per\s+(?:category|post|application)))?",
    re.I,
)
_FEE_BARE = re.compile(rf"\b{_NUM}\s*/-\s*(?:only)?\b", re.I)

_PAY_LEVEL = re.compile(
    r"\b(?:pay\s*(?:matrix)?\s*(?:level|band|scale)\s*|level\s*[-:]?\s*|"
    r"pay\s+level\s+|bps\s*[-:]?\s*)(\d{1,2})\b",
    re.I,
)
_PAY_LEVEL_PAIR = re.compile(
    r"\b(?:pay\s*(?:matrix)?\s*(?:level|band|scale)s?\s*)(\d{1,2})\s*(?:and|&|to|,|/)\s*(\d{1,2})\b",
    re.I,
)
_PAY_GRADE = re.compile(r"\b(?:grade\s+pay\s*(?:of)?\s*|grade\s*[-:]?\s*)(e-?[0-9]|[0-9])\b", re.I)
# 69,250 - 1,34,200 | Rs 21700-69100 | ₹ 24050 to 64480
# The currency is written once, not twice: "Rs 21700-69100" is how a state
# PSC prints a scale, and requiring "Rs" on both sides missed all of them.
_PAY_RANGE = re.compile(
    rf"{_INR}\s*\.?\s*{_NUM}\s*(?:-|–|—|to|and)\s*(?:{_INR}\s*\.?\s*)?{_NUM}", re.I
)
_PAY_INITIAL = re.compile(
    rf"initial\s+(?:basic\s+)?pay\s+(?:of\s+)?{_INR}\s*\.?\s*{_NUM}", re.I
)
_PAY_SCALE_WORDS = re.compile(
    rf"pay\s+scale\s+{_INR}\s*\.?\s*{_NUM}\s*(?:-|–|to)\s*{_INR}\s*\.?\s*{_NUM}", re.I
)

#: Phrases that name how the test itself is taken, with a prior each. "Apply
#: through online mode" or "written examination" says nothing about the mode.
_MODE_NORMALISE = (
    (re.compile(r"computer[\s-]*based\s+(?:test|exam\w*|mode)|\bcbt\b|"
                r"\bonline\s+(?:test|exam\w*)\b", re.I), "Online (CBT)", 0.7),
    (re.compile(r"\bomr\b[\s-]*(?:based|answer|response|sheet|mode|method)", re.I), "OMR", 0.7),
    (re.compile(r"pen[\s-]*(?:and|&)[\s-]*paper|offline\s+(?:mode|exam\w*|test)", re.I), "Offline", 0.5),
)
#: "OMR or CBT at the discretion of ..." leaves the mode open.
#: "Taking away ... OMR sheets, Rough Sheets": exam-hall rules, not the mode
_MODE_MATERIALS = re.compile(r"\b(?:taking\s+away|carry\w*\s+(?:away|out)|rough\s+sheets?)\b", re.I)
#: "fee ... online mode or offline mode": how to pay, not how the exam is sat
_MODE_PAYMENT = re.compile(r"\b(?:payment|fees?)\b", re.I)
_MODE_EITHER = re.compile(r"\bomr\b.{0,60}\b(?:cbt|computer)|\b(?:cbt|computer)\b.{0,60}\bomr\b", re.I)

_NEGATIVE_PHRASES = (
    (re.compile(r"(?:one[- ]?(?:fourth|quarter)|1/4|\b0\.25\b|-\s*0\.25)", re.I),
     "One-fourth of the marks assigned for each wrong answer"),
    (re.compile(r"(?:one[- ]?third|1/3|\b0\.33)", re.I),
     "One-third of the marks assigned for each wrong answer"),
    (re.compile(r"(?:one[- ]?half|1/2|\b0\.50)", re.I),
     "Half of the marks assigned for each wrong answer"),
    (re.compile(r"(?:one[- ]?fourth\s+of\s+the\s+marks?\s+assigned)", re.I),
     "One-fourth of the marks assigned for each wrong answer"),
    (re.compile(r"no\s+negative\s+marking", re.I), "No negative marking"),
    (re.compile(r"minus\s+(?:one|1)\s+mark", re.I), "-1 mark for each wrong answer"),
    (re.compile(r"one\s+mark\s+(?:will\s+be\s+)?deducted", re.I),
     "One mark deducted for each wrong answer"),
)

# --------------------------------------------------------------------------
# The finder
# --------------------------------------------------------------------------


def _clean_sentence(clause: str, limit: int = 300) -> str:
    clause = " ".join(clause.split())
    if len(clause) <= limit:
        return clause
    return clause[: limit - 1].rsplit(" ", 1)[0] + "…"


#: A disclaimer that applies to the whole document rather than to the clause
#: a date sits in. The NTA examination calendar is the canonical case: a
#: table of forty proposed dates, and one line at the bottom reading "Note:
#: Dates are tentative and subject to change owing to administrative,
#: academic, logistic or other unforeseen circumstances." Every date in that
#: table is provisional, and none of them is hedged in its own cell.
_DOCUMENT_HEDGE = re.compile(
    r"\bnote\s*[:\-]?\s*[^\n]{0,40}?\b(?:all\s+)?dates?\b[^\n]{0,80}?"
    r"\b(?:are|is|will\s+be|may\s+be)\s+"
    r"(?:tentative|provisional|proposed|indicative|subject\s+to\s+(?:change|revision))"
    r"|\b(?:all\s+)?dates?\s+(?:mentioned|given|stated|published)\s+"
    r"(?:above|herein|are|is)?\s*"
    r"(?:tentative|provisional|proposed|indicative)\b"
    r"|\btentative\s+(?:schedule|calendar|dates?)\b\s*[:,]?",
    re.I,
)

#: Column headers that mark a whole table as proposed. Same reason as above:
#: the hedge is in the header, not in the cell.
_TABLE_HEDGE = re.compile(
    r"\bproposed\s+dates?\b|\btentative\s+dates?\b|"
    r"\bindicative\s+dates?\b|\bprovisional\s+dates?\b",
    re.I,
)


def document_is_hedged(text: str) -> str | None:
    """Return the document-level hedging sentence, if there is one."""
    match = _DOCUMENT_HEDGE.search(text)
    if match:
        return " ".join(match.group(0).split())[:200]
    match = _TABLE_HEDGE.search(text)
    if match:
        return "table header: " + " ".join(match.group(0).split())[:120]
    return None


def find_candidates(
    text: str,
    source_url: str,
    *,
    pages: Sequence[tuple[int, str, bool]] | None = None,
    reference: dt.date | None = None,
) -> list[Candidate]:
    """Find every candidate value in a document.

    ``pages`` is ``(page_number, page_text, is_ocr)``. Without it the whole
    text is treated as one unit with no page numbers, which is what an HTML
    notice page is.
    """
    units: list[tuple[int | None, str, bool]] = []
    if pages:
        units = list(pages)
    else:
        units = [(None, text, False)]

    document_hedge = document_is_hedged(text)

    out: list[Candidate] = []
    for page_number, page_text, is_ocr in units:
        out.extend(
            _candidates_in_unit(page_text, page_number, is_ocr, source_url, reference)
        )

    out = _drop_stale_dates(out)
    out.extend(_age_on_closing_date(text, out))

    if document_hedge:
        # Demote every date the document states. This is the whole of rule 2:
        # a tentative date is `provisional`, not `confirmed` -- and it is
        # still stored, because a candidate wants to know it exists.
        for candidate in out:
            if candidate.granularity == "day" and candidate.field in _DATE_FIELDS:
                candidate.provisional = True
                candidate.evidence = (
                    f"{candidate.evidence}  [document-level hedge: {document_hedge}]"
                )
    return out


#: "age ... as on the closing date", "closing date ... treated as crucial date".
_AGE_ON_CLOSING = re.compile(
    r"(?:\bage\b|crucial\s+date|cut[\s-]?off\s+date(?!\s+for\s+(?!(?:the\s+)?(?:purpose\s+of\s+)?(?:eligibility\s+in\s+)?age)))[^.]{0,80}?\b(?:closing|last)\s+date"
    r"|\b(?:closing|last)\s+date[^.]{0,150}?\b(?:crucial|cut[\s-]?off)\s+date", re.I)


def _age_on_closing_date(text: str, found: list[Candidate]) -> list[Candidate]:
    """Age counted on the closing date: each deadline candidate is also the age cut-off."""
    match = _AGE_ON_CLOSING.search(normalise(text))
    if not match:
        return []
    return [replace(c, field="age_as_on", hint=c.hint * 0.9,
                    evidence=f"{_clean_sentence(match.group(0))} | {c.evidence}")
            for c in found if c.field == "registration_deadline"]


#: Words just before a date that make it a reference, not an event:
#: "OM dated 15.01.2018", "born before 02.04.1998", "issued on or after 01.04.2026".
_REFERENCE_BEFORE = re.compile(
    r"(?:\bdated|\bdt\.?|\bdtd\.?|\bvide|\bo\.?\s?m\.?(?:\s+no\.?)?|\bborn(?:\s+\w+){0,4}"
    r"|\bissued\s+(?:on\s+or\s+)?(?:after|before|on)|\bon\s+or\s+after|\bw\.?e\.?f\.?\s+\d)\s*[:\-]?\s*$",
    re.I)
#: A result named as a condition or a boundary, not an event with its own date.
_RESULT_CONDITION = re.compile(
    r"\b(?:having|has|have)\s+(?:been\s+)?declared\s+(?:the\s+|their\s+)?results?"
    r"|\bresults?\b[^.]{0,60}?\b(?:declared|published)\s+on\s+or\s+before"
    r"|\b(?:after|before|till|until)\s+(?:the\s+)?declaration\s+of", re.I)
#: "the 1st day of the month in which online registration commences i.e. <date>"
_IN_WHICH_BEFORE = re.compile(r"\bin\s+which\b[^.]{0,60}\bcommences?\b", re.I)
#: "as on" marks a cut-off date, which is only an answer for the age field.
_AS_ON_BEFORE = re.compile(r"\bas\s+on\s*[:\-]?\s*$", re.I)


#: A registration label before a "<date> to <date>" range.
_RANGE_LABEL = re.compile(
    r"\b(?:online\s+)?(?:registration|applications?|apply)\b", re.I)
#: Ranges about something else: corrections, late fees, admit cards, the exam.
_RANGE_OTHER = re.compile(
    r"\b(?:correction|edit|late\s+fee|admit|hall\s+ticket|exam(?:ination)?\s+(?:date|will)|"
    r"result|answer\s+key|counsell?ing)\b", re.I)
_RANGE_JOIN = re.compile(r"^\s*(?:\([^)]{0,30}\)\s*)?(?:to|till|until|up\s*to|–|-)\s*$", re.I)


def _range_candidates(clause: str, day_dates: Sequence[ParsedDate], page: int | None,
                      is_ocr: bool, source_url: str) -> list[Candidate]:
    """Open and close dates from "Registration: <date> to <date>"."""
    out: list[Candidate] = []
    for first, second in zip(day_dates, day_dates[1:]):
        a = clause.find(first.text)
        b = clause.find(second.text, a + len(first.text))
        if a < 0 or b < 0 or not _RANGE_JOIN.match(clause[a + len(first.text):b]):
            continue
        before = clause[max(0, a - 160):a]
        if not _RANGE_LABEL.search(before) or _RANGE_OTHER.search(clause[:a]):
            continue
        fields = [("registration_open", first), ("registration_deadline", second)]
        if re.search(r"\bfees?\b|payment", before, re.I):
            fields.append(("payment_deadline", second))
        for key, date in fields:
            out.append(Candidate(
                field=key, value=date.value.isoformat(),
                hint=max(0.05, 0.9 - (0.05 if is_ocr else 0.0) - (0.1 if date.hedged else 0.0)),
                granularity="day", provisional=date.hedged, evidence=_clean_sentence(clause),
                source_url=source_url, page=page, is_ocr=is_ocr, raw=date.text))
        break
    return out


#: Fields that name an event of this cycle; age_as_on is a cut-off, not an event.
_EVENT_FIELDS = frozenset({"exam_date", "registration_open", "registration_deadline",
                           "payment_deadline", "admit_card_from", "admit_card_to", "result_date"})
#: An event date this much older than the notice's newest date is history
#: ("graduated on or after 1st April 2021", "proposed on 26-06-2000").
STALE_DAYS = 730


def _drop_stale_dates(found: list[Candidate]) -> list[Candidate]:
    days = [dt.date.fromisoformat(c.value) for c in found
            if c.field in _EVENT_FIELDS and c.granularity == "day"]
    if not days:
        days = [dt.date.today()]
    # stale beside the newest date, and never older than ten years
    cutoff = max(max(days) - dt.timedelta(days=STALE_DAYS),
                 dt.date.today() - dt.timedelta(days=3650))
    return [c for c in found if not (c.field in _EVENT_FIELDS and c.granularity == "day"
                                     and dt.date.fromisoformat(c.value) < cutoff)]


def _drop_weak_claims(found: list[Candidate]) -> list[Candidate]:
    """In one clause, a weak exam-date match gives way to a stronger label on the same date."""
    best: dict[str, float] = {}
    for c in found:
        if c.field != "exam_date" and c.hint >= 0.8:
            best[c.value] = max(best.get(c.value, 0.0), c.hint)
    return [c for c in found if not (c.field == "exam_date" and c.hint < best.get(c.value, 0.0))]


_EXAM_WORD = re.compile(r"\b(?:exam\w*|test|cbt|prelims?|mains?)\b", re.I)
#: Words that make "on or before" an application deadline.
_APPLY_WORDS = re.compile(r"\b(?:appl(?:y|ied|ications?)|regist\w*|resume|cv|bio-?data)\b", re.I)


def _label_is_reference(clause: str, label: re.Match[str]) -> bool:
    """True when a label names another date rather than labelling this one."""
    # "after closing date for receipt of applications, a correction window of ..."
    if re.search(r"\b(?:after|beyond)\s+(?:the\s+)?$", clause[max(0, label.start() - 12):label.start()], re.I):
        return True
    # "on or before" is a deadline only in a sentence about applying
    if label.group(0).lower().startswith("on or before"):
        return (not _APPLY_WORDS.search(clause) or bool(_RESULT_CONDITION.search(clause))
                or bool(re.search(r"\bon\s+or\s+after\b", clause, re.I)))
    return False


def _reference_date(clause: str, date_text: str, field: str) -> bool:
    """True when the words before this date make it a reference, not an event."""
    at = clause.find(date_text)
    if at < 0:
        return False
    before = clause[max(0, at - 40):at]
    if field == "age_as_on" and re.search(r"as\s+on\s+dt\.?\s*:?\s*$", before, re.I):
        return False
    if _REFERENCE_BEFORE.search(before):
        return True
    # "having declared the result on or before <date>": the candidate's degree
    if field == "result_date" and _RESULT_CONDITION.search(clause):
        return True
    # "the month in which registration commences i.e. <date>" is an age rule
    if field != "age_as_on" and _IN_WHICH_BEFORE.search(clause[max(0, at - 80):at]):
        return True
    return field != "age_as_on" and bool(_AS_ON_BEFORE.search(before))


#: One table cell holding a count: "911", "1,538", "276*"; a dash is a zero.
_COUNT_CELL = re.compile(r"^\s*(\d{1,3}(?:,\d{2,3})+|\d{1,6})\s*\*?\s*$|^\s*(-{1,2}|–)\s*$")
#: The label of a table's total row.
_TOTAL_ROW = re.compile(
    r"^\s*(?:grand\s+)?total(?:\s+(?:no\.?\s+of\s+|number\s+of\s+)?(?:vacanc\w*|posts?))?\s*:?\s*$", re.I)
_VACANCY_WORD = re.compile(r"\bvacanc|\bposts?\b", re.I)
_MARKS_WORD = re.compile(r"\bmarks?\b|\bquestions?\b|\bduration\b", re.I)


def _count_runs(text: str) -> list[tuple[str, list[int], int]]:
    """Runs of count cells, one per line, with the line before them and their offset."""
    runs: list[tuple[str, list[int], int]] = []
    label, nums, start, offset = "", [], 0, 0
    for line in text.split("\n"):
        cell = _COUNT_CELL.match(line)
        if cell:
            if not nums:
                start = offset
            nums.append(parse_int(cell.group(1)) or 0 if cell.group(1) else 0)
        elif line.strip():
            if nums:
                runs.append((label, nums, start))
                nums = []
            label = line.strip()
        offset += len(line) + 1
    if nums:
        runs.append((label, nums, start))
    return runs


def _sum_cell(nums: Sequence[int]) -> int | None:
    """The first cell that is the sum of the two or more cells just before it."""
    for j in range(2, len(nums)):
        total = 0
        for i in range(j - 1, -1, -1):
            total += nums[i]
            if total == nums[j] and j - i >= 2 and nums[j] >= 10:
                return nums[j]
            if total > nums[j]:
                break
    return None


def _table_totals(text: str, page: int | None, is_ocr: bool, source_url: str,
                  ocr_penalty: float) -> list[Candidate]:
    """Vacancy totals read from tables printed one cell per line.

    A "Total" row gives its only number, or the cell that sums the category
    cells before it (UR+SC+ST+OBC+EWS = Total). Any other row whose cells sum
    this way is one post's total, a weaker guess.
    """
    out = []
    for label, nums, start in _count_runs(text):
        before = text[max(0, start - 3000):start]
        posts = [m.end() for m in _VACANCY_WORD.finditer(before)]
        if not posts:
            continue
        # a marks table ("Total: 570" marks) names marks nearer than posts
        marks = [m.end() for m in _MARKS_WORD.finditer(before)]
        if marks and marks[-1] > posts[-1]:
            continue
        if _TOTAL_ROW.match(label):
            value, hint = (nums[0] if len(nums) == 1 else _sum_cell(nums)), 0.9
        else:
            value, hint = _sum_cell(nums), 0.6
        if not value:
            continue
        out.append(Candidate(
            field="vacancies", value=str(value), hint=max(0.05, hint - ocr_penalty),
            evidence=_clean_sentence(f"{label}: {' '.join(map(str, nums))}"),
            source_url=source_url, page=page, is_ocr=is_ocr, raw=f"{label} {value}"))
    return out


def _candidates_in_unit(
    text: str, page: int | None, is_ocr: bool, source_url: str, reference: dt.date | None
) -> list[Candidate]:
    text = normalise(text)
    out: list[Candidate] = []

    # Every value on an OCR'd page is OCR output and can be wrong, so every
    # hint on such a page is discounted. Not by much: it is a prior, and the
    # reviewer is told separately via provenance.ocr.
    ocr_penalty = 0.08 if is_ocr else 0.0

    # tables are read cell per line, before soft breaks are joined
    out.extend(_table_totals(text, page, is_ocr, source_url, ocr_penalty))
    text = unwrap_soft_breaks(text)

    all_clauses = clauses(text)
    clause_start = len(out)
    for position, clause in enumerate(all_clauses):
        out[clause_start:] = _drop_weak_claims(out[clause_start:])
        clause_start = len(out)
        clause_dates = find_dates(clause, reference)
        day_dates = [d for d in clause_dates if d.is_day]
        month_dates = [d for d in clause_dates if d.granularity == "month"]

        # --- labelled dates ------------------------------------------------
        # A clause whose value lives in the bare date cells that follow it is
        # a *table row label*, not a sentence, and the two need different
        # handling. A weak pattern written for prose -- a bare "examination"
        # picking up the exam date -- must not fire inside a table, where the
        # same word appears in a fee row and in a correction-window row.
        row_dates = _row_dates_after(all_clauses, position) if not day_dates else []
        is_row_label = bool(row_dates)

        # where each label starts: a label's value never lies past the next one
        label_starts = sorted(m.start() for _, pat, _ in _LABEL_PATTERNS
                              for m in pat.finditer(clause) if not re.search(r"\d", m.group(0))
                              and not _IN_WHICH_BEFORE.search(clause[max(0, m.start() - 60):m.end()]))

        for key, pattern, base_hint in _LABEL_PATTERNS:
            if is_row_label and base_hint < 0.8:
                # Too weak to trust against a table. In the UGC-NET extension
                # notice this is the difference between the fee deadline
                # (13 May) becoming the exam date and not.
                continue
            for label_match in pattern.finditer(clause):
                if _label_is_reference(clause, label_match):
                    continue
                # a bare "from <month>" is an exam date only beside an exam word
                if (key == "exam_date" and label_match.group(0).lower().startswith("from")
                        and not _EXAM_WORD.search(clause)):
                    continue
                if (
                    _TABLE_ONLY_LABEL.fullmatch(label_match.group(0).strip())
                    and len(clause) > TABLE_LABEL_MAX_CLAUSE
                ):
                    # These phrases name a *table cell*, so they only count as
                    # a label when the whole clause is that cell. Mid-sentence
                    # they are just words: "...the public notice dated: 16 April
                    # 2025 regarding submission of online application form..."
                    # has the same words and the date is the notice's own
                    # date, not a deadline.
                    continue
                # "Label ⏎ : ⏎ Tentatively 4th ... of May, 2026": the value opens the next line
                next_line: list[ParsedDate] = []
                if (not row_dates and base_hint >= 0.8
                        and not find_dates(clause[label_match.end():], reference)):
                    next_line = _next_line_dates(all_clauses, position, reference)
                if not day_dates and not month_dates and not row_dates and not next_line:
                    continue
                if row_dates:
                    # A label with its value in the table cells that follow it.
                    day_dates = list(row_dates)
                    chosen_override = row_dates[-1]
                else:
                    chosen_override = None
                    # "Opening ⏎ 25 May ⏎ Closing" joined into one clause: a label
                    # with no date after it takes the next row's date, not the one before.
                    if not find_dates(clause[label_match.end():], reference):
                        after = _row_dates_after(all_clauses, position) or next_line
                        if after:
                            chosen_override = after[0]
                # Prefer a date near the label, then a month-level one.
                stop = next((st for st in label_starts if st >= label_match.end()), len(clause))
                ordered = sorted(
                    (d for d in clause_dates if not _reference_date(clause, d.text, key)
                     and clause.find(d.text) < stop),
                    key=lambda d: _distance(clause, label_match.end(), d.text),
                )
                chosen = chosen_override or next((d for d in ordered if d.is_day), None)
                if chosen is None and month_dates:
                    out.append(
                        _month_note(key, month_dates[0], clause, base_hint, page, is_ocr, source_url)
                    )
                    continue
                if chosen is None:
                    continue
                hint = base_hint
                proximity = _distance(clause, label_match.end(), chosen.text)
                hint += _proximity_bonus(proximity)
                if chosen_override is not None:
                    # The value is a table cell, so proximity means nothing.
                    # Several cells (earlier / extended date) need the table's
                    # column order, which this layer cannot read; one cell is
                    # simply the value.
                    ambiguous = len(row_dates) > 1
                else:
                    # A deadline label's value comes *after* it. "the public
                    # notice dated: 16 April 2025 regarding submission of
                    # online application form" has the date before the label,
                    # and pairing those two is how a notice's own date becomes
                    # an application deadline.
                    ambiguous = len(day_dates) >= AMBIGUOUS_DATE_COUNT
                    if _value_is_before(clause, label_match.end(), chosen.text):
                        hint -= 0.15
                if chosen.hedged:
                    hint -= 0.1
                if is_ocr:
                    hint -= 0.05
                if ambiguous:
                    # Not a lower-confidence guess to be outvoted by a better
                    # one: a flag that says the pairing was never made.
                    hint = min(hint, 0.15)
                out.append(
                    Candidate(
                        field=key,
                        value=chosen.value.isoformat(),
                        hint=min(0.99, max(0.05, hint)),
                        granularity="day",
                        provisional=chosen.hedged,
                        evidence=_clean_sentence(clause),
                        source_url=source_url,
                        page=page,
                        is_ocr=is_ocr,
                        ambiguous=ambiguous,
                        raw=chosen.text,
                    )
                )

        # --- application windows written as a range ------------------------
        out.extend(_range_candidates(clause, day_dates, page, is_ocr, source_url))

        # --- vacancy counts ------------------------------------------------
        for match in _VACANCY.finditer(clause):
            number = parse_int(match.group(1))
            if number is None or number <= 0 or number > 500000:
                continue
            out.append(
                Candidate(
                    field="vacancies",
                    value=str(number),
                    hint=max(0.05, (0.8 if re.search(r"total", clause, re.I) else 0.7) - ocr_penalty),
                    evidence=_clean_sentence(clause),
                    source_url=source_url,
                    page=page,
                    is_ocr=is_ocr,
                    raw=match.group(0),
                )
            )

        # --- fee prose -----------------------------------------------------
        # One fee candidate per clause, however many times it says "fee":
        # the rest are the same table.
        amounts = [m.group(0).strip() for m in _FEE_AMOUNT.finditer(clause)]
        amounts += [m.group(0).strip() for m in _FEE_BARE.finditer(clause)]
        if amounts and re.search(r"\bfee", clause, re.I):
            out.append(
                Candidate(
                    field="fee",
                    # The schema stores fee as prose *because* it is a
                    # per-category split, and the clause already says
                    # "Rs 100 for General, Rs 50 for SC/ST, nil for PwD".
                    # Synthesising a number list would drop the nil. So the
                    # clause is the value, and the amounts are kept in `raw`
                    # for the reviewer.
                    value=_summarise_fee(amounts, clause),
                    hint=0.7,
                    evidence=_clean_sentence(clause),
                    source_url=source_url,
                    page=page,
                    is_ocr=is_ocr,
                    raw="; ".join(amounts[:6]),
                )
            )

        # --- negative marking ---------------------------------------------
        for pattern, value in _NEGATIVE_PHRASES:
            if pattern.search(clause):
                out.append(
                    Candidate(
                        field="negative_marking",
                        value=value,
                        hint=0.85,
                        evidence=_clean_sentence(clause),
                        source_url=source_url,
                        page=page,
                        is_ocr=is_ocr,
                        raw=match_snippet(pattern, clause),
                    )
                )
                break

        # --- mode ----------------------------------------------------------
        for pattern, value, mode_hint in _MODE_NORMALISE:
            if _MODE_EITHER.search(clause) or _MODE_MATERIALS.search(clause):
                break
            if value == "Offline" and _MODE_PAYMENT.search(clause):
                continue
            if pattern.search(clause):
                out.append(
                    Candidate(
                        field="mode",
                        value=value,
                        hint=mode_hint,
                        evidence=_clean_sentence(clause),
                        source_url=source_url,
                        page=page,
                        is_ocr=is_ocr,
                        raw=clause[:120],
                    )
                )
                break

        # --- duration / venue, which are clause values --------------------
        out.extend(_clause_candidates(clause, page, is_ocr, source_url))

        # --- pay -----------------------------------------------------------
        pay = _pay_candidate(clause, page, is_ocr, source_url)
        if pay is not None:
            out.append(pay)

    if all_clauses:
        out[clause_start:] = _drop_weak_claims(out[clause_start:])

    # --- prose fields, which need a wider window than one clause -----------
    out.extend(_prose_candidates(text, page, is_ocr, source_url))
    return out


def _next_line_dates(all_clauses: Sequence[str], position: int,
                     reference: dt.date | None) -> list[ParsedDate]:
    """Day dates on the next line, past a lone ":" cell, when that line has no label of its own."""
    rest = [c for c in all_clauses[position + 1:position + 3] if not _NOTE_CELL_RE.match(c)]
    if not rest or any(h >= 0.8 and p.search(rest[0]) for _, p, h in _LABEL_PATTERNS):
        return []
    # the value opens the line: "Tentatively 4th, 5th ... of May, 2026 (...)"
    days = [d for d in find_dates(rest[0], reference) if d.is_day]
    return days if days and rest[0].find(days[0].text) <= 15 else []


def _row_dates_after(all_clauses: Sequence[str], position: int) -> list[ParsedDate]:
    """The dates in the run of bare table cells that follows a label clause.

    In an ``Earlier Date | Extended Date`` table the label sits in one cell
    and the values in the next two or three, and the *last* one is the current
    value -- the earlier date is a history, not a fact about the exam. So the
    caller takes the last, and marks the candidate ambiguous so it is reported
    rather than stored: reading a table's structure properly is beyond what
    this layer can do, and guessing is how a fee date becomes an exam date.
    """
    out: list[ParsedDate] = []
    for following in all_clauses[position + 1 :]:
        if len(out) >= MAX_ROW_CELLS:
            break
        if _NOTE_CELL_RE.match(following):
            # "(Upto 11:59 P.M.)" sits between two date cells and is part of
            # the row, not the end of it.
            continue
        if not _CELL_RE.match(following):
            break
        dates = [d for d in find_dates(following) if d.is_day]
        if not dates:
            break
        out.extend(dates)
    return out


#: Labels that name a table cell rather than a sentence. Only a label when
#: the clause is that cell and nothing else.
_TABLE_ONLY_LABEL = re.compile(
    r"(?:online\s+)?submission\s+of\s+(?:the\s+)?(?:online\s+)?"
    r"(?:application|exam(?:ination)?\s+form|form)",
    re.I,
)
TABLE_LABEL_MAX_CLAUSE = 80


def _value_is_before(clause: str, anchor: int, value_text: str) -> bool:
    """Does the value sit before the label rather than after it?"""
    position = clause.find(value_text)
    return position != -1 and position < anchor


def _distance(clause: str, anchor: int, value_text: str) -> int:
    pos = clause.find(value_text)
    if pos < 0:
        return 10_000
    return abs(pos - anchor)


def _proximity_bonus(distance: int) -> float:
    """A date 15 characters from "last date to apply" is not the same as one
    200 characters away in a paragraph of unrelated dates."""
    if distance <= 25:
        return 0.1
    if distance <= 60:
        return 0.05
    if distance <= 120:
        return 0.0
    return -0.1


def _month_note(
    key: str,
    parsed: ParsedDate,
    clause: str,
    hint: float,
    page: int | None,
    is_ocr: bool,
    source_url: str,
) -> Candidate:
    """A coarser-than-a-day date, kept as a note and never as a date.

    "Autumn 2026", "2nd week of June 2027" and "June 2027" are real
    information a candidate wants, and the data model says they go in prose
    rather than in a date field. Granularity ``month`` plus a value that is
    *not* a valid date is what stops it ever being written as one.
    """
    return Candidate(
        field=key,
        value=parsed.text,
        hint=min(0.6, hint),
        granularity="month",
        provisional=True,  # by definition not fixed
        evidence=_clean_sentence(clause),
        source_url=source_url,
        page=page,
        is_ocr=is_ocr,
        raw=parsed.text,
    )


def _summarise_fee(amounts: Sequence[str], clause: str = "") -> str:
    """One line of fee prose.

    Preferred: the clause itself, trimmed. It is verbatim from the notice and
    already carries the per-category split, including the "nil for PwD" that
    a synthesised number list would silently drop.

    Fallback (clause longer than 240 characters, which happens when a fee
    paragraph runs into the next one): the distinct amounts, in first-seen
    order, because a fee table repeats its header on every row.

    Either way the return is text, never a number. One fee is not a scalar.
    """
    cleaned = _clean_sentence(clause, 240) if clause else ""
    if cleaned and len(cleaned) <= 240:
        return cleaned
    seen: list[int] = []
    for amount in amounts:
        number = parse_int(re.sub(r"[^0-9]", "", amount))
        if number is None or number in seen:
            continue
        seen.append(number)
    if not seen:
        return cleaned
    return " / ".join(f"Rs {n}" for n in seen[:6])


def match_snippet(pattern: re.Pattern[str], clause: str, limit: int = 120) -> str:
    """The matched text plus a little context, for the reviewer."""
    match = pattern.search(clause)
    if not match:  # pragma: no cover - caller already matched
        return clause[:limit]
    lo = max(0, match.start() - 40)
    return " ".join(clause[lo : match.end() + 60].split())[:limit]


#: Window fields are the ones where the label names a *block* of text rather
#: than a value. ``eligibility`` is the only such field: a real notice prints
#: "ELIGIBILITY CRITERIA" and then five numbered conditions, and any of them
#: is part of the answer. Duration and venue are values, and are matched
#: clause-by-clause -- a 900-character window after "duration" on a real
#: notice returns the next three numbered clauses and calls it the duration.
_WINDOW_FIELDS = ("eligibility",)
_CLAUSE_FIELDS = ("duration", "venue")
_PROSE_WINDOW = 700


def _prose_candidates(
    text: str, page: int | None, is_ocr: bool, source_url: str
) -> list[Candidate]:
    """Fields whose value is prose.

    Clause fields are matched per clause and the clause is the value.
    Window fields (only ``eligibility``) take a bounded window after the
    label, stopping at the next numbered clause so one heading cannot swallow
    the rest of the notice.
    """
    out: list[Candidate] = []
    text = unwrap_soft_breaks(normalise(text))
    for key, pattern, base in _TEXT_PATTERNS:
        if key not in _WINDOW_FIELDS:
            continue
        for match in pattern.finditer(text):
            window = text[match.end() : match.end() + _PROSE_WINDOW]
            window = _stop_at_next_clause(window)
            value = _clean_sentence(window, 600).strip(" .;:")
            if not value or len(value) < 12:
                continue
            out.append(
                Candidate(
                    field=key,
                    value=value,
                    # A window is weaker evidence than a clause, and the
                    # schema wants eligibility as prose anyway, so this is
                    # never the sole basis for storing a value.
                    hint=base * 0.6,
                    evidence=_clean_sentence(
                        text[max(0, match.start() - 80) : match.end() + 240]
                    ),
                    source_url=source_url,
                    page=page,
                    is_ocr=is_ocr,
                    raw=match.group(0),
                )
            )
    return out


_NEXT_CLAUSE_RE = re.compile(r"\n\s*(?:\d{1,2}\s*[.)]|\(\d+\)|[A-Z][A-Z ]{6,40}\s*$)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def _stop_at_next_clause(window: str) -> str:
    """Trim a window at the next numbered clause or after two sentences."""
    match = _NEXT_CLAUSE_RE.search(window, 60)
    if match:
        window = window[: match.start()]
    parts = _SENTENCE_END_RE.split(window, 2)
    return " ".join(parts[:2]) if len(parts) > 1 else window


def _clause_candidates(
    clause: str, page: int | None, is_ocr: bool, source_url: str
) -> list[Candidate]:
    """Duration and venue, matched on the clause as a whole."""
    out: list[Candidate] = []
    for key in _CLAUSE_FIELDS:
        for pattern, base in _CLAUSE_FIELD_PATTERNS[key]:
            match = pattern.search(clause)
            if not match:
                continue
            value = _clean_sentence(clause, 260)
            if len(value) < 12:
                break
            out.append(
                Candidate(
                    field=key,
                    value=value,
                    hint=base,
                    evidence=_clean_sentence(clause),
                    source_url=source_url,
                    page=page,
                    is_ocr=is_ocr,
                    raw=match.group(0)[:80],
                )
            )
            break
    return out


_CLAUSE_FIELD_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
    # A number is mandatory. "Duration" as a table *header* is not a value,
    # and OCR of an exam calendar produces a header row that reads
    # "Name of Examination | Proposed Date(s) | Duration".
    "duration": (
        (
            re.compile(
                r"^(?=.{0,200}?\d).{0,70}?\b(duration|time\s+allowed)\b.{0,70}?$|"
                r"^.{0,30}?\b\d{1,3}\s*(?:hours?|hrs?|minutes?)\b.{0,50}?$",
                re.I,
            ),
            0.6,
        ),
    ),
    "venue": (
        (
            re.compile(
                r"^(?=.{0,200}?\d).{0,50}?\b(?:\d{2,5}\s+centres?|centres?\s+at|"
                r"examination\s+centres?|exam\s+centres?)\b.{0,110}?$",
                re.I,
            ),
            0.55,
        ),
    ),
}


def _pay_candidate(
    clause: str, page: int | None, is_ocr: bool, source_url: str
) -> Candidate | None:
    """Pay, which has three real vocabularies.

    Central bodies publish "Pay Matrix Level 7". States publish rupee ranges.
    PSUs publish a grade plus a range plus an initial basic pay. All three
    occur, and one exam can span levels or set a different scale per post --
    so the candidate keeps whatever the clause actually said and lets
    adjudication decide.
    """
    payload: dict[str, Any] = {}
    system: str | None = None
    hint = 0.0

    levels = sorted({int(n) for n in _PAY_LEVEL.findall(clause)})
    pair = _PAY_LEVEL_PAIR.search(clause)
    if pair:
        levels = sorted(set(levels) | {int(pair.group(1)), int(pair.group(2))})
    if levels:
        payload["levels"] = levels
        system = "pay_matrix" if re.search(r"pay\s*matrix|matrix\s*level", clause, re.I) else "scale"
        hint = max(hint, 0.85)

    grade = _PAY_GRADE.search(clause)
    if grade:
        payload["grade"] = grade.group(1).upper().replace("-", "")
        system = system or "scale"
        hint = max(hint, 0.8)

    rng = _PAY_RANGE.search(clause) or _PAY_SCALE_WORDS.search(clause)
    if rng:
        low, high = rng.group(1), rng.group(2)
        payload["low"], payload["high"] = parse_int(low), parse_int(high)
        system = system or "scale"
        hint = max(hint, 0.8)

    initial = _PAY_INITIAL.search(clause)
    if initial:
        payload["initial"] = parse_int(initial.group(1))
        hint = max(hint, 0.8)

    if not payload:
        return None

    return Candidate(
        field="pay",
        value=", ".join(
            part
            for part in (
                f"levels={payload['levels']}" if "levels" in payload else "",
                f"grade={payload['grade']}" if "grade" in payload else "",
                f"low={payload['low']}" if "low" in payload else "",
                f"high={payload['high']}" if "high" in payload else "",
                f"initial={payload['initial']}" if "initial" in payload else "",
            )
            if part
        ),
        hint=hint,
        evidence=_clean_sentence(clause),
        source_url=source_url,
        page=page,
        is_ocr=is_ocr,
        pay=payload,
        raw=clause[:140],
    )


# --------------------------------------------------------------------------
# Adjudication: many candidates -> at most one value per field
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Adjudication:
    """The single value chosen for a field, plus why and what it beat."""

    field: str
    chosen: Candidate | None
    rejected: list[Candidate] = field(default_factory=list)
    #: True when the winning candidate's label-value pairing was ambiguous.
    #: Distinct from `conflict`, which is about two candidates disagreeing.
    ambiguous: bool = False
    #: True when two candidates with comparable strength disagreed. A real
    #: conflict goes to a human; it is never resolved silently.
    conflict: bool = False
    #: Month-granularity findings kept as prose notes, never as dates.
    coarse_notes: list[Candidate] = field(default_factory=list)
    reason: str = ""

    @property
    def value(self) -> str | None:
        return self.chosen.value if self.chosen else None


def adjudicate(candidates: Iterable[Candidate]) -> dict[str, Adjudication]:
    """Pick at most one candidate per field.

    Ranking, in order:

    1. Day granularity beats month granularity, always. A month is prose.
    2. Higher ``hint`` (label strength + proximity).
    3. An earlier page, because a summary table at the front of a notice is
       the body stating its own answer, and a date buried on page 40 of a
       schedule is usually about something else.

    Provisional is never promoted. If the winning candidate is hedged, the
    stored date is ``provisional``, whatever its hint.
    """
    grouped: dict[str, list[Candidate]] = {}
    coarse: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.granularity == "month":
            coarse.setdefault(candidate.field, []).append(candidate)
            continue
        grouped.setdefault(candidate.field, []).append(candidate)

    out: dict[str, Adjudication] = {}
    for key, field_candidates in grouped.items():
        ranked = sorted(
            field_candidates,
            key=lambda c: (
                -_rank_hint(c),
                c.page if c.page is not None else 0,
            ),
        )
        chosen = ranked[0]
        distinct = {c.value for c in ranked}
        conflict = len(distinct) > 1
        reason = "single candidate" if len(ranked) == 1 else f"{len(ranked)} candidates"
        if chosen.provisional:
            reason += "; winning candidate is hedged in the source, so provisional"
        if chosen.is_ocr:
            reason += "; read from an OCR'd page"
        ambiguous = bool(chosen.ambiguous)
        if ambiguous:
            reason += (
                f"; AMBIGUOUS: the clause carries {AMBIGUOUS_DATE_COUNT}+ full dates, "
                "so the label could not be paired with one of them. Not stored."
            )
        out[key] = Adjudication(
            field=key,
            chosen=chosen,
            rejected=ranked[1:],
            conflict=conflict,
            ambiguous=ambiguous,
            coarse_notes=coarse.get(key, []),
            reason=reason,
        )
    # Fields with only month-level findings still deserve an entry: the
    # reviewer needs to see "we found June 2027 and it is not a date".
    for key, notes in coarse.items():
        if key not in out:
            out[key] = Adjudication(
                field=key, chosen=None, coarse_notes=notes,
                reason="only month-level dates found; nothing to store as a date",
            )
    return out


def _rank_hint(candidate: Candidate) -> float:
    if candidate.granularity != "day" and candidate.field in _DATE_FIELDS:
        return -1.0
    return candidate.hint


_DATE_FIELDS = frozenset(f.key for f in FIELDS if f.kind == "date")
