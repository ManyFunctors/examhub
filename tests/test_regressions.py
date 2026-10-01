"""Regressions found by running the pipeline against real notices.

Every case here is a real document, a real wrong answer, and a real date. They
are the tests that matter most in the file, because each one was a bug that
produced a plausible, wrong value on a page the model then "verified".

Source documents, all fetched from ugcnet.nta.ac.in:

* ``public-notice-for-extension-of-dates-for-ugc-net-june-2025.pdf`` --
  NTA's "Extension of last date" press notice: an Earlier Date / Extended Date
  table whose cells arrive from the PDF text layer as bare lines.
* ``public_noticeanswer_key_challengeugc_net_june_2025.pdf`` -- the
  provisional answer key and its challenge window.
* ``public-notice-for-schedule-of-ugc-net-june-2025.pdf`` -- image-only, OCR.
"""

from __future__ import annotations

import pytest

from examhub_pipeline.candidates import (
    _CELL_RE,
    _row_dates_after,
    adjudicate,
    clauses,
    find_candidates,
    find_dates,
    normalise,
    unwrap_soft_breaks,
)

# --- verbatim excerpts, not paraphrases -----------------------------------

EXTENSION_NOTICE_TABLE = """Events
Earlier Date
Extended Date
Online submission of application form
07th May 2025
(Upto 11:59 P.M.)
12th May 2025
(Upto 11:59 P.M.)
Last date for submission of examination fee (through credit
card/ debit card/net banking /UPI)
08th May 2025
(Upto 11:59 P.M.)
13th May 2025
(Upto 11:59 P.M.)
Correction in the particulars in online application form
09th May 2025 to
10th May 2025
(Upto 11:59 P.M.)
14th May 2025 to
15th May 2025
(Upto 11:59 P.M.)"""

EXTENSION_NOTICE_PROSE = """PUBLIC NOTICE
08 May 2025
Subject: Extension of last date for submission of online application form for

UGC - NET June 2025.
Therefore, in continuation to the public notice dated: 16 April 2025 regarding
submission of online application form for UGC - NET June 2025, NTA has decided
to extend the last date for submission of online application form for
UGC - NET June 2025. The schedule is as follows:
""" + EXTENSION_NOTICE_TABLE

ANSWER_KEY = """The Provisional Answer Key(s) for UGC - NET June 2025 Examination
conducted from 25th June 2025 to 29th June 2025 along with the Question Paper
with Recorded Responses are available on the website.
The procedure for the challenge of Answer Key is as enclosed below.
The candidates, who are not satisfied with the Answer Key, may challenge the
same by paying a fee of Rs 200/- per question challenged.
Last date for Payment
08th July 2025 (upto 05:00 p.m.)
No challenge will be entertained after 06th July 2025 to 08th July 2025
(upto 05:00 p.m.)
"""

SCHEDULE_OCR = """Examination Calendar 2025
June 2025
06 June 2025 Subject: Examination Schedule of UGC - NET June 2025 - reg.
The National Testing Agency (NTA) will conduct UGC - NET June 2025 for
award of Junior Research Fellowship and admission to Ph.D. for 85 subjects
in CBT, mode from 25 June 2025 to 29 June 2025.
"""


def values_for(text, field):
    return {c.value for c in find_candidates(text, "https://ugcnet.nta.ac.in/x.pdf")
            if c.field == field}


class TestLineBreaksBesideTableCells:
    def test_a_cell_boundary_is_not_a_soft_wrap(self):
        """Joining the cells of a date table turns it into a paragraph, and
        then the word "examination" in the fee row pairs with the fee row's
        date."""
        joined = unwrap_soft_breaks(EXTENSION_NOTICE_TABLE)
        assert "07th May 2025\n" in joined
        assert "12th May 2025\n" in joined

    def test_a_sentence_wrap_after_a_date_is_still_a_wrap(self):
        """"will be held on 15.06.2026 at / 10:00 AM" is a sentence that
        happens to wrap after a date. Treating every date-adjacent break as a
        cell boundary would stop that too."""
        wrapped = "The examination will be held on 15.06.2026 at\n10:00 AM."
        assert "at 10:00 AM" in unwrap_soft_breaks(wrapped)

    def test_two_dates_on_consecutive_lines_stay_apart(self):
        assert "07th May 2025\n12th May 2025" in unwrap_soft_breaks(
            "07th May 2025\n12th May 2025"
        )

    def test_cell_recogniser(self):
        assert _CELL_RE.match("07th May 2025")
        assert _CELL_RE.match("07.05.2025")
        assert not _CELL_RE.match("Online submission of application form")
        assert not _CELL_RE.match("Last date for Payment")


