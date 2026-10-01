"""Tests for the deterministic "find" layer.

These matter more than any other tests in the project: the model never
extracts anything, so if a value is not found by these regexes it is never
found at all, and if a value is found wrongly the model is the only thing
standing between it and front matter.

The cases below are taken from the shapes real notices use, not invented ones.
"""

from __future__ import annotations

import datetime as dt

import pytest

from examhub_pipeline.candidates import (
    Adjudication,
    adjudicate,
    clauses,
    document_is_hedged,
    find_candidates,
    find_dates,
    normalise,
    parse_int,
    unwrap_soft_breaks,
)

REF = dt.date(2026, 9, 27)


# --------------------------------------------------------------------------
# Date parsing
# --------------------------------------------------------------------------


class TestDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("on 15.06.2026", dt.date(2026, 6, 15)),
            ("on 15/06/2026", dt.date(2026, 6, 15)),
            ("on 15-06-2026", dt.date(2026, 6, 15)),
            ("on 2026-06-15", dt.date(2026, 6, 15)),
            ("15 June 2026", dt.date(2026, 6, 15)),
            ("15th June 2026", dt.date(2026, 6, 15)),
            ("June 15, 2026", dt.date(2026, 6, 15)),
            ("15.06.26", dt.date(2026, 6, 15)),
            ("5th March, 2027", dt.date(2027, 3, 5)),
        ],
    )
    def test_day_forms(self, text, expected):
        found = [d for d in find_dates(text, REF) if d.is_day]
        assert found, f"no day-granularity date found in {text!r}"
        assert found[0].value == expected

    def test_zero_padding_is_not_required(self):
        # "1.2.2026" and "01.02.2026" are the same day and must not be two
        # candidates that disagree.
        found = [d.value for d in find_dates("01.02.2026 and 1.2.2026", REF) if d.is_day]
        assert set(found) == {dt.date(2026, 2, 1)}

    @pytest.mark.parametrize(
        "text",
        [
            "during June 2027",
            "in June 2027",
            "June 2027",
            "2nd week of June 2027",
            "first half of June 2027",
        ],
    )
    def test_month_granularity_is_never_a_day(self, text):
        """The data model's rule: coarser than a day is prose, not a date.

        This is the single most important assertion in the file. A day
        invented out of a month is a false fact on the site.
        """
        found = find_dates(text, REF)
        assert found, f"nothing found in {text!r}"
        assert all(d.granularity == "month" for d in found), (
            f"{text!r} produced a day-granularity date: {found}"
        )
        assert all(d.value is None or d.value.day == 1 for d in found)

    def test_partial_day_is_always_provisional(self):
        found = find_dates("2nd week of June 2027", REF)
        assert found[0].partial is not None
        assert found[0].hedged is True

    @pytest.mark.parametrize("text", ["31.02.2027", "45.06.2027", "15.13.2027"])
    def test_impossible_dates_are_rejected(self, text):
        """A real typo in a real notice must not become a date."""
        found = find_dates(text, REF)
        assert all(not d.is_day for d in found), found

    def test_two_digit_year_window(self):
        # A notice written in 2026 saying "15.06.27" means 2027, not 1997.
        found = [d for d in find_dates("15.06.27", REF) if d.is_day]
        assert found[0].value == dt.date(2027, 6, 15)

    def test_hedge_detection(self):
        hedged = find_dates("the tentative date is 15.06.2027", REF)[0]
        assert hedged.hedged is True
        clean = find_dates("the examination will be held on 15.06.2027", REF)[0]
        assert clean.hedged is False

    def test_provisional_answer_key_does_not_hedge_the_date(self):
        """"Provisional" qualifying a document is not a hedge on a date.

        This was a real false positive: UGC-NET's provisional-answer-key notice
        marked the (fixed) exam date as provisional because the phrase
        "Provisional Answer Key" sat in the same sentence.
        """
        text = (
            "The Provisional Answer Key(s) for UGC NET June 2025 Examination "
            "conducted from 25th June 2025 to 29th June 2025 are available."
        )
        assert find_dates(text, REF)[0].hedged is False

    def test_provisional_date_still_hedges(self):
        text = "The provisional date of the examination is 15.06.2027."
        assert find_dates(text, REF)[0].hedged is True

    def test_dedupe_same_date_two_spellings(self):
        found = find_dates("15.06.2026 (15th June 2026)", REF)
        days = [d.value for d in found if d.is_day]
        assert len(days) == 1