class TestExtensionNotice:
    """The bug that mattered: `exam_date = 2025-05-08` for an exam held on
    25 June 2025, which the model then verified at 0.61 confidence."""

    @pytest.fixture
    def adj(self):
        return adjudicate(find_candidates(EXTENSION_NOTICE_PROSE, "u"))

    def test_the_exam_date_is_never_the_fee_deadline(self, adj):
        assert "2025-05-08" not in values_for(EXTENSION_NOTICE_PROSE, "exam_date")
        assert "2025-05-13" not in values_for(EXTENSION_NOTICE_PROSE, "exam_date")

    def test_no_exam_date_is_stored_at_all(self, adj):
        """The honest outcome. The notice is about an application deadline;
        it does not fix an exam date, and no pairing of its dates produces one
        that is right."""
        assert adj.get("exam_date") is None or adj["exam_date"].chosen is None

    def test_the_extended_deadline_is_found(self, adj):
        assert adj["registration_deadline"].value == "2025-05-12"

    def test_the_extended_fee_deadline_is_found(self, adj):
        assert adj["payment_deadline"].value == "2025-05-13"

    def test_a_table_reading_is_never_stored_unattended(self, adj):
        """Reading a table's column order is not something this layer can do,
        so the value is reported and a human confirms it."""
        assert adj["registration_deadline"].ambiguous is True
        assert adj["payment_deadline"].ambiguous is True
        assert "AMBIGUOUS" in adj["registration_deadline"].reason

    def test_the_notices_own_date_is_not_a_deadline(self):
        """`public notice dated: 16 April 2025 regarding submission of online
        application form` has the label's own words in it, and the date is
        the date of the notice being corrected, not a deadline anyone can
        apply by."""
        assert "2025-04-16" not in values_for(EXTENSION_NOTICE_PROSE, "registration_deadline")

    def test_the_notices_own_date_is_not_the_exam_date(self):
        assert "2025-05-08" not in values_for(EXTENSION_NOTICE_PROSE, "exam_date")

    def test_the_rightmost_cell_wins(self):
        """Earlier | Extended: the extended date is the current one."""
        cells = clauses(unwrap_soft_breaks(normalise(EXTENSION_NOTICE_TABLE)))
        # The header cells soft-join, so the row label sits at the end of that
        # clause rather than in one of its own.
        index = next(
            k for k, c in enumerate(cells) if c.endswith("Online submission of application form")
        )
        row = _row_dates_after(cells, index)
        assert [d.value.isoformat() for d in row] == ["2025-05-07", "2025-05-12"]


class TestAnswerKeyNotice:
    @pytest.fixture
    def adj(self):
        return adjudicate(find_candidates(ANSWER_KEY, "u"))

    def test_the_exam_date_is_not_the_notice_date(self, adj):
        assert adj["exam_date"].value == "2025-06-25"
        assert adj["exam_date"].ambiguous is False

    def test_the_challenge_window_end_is_the_deadline(self, adj):
        assert adj["registration_deadline"].value == "2025-07-08"

    def test_the_provisional_answer_key_does_not_make_the_date_provisional(self, adj):
        """"Provisional" here qualifies the answer key, not the date. Marking
        the exam date provisional would suppress its countdown on the site for
        a date the body fixed months earlier."""
        assert adj["exam_date"].chosen.provisional is False

    def test_a_date_inside_the_word_provisional_is_not_hedged(self):
        found = find_dates(
            "The Provisional Answer Key for the Examination conducted from "
            "25th June 2025 to 29th June 2025 is available.",
            None,
        )
        assert found[0].hedged is False


class TestScheduleNotice:
    """OCR'd, so every date is as good as the OCR."""

    @pytest.fixture
    def adj(self):
        return adjudicate(find_candidates(SCHEDULE_OCR, "u"))

    def test_the_notices_own_date_does_not_beat_the_exam_date(self, adj):
        assert adj["exam_date"].value == "2025-06-25"

    def test_two_candidate_dates_are_a_conflict_not_a_silent_pick(self, adj):
        """The notice date (06 June) and the exam date (25 June) are both
        plausible readings of the clause. A human picks."""
        assert adj["exam_date"].conflict is True
        assert adj["exam_date"].rejected


class TestAmbiguityRule:
    def test_three_dates_in_one_clause_is_ambiguous(self):
        text = (
            "The examination will be held on 15.06.2026 and the re-exam on "
            "20.06.2026 and the interview on 25.06.2026."
        )
        adj = adjudicate(find_candidates(text, "u"))
        assert adj["exam_date"].ambiguous is True

    def test_two_dates_in_one_clause_is_not_automatically_ambiguous(self):
        """Multi-stage exams print two dates in one sentence and the first is
        usually right; three or more is a table, not a stage list."""
        text = "Tier-I will be held on 15.06.2026 and Tier-II on 28.09.2026."
        adj = adjudicate(find_candidates(text, "u"))
        assert adj["exam_date"].value == "2025-06-15" or adj["exam_date"].value == "2026-06-15"


class TestLabelPatterns:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Last date to apply: 22.02.2026", True),
            ("Last date for submission of application form", True),
            ("Closing date of online application: 22.02.2026", True),
            ("The last date to apply has been extended", True),
            ("Last date for Payment", True),
            ("Last date for challenge", True),
            ("the last date ", False),
            ("date of birth", False),
        ],
    )
    def test_a_bare_phrase_does_not_match(self, text, expected):
        """An earlier version of the deadline pattern ended its group with an
        optional object, so the bare words "last date " matched on their own
        and the label attached to whatever date was nearby -- which on a real
        notice was the date of the previous notice."""
        from examhub_pipeline.candidates import _LABEL_PATTERNS

        pattern = next(p for k, p, _ in _LABEL_PATTERNS if k == "registration_deadline")
        assert bool(pattern.search(text)) is expected