# --------------------------------------------------------------------------
# Normalisation and clause splitting
# --------------------------------------------------------------------------


class TestNormalisation:
    def test_rupee_sign_folds(self):
        # The rupee sign folds to ASCII "Rs" with no space; every fee and pay
        # pattern allows \s* after the currency, so "Rs100" and "Rs 100" are
        # both matched.
        assert normalise("₹100") == "Rs100"
        assert normalise("₹ 100") == "Rs 100"

    def test_fullwidth_digits_fold(self):
        # Several .nic.in portals emit fullwidth digits. NFKC handles it.
        assert normalise("１５.０６.２０２６") == "15.06.2026"

    def test_en_dash_folds(self):
        assert normalise("15–06–2026") == "15-06-2026"

    def test_soft_wraps_join(self):
        wrapped = (
            "The examination will be held on 15.06.2026 at\n"
            "10:00 AM at all centres.\n"
            "Last date to apply: 22.02.2026"
        )
        assert "15.06.2026 at 10:00 AM" in unwrap_soft_breaks(wrapped)

    def test_soft_wrap_joins_across_a_numbered_clause(self):
        wrapped = "1. The examination will be held on 15.06.2026 at\n10:00 AM."
        # "10:" does not start a new clause, so this one *should* join.
        assert "at 10:00 AM" in unwrap_soft_breaks(wrapped)

    def test_numbered_clause_starts_a_new_line(self):
        wrapped = "The fee is Rs 100 per candidate.\n2. Eligibility criteria"
        assert "\n2. Eligibility" in unwrap_soft_breaks(wrapped)

    def test_table_rows_never_join(self):
        wrapped = "Category | Fee\nGeneral | Rs 100"
        joined = unwrap_soft_breaks(wrapped)
        assert joined.count("|") == 2
        assert "\n" in joined

    def test_colon_is_not_a_clause_boundary(self):
        """Indian notices put the label and value either side of a colon.

        Splitting on ":" destroys the association on essentially every real
        notice, which is how "Last date to apply: 22.02.2026" ends up with
        the deadline and the exam date swapped.
        """
        parts = clauses("Last date to apply: 22.02.2026 up to 23:00 hours")
        assert len(parts) == 1
        assert "22.02.2026" in parts[0]

    def test_sentence_boundary_still_splits(self):
        parts = clauses("The fee is Rs 100. The exam is on 15.06.2026.")
        assert len(parts) == 2


class TestParseInt:
    @pytest.mark.parametrize(
        "raw,expected",
        [("1,044", 1044), ("1044", 1044), ("1,04,233", 104233), ("14,500", 14500)],
    )
    def test_indian_grouping(self, raw, expected):
        assert parse_int(raw) == expected

    def test_garbage(self):
        assert parse_int("not a number") is None


# --------------------------------------------------------------------------
# The finder
# --------------------------------------------------------------------------


class TestFindCandidates:
    @pytest.fixture
    def found(self, ssc_notice):
        """The adjudicated winner per field, not the last candidate found.

        A field with several candidates is the normal case, so the assertions
        below have to test the decision, not the iteration order.
        """
        adj = adjudicate(find_candidates(ssc_notice, "https://ssc.gov.in/notice.pdf"))
        return {field: entry.chosen for field, entry in adj.items() if entry.chosen}

    def test_exam_date(self, found):
        assert found["exam_date"].value == "2026-06-15"
        assert found["exam_date"].granularity == "day"
        assert found["exam_date"].provisional is False

    def test_registration_open(self, found):
        assert found["registration_open"].value == "2026-02-01"

    def test_registration_deadline(self, found):
        assert found["registration_deadline"].value == "2026-02-22"

    def test_vacancies(self, found):
        assert found["vacancies"].value == "1044"

    def test_vacancies_ignores_absurd_numbers(self):
        cands = find_candidates("Total posts: 999999", "u")
        assert all(c.field != "vacancies" for c in cands)

    def test_fee_keeps_the_per_category_split(self, found):
        fee = found["fee"].value
        assert "100" in fee and "50" in fee
        assert "nil" in fee.lower(), "the nil case must survive; a scalar would drop it"

    def test_negative_marking(self, found):
        assert "one-fourth" in found["negative_marking"].value.lower()

    def test_mode(self, found):
        assert found["mode"].value == "Online (CBT)"

    def test_pay_level_is_a_list_because_one_exam_can_span_levels(self):
        cands = find_candidates("Posts carry Pay Level 2 and 3.", "u")
        pay = [c for c in cands if c.field == "pay"]
        assert pay and set(pay[0].pay["levels"]) == {2, 3}
        assert pay[0].pay["levels"] == sorted(pay[0].pay["levels"])

    def test_pay_range(self):
        cands = find_candidates("The scale is Rs 21700-69100 for constables.", "u")
        pay = [c for c in cands if c.field == "pay"]
        assert pay[0].pay["low"] == 21700 and pay[0].pay["high"] == 69100

    def test_no_invented_negative_marking(self):
        cands = find_candidates("There will be no negative marking.", "u")
        values = [c.value for c in cands if c.field == "negative_marking"]
        assert values and "no negative" in values[0].lower()

    def test_evidence_is_always_captured(self, ssc_notice):
        for candidate in find_candidates(ssc_notice, "u"):
            assert candidate.evidence, f"{candidate.field} has no evidence string"

    def test_a_label_cannot_reach_across_clauses(self):
        """The whole point of clause scoping.

        "Last date to apply" on one line and an exam date on the next must
        not produce a candidate that pairs them.
        """
        text = "Last date to apply:\nThe examination will be held on 15.06.2026."
        by_field = {c.field: c for c in find_candidates(text, "u")}
        assert "2026-06-15" not in by_field.get("registration_deadline", _none()).value

    def test_month_only_notice_yields_no_date_candidate(self):
        cands = find_candidates(
            "The tentative schedule is in June 2027 and the exam will be held then.", "u"
        )
        for c in cands:
            if c.field in {"exam_date", "registration_deadline"}:
                assert c.granularity == "month"
                with pytest.raises(ValueError):
                    dt.date.fromisoformat(c.value)

    def test_ocr_pages_are_marked_and_discounted(self):
        pages = [(1, "The examination will be held on 15.06.2026.", True)]
        clean = find_candidates("The examination will be held on 15.06.2026.", "u")
        dirty = find_candidates("", "u", pages=pages)
        assert dirty[0].is_ocr is True
        assert dirty[0].hint < max(c.hint for c in clean)


def _none():
    class _Empty:
        value = ""

    return _Empty()


# --------------------------------------------------------------------------
# Document-level hedging
# --------------------------------------------------------------------------


class TestDocumentHedge:
    def test_exam_calendar_disclaimer(self):
        text = (
            "Examination Calendar 2027\n"
            "| 8 NIFT Entrance Examination 10 January 2027 1 Day\n"
            "Note: Dates are tentative and subject to change owing to "
            "administrative, academic or other unforeseen circumstances."
        )
        assert document_is_hedged(text)
        candidates = find_candidates(text, "u")
        dates = [c for c in candidates if c.granularity == "day"]
        assert dates
        assert all(c.provisional for c in dates), (
            "a document that says all its dates are tentative must not yield "
            "a confirmed date"
        )

    def test_proposed_date_column_header(self):
        text = "S. No. Name of Examination Proposed Date(s)\n1 RIMC 06 Dec 2026"
        assert document_is_hedged(text)
        assert all(c.provisional for c in find_candidates(text, "u") if c.granularity == "day")

    def test_no_disclaimer_means_no_hedge(self, ssc_notice):
        assert document_is_hedged(ssc_notice) is None


# --------------------------------------------------------------------------
# Adjudication
# --------------------------------------------------------------------------


class TestAdjudication:
    def test_one_value_per_field(self, ssc_notice):
        adj = adjudicate(find_candidates(ssc_notice, "u"))
        assert isinstance(adj["exam_date"], Adjudication)
        assert adj["exam_date"].value is not None
        assert all(c.field == "exam_date" for c in adj["exam_date"].rejected)

    def test_strongest_label_wins(self):
        text = (
            "The examination is referred to in general terms on 01.01.2020.\n"
            "Last date to apply: 22.02.2026 up to 23:00 hours."
        )
        candidates = find_candidates(text, "u")
        adj = adjudicate(candidates)
        # The deadline label is stronger than a bare "examination" mention, and
        # the wrong-date candidate must not win on the exam_date field.
        assert adj["registration_deadline"].value == "2026-02-22"

    def test_multi_stage_exam_dates_are_a_conflict(self, ssc_notice):
        """Tier-I and Tier-II dates on one notice cannot both be `exam_date`.

        `exam_date` is a scalar until the `exam_dates` list lands, so two
        stages on one document are a genuine conflict. The pipeline picks the
        one with the stronger label, records the other as rejected, and flags
        the conflict for a human rather than pretending there is one date.
        """
        adj = adjudicate(find_candidates(ssc_notice, "u"))
        entry = adj["exam_date"]
        assert entry.conflict is True
        rejected = {c.value for c in entry.rejected}
        assert "2026-09-28" in rejected

    def test_disagreement_is_flagged_not_silently_resolved(self):
        cands = find_candidates(
            "The examination will be held on 15.06.2026. "
            "The date of the examination is 16.06.2026.",
            "u",
        )
        adj = adjudicate(cands)
        assert adj["exam_date"].conflict is True
        assert adj["exam_date"].value in {"2026-06-15", "2026-06-16"}
        assert adj["exam_date"].rejected, "the loser must be kept for the reviewer"

    def test_provisional_is_never_promoted(self):
        cands = find_candidates("The tentative exam date is 15.06.2026.", "u")
        adj = adjudicate(cands)
        assert adj["exam_date"].chosen.provisional is True

    def test_month_only_field_gets_an_entry_with_no_value(self):
        adj = adjudicate(find_candidates("The exam is in June 2027.", "u"))
        entry = adj.get("exam_date")
        assert entry is not None
        assert entry.chosen is None
        assert entry.coarse_notes
        assert "month" in entry.reason

    def test_day_beats_month_for_the_same_field(self):
        text = "Last date to apply: in June 2027. Last date to apply: 22.02.2027."
        cands = find_candidates(text, "u")
        adj = adjudicate(cands)
        assert adj["registration_deadline"].value == "2027-02-22"


class TestReferenceDates:
    """A date after 'dated', 'born' or 'as on' is a reference, never an event."""

    def test_an_office_memo_date_is_not_an_exam_date(self):
        from examhub_pipeline.candidates import find_candidates
        text = "The examination will be held as per OM No. 12/2018 dated 15.01.2018 and notified later."
        assert not [c for c in find_candidates(text, "u") if c.field == "exam_date"]

    def test_an_age_cut_off_is_only_an_age_answer(self):
        from examhub_pipeline.candidates import _reference_date
        clause = "Age limit as on 01.04.2026"
        assert _reference_date(clause, "01.04.2026", "exam_date")
        assert not _reference_date(clause, "01.04.2026", "age_as_on")

    def test_a_deadline_is_left_alone(self):
        from examhub_pipeline.candidates import _reference_date
        assert not _reference_date("Last date is 31.08.2026", "31.08.2026", "registration_deadline")


def _pick(text: str, field: str) -> str | None:
    """The finder's first pick for one field, or None."""
    a = adjudicate(find_candidates(text, "u")).get(field)
    return a.chosen.value if a and a.chosen else None


class TestTableTotals:
    """Vacancy totals printed one table cell per line (shapes from DSSSB, IBPS, SBI)."""

    def test_a_grand_total_row_gives_the_cell_that_sums_the_categories(self):
        text = "Total number of vacancies\nPost A\n7\n5\n1\n1\n0\n14\nGRAND TOTAL\n365\n220\n140\n59\n127\n911\n42\n9"
        assert _pick(text, "vacancies") == "911"

    def test_a_total_row_with_one_number_gives_that_number(self):
        text = "No. of vacancies\nSI (Civil)\n116\nTotal Vacancies\n378\n"
        assert _pick(text, "vacancies") == "378"

    def test_a_post_row_sums_to_its_own_total(self):
        text = "Vacancies\nName of Post\nTotal\nUR\nSC\nST\nOBC EWS\nHead Constable\n21\n7\n4\n0\n7\n3\n21\n"
        assert _pick(text, "vacancies") == "21"

    def test_numbers_far_from_any_post_or_vacancy_are_ignored(self):
        text = "Marks\nPaper I\n50\n100\n150\n"
        assert _pick(text, "vacancies") is None


class TestAgeCutOff:
    """The date age is counted on, however the notice words it."""

    @pytest.mark.parametrize("text", [
        "must not have attained the age of 24 years as on 1st\nJuly, 2026 i.e., must have been born",
        "Min. 20 year and Max. 28 years as on 01-Feb-2025.",
        "Age will be calculated with reference to 01.01.2025 and should have attained the age",
        "The Cut-off Date for the purpose of eligibility in Age criteria shall be the 1st day of "
        "the month in which online registration commences i.e.\n01.08.2025.",
    ])
    def test_the_cut_off_is_found(self, text):
        assert _pick(text, "age_as_on") in {"2026-07-01", "2025-02-01", "2025-01-01", "2025-08-01"}

    def test_age_on_the_closing_date_is_the_deadline(self):
        text = ("Closing date for applications: 27/10/2026.\n"
                "Crucial date for determining the age limit will be the closing date.")
        assert _pick(text, "age_as_on") == "2026-10-27"

    def test_a_cut_off_for_experience_is_not_an_age_cut_off(self):
        text = ("Last date of registration: 25.08.2025.\n"
                "The cut-off date for post qualification experience will be the last date of registration.")
        assert _pick(text, "age_as_on") is None

    def test_an_in_which_registration_date_is_not_the_opening_date(self):
        text = ("The Cut-off Date for Age criteria shall be the 1st day of the month in which "
                "online registration commences i.e. 01.08.2025.")
        assert _pick(text, "registration_open") is None


class TestTableRows:
    """Label and date on alternate lines, as PDF text layers print a table."""

    def test_each_label_takes_the_date_below_it(self):
        text = ("Opening of Application Portal\n25 May 2026 (2:00 PM)\n"
                "Closing of Application Portal\n15 June 2026 (5:00 PM)\nReleasing of admit card")
        assert _pick(text, "registration_open") == "2026-05-25"
        assert _pick(text, "registration_deadline") == "2026-06-15"

    def test_a_label_never_reaches_past_the_next_label(self):
        text = "Opening Date of Application:- 04-{19-2025 Closing Date of Application:- 30-09-2025 (03:00 PM)"
        assert _pick(text, "registration_open") is None
        assert _pick(text, "registration_deadline") == "2025-09-30"


class TestNewWordings:
    @pytest.mark.parametrize("text,field,value", [
        ("The CAT 2026 registration window opens on August 3, 2026 and the online application "
         "process closes on September 15, 2026.", "registration_deadline", "2026-09-15"),
        ("Online registration closes\nMay 02, 2026 (Saturday, 23:59 IST)", "registration_deadline", "2026-05-02"),
        ("Last date of Online Submission of Application\n07-June-2026: 18.00", "registration_deadline", "2026-06-07"),
        ("Last date for fee payment for\nregistered candidates\nMay 04, 2026 (Monday, 23:59 IST)",
         "payment_deadline", "2026-05-04"),
        ("any pending payments must be completed by April 12, 2026 (11:30 PM).", "payment_deadline", "2026-04-12"),
    ])
    def test_the_value_is_found(self, text, field, value):
        assert _pick(text, field) == value


class TestFalsePicks:
    def test_a_qualifying_result_deadline_is_not_the_result_date(self):
        text = "Proof of having declared the result on or before 25.08.2025 has to be submitted."
        assert _pick(text, "result_date") is None

    def test_omr_sheets_in_exam_hall_rules_are_not_the_mode(self):
        text = "(a) Taking away any Examination related material such as OMR sheets, Rough Sheets etc."
        assert _pick(text, "mode") is None

    def test_a_date_from_decades_ago_is_not_an_event(self):
        text = "The examination was held on 26.06.2000 for the first time."
        assert _pick(text, "exam_date") is None


class TestHeldOutShapes:
    """Shapes found in notices kept out of tuning."""

    @pytest.mark.parametrize("text,value", [
        ("on the 18th & 19th July, 2024 for", "2024-07-18"),
        ("Friday, 29th of January, 2021.", "2021-01-29"),
        ("Tentatively 4th, 5th, 7th, 8th and 9th of May, 2026", "2026-05-04"),
    ])
    def test_day_lists_and_of_give_the_first_day(self, text, value):
        from examhub_pipeline.candidates import find_dates
        assert find_dates(text)[0].value.isoformat() == value

    def test_a_marks_total_is_not_a_vacancy_total(self):
        text = "No. of vacancies\nLab Assistant\n1\nSubject\nMaximum Marks\nPaper I\n300\nPaper II\n270\nTotal:\n570\n"
        assert _pick(text, "vacancies") != "570"

    def test_a_certificate_validity_bound_is_not_an_exam_date(self):
        text = "Certificate of character issued by a Group A Officer on or after 23.02.2024 for the examination."
        assert _pick(text, "exam_date") is None

    def test_a_published_result_condition_is_not_a_deadline(self):
        text = ("Candidates should satisfy themselves before they apply that the final result must have "
                "been published on or before 01.12.2023.")
        assert _pick(text, "registration_deadline") is None

    def test_a_label_takes_a_tentative_date_on_the_next_line(self):
        text = ("Starting of Downloading of Admit\nCards\n:\nFrom 25th of April, 2026\niv\nDate of Examination\n:\n"
                "Tentatively 4th, 5th, 7th, 8th and 9th\nof May, 2026 (Detailed Schedule\nshall be notified later)\n")
        assert _pick(text, "exam_date") == "2026-05-04"

    def test_a_correction_window_is_not_the_application_window(self):
        text = ("Considering the request made by candidates to open correction window to correct/modify online "
                "application form, after closing date for receipt of online application form, CRPF will "
                "provide a period of 21/05/2026 to 23/05/2026.")
        assert _pick(text, "registration_open") is None
        assert _pick(text, "registration_deadline") is None

    def test_offline_fee_payment_is_not_the_exam_mode(self):
        assert _pick("Payment of fee can be done through either on-line mode or offline mode.", "mode") is None

    @pytest.mark.parametrize("text,field,value", [
        ("Last date and time\n19.09.2026 (Saturday), 05:00 PM", "registration_deadline", "2026-09-19"),
        ("Online Registration Closing Time and date: 17.00 hours on 15.01.2026", "registration_deadline", "2026-01-15"),
        ("Last date for Filling-up of Online\nApplication Forms\n:\n22nd March, 2026", "registration_deadline", "2026-03-22"),
        ("Last date for submission of fee: 10.06.2026 (Before 11:59PM)", "payment_deadline", "2026-06-10"),
        ("6 A. AGE (as on 01.07.2018):", "age_as_on", "2018-07-01"),
        ("The candidates must be minimum 17 years of age as on dt: 31.12.2026 i.e.", "age_as_on", "2026-12-31"),
        ("Eligible candidates may send their resume to the address on or before 31.05.2024.",
         "registration_deadline", "2024-05-31"),
    ])
    def test_the_value_is_found(self, text, field, value):
        assert _pick(text, field) == value
