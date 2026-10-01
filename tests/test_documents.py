"""The PDF structurer: tables, prose, selection. No network, no OCR."""

from __future__ import annotations

import datetime as dt

import pytest

from examhub_pipeline import documents as D
from examhub_pipeline.crawl import ingest

REF = dt.date(2026, 9, 1)


def table(header, rows, page=1):
    return D.Table(page=page, header=header, rows=rows)


# -- categories -------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("SC/ST/PwBD/EXS", ["SC", "ST", "PwBD", "Ex-Servicemen"]),
    ("General (UR)", ["Unreserved"]),
    # Distinct classes are never merged: OBC-NCL is not OBC.
    ("OBC- NCL", ["OBC-NCL"]),
    ("OBC", ["OBC"]),
    # "Most backward classes" with no such class in scope is unknown, not OBC.
    ("Most Backward Classes", []),
    ("Scheduled Castes", ["SC"]),
    ("Economically Weaker Sections", ["EWS"]),
    ("Constable (General Duty)", []),
])
def test_categories(text, expected):
    assert D.categories_in(text) == expected


@pytest.mark.parametrize("body,text,expected", [
    # The same letters are different classes in different states.
    ("hr-hssc", "OSC", ["hr:OSC"]),
    ("jk-jkssb", "OSC", ["jk:OSC"]),
    ("hr-hssc", "DESM", ["Dependent of Ex-Servicemen"]),
    ("in-ssc", "DESM", ["Disabled Ex-Servicemen"]),
    # A state's own spelling of Unreserved.
    ("tn-tnpsc", "GT/BC/BCM/MBC/DNC/SC(A)", ["Unreserved", "tn:BC", "tn:BCM", "tn:MBC/DNC", "tn:SC(A)"]),
    ("ka-kea", "GM/2A/3B", ["Unreserved", "ka:2A", "ka:3B"]),
    # A national notice has no state classes in scope.
    ("in-ssc", "BC", ["OBC"]),
])
def test_categories_are_scoped_to_the_notice_jurisdiction(body, text, expected):
    token = D._JURISDICTION.set(D.jurisdiction_of({"body": body}))
    try:
        assert D.categories_in(text) == expected
    finally:
        D._JURISDICTION.reset(token)


def test_unmapped_class_columns_go_to_the_worklist():
    t = table(["Post", "UR", "SC", "BC-X", "Total"], [["Clerk", "3", "1", "2", "6"], ["Typist", "1", "0", "1", "2"]])
    assert D.unmapped_headers(t) == ["BC-X"]


def test_who_reads_except_as_everyone_else():
    assert D.who("All candidates other than SC/ST/PwBD") == {
        "categories": ["SC", "ST", "PwBD"], "except": True}
    assert D.who("for SC/ST") == {"categories": ["SC", "ST"]}
    assert D.who("for all candidates") == {"categories": ["All candidates"]}


# -- tables -----------------------------------------------------------------


def test_split_header_joins_spanned_levels_and_skips_captions():
    rows = [
        ["Statement showing category-wise vacancies for the post of Librarian", "", "", "", ""],
        ["Establishment", "Total", "Category", "", ""],
        ["", "", "UR", "SC", "ST"],
        ["District Judiciary", "29", "25", "3", "1"],
    ]
    header, body = D.split_header(rows)
    assert header == ["Establishment", "Total", "Category UR", "Category SC", "Category ST"]
    assert body == [["District Judiciary", "29", "25", "3", "1"]]


def test_vacancy_table_by_category_with_male_female_rows():
    t = table(
        ["Name of Post", "Total vacancies", "Particulars", "UR", "SC", "ST", "OBC", "EWS", "Total"],
        [
            ["Head Constable", "16", "Male", "3", "0", "2", "8", "1", "14"],
            ["", "", "Female", "1", "0", "0", "1", "0", "2"],
        ],
    )
    assert D.classify(t) == "vacancy"
    rows = D.parse_vacancy(t)
    assert [r["label"] for r in rows] == ["Head Constable / Male", "Head Constable / Female"]
    assert [r["total"] for r in rows] == [14, 2]
    assert rows[0]["by_category"] == {"Unreserved": 3, "EWS": 1, "OBC": 8, "SC": 0, "ST": 2}


def test_subset_columns_are_not_the_total():
    t = table(
        ["Establishment", "No. of Posts", "General", "SC", "Out of total vacancy reserved for PwBD"],
        [["District Judiciary", "29*", "29", "0", "2"]],
    )
    [row] = D.parse_vacancy(t)
    assert row["total"] == 29
    assert row["by_category"] == {"Unreserved": 29, "SC": 0, "PwBD": 2}


def test_largest_table_group_wins_and_total_row_is_used():
    groups = {
        "a": [{"label": "Mining", "total": 276, "by_category": {}, "page": 1}],
        "b": [
            {"label": "Mining", "total": 276, "by_category": {"Unreserved": 114, "SC": 162}, "page": 2},
        ],
    }
    out = D.summarise_vacancies(groups, [])
    assert out["total"] == 276 and out["by_category"] == {"Unreserved": 114, "SC": 162}


def test_fee_table_with_except_row():
    t = table(
        ["Category", "Application Fees"],
        [["SC/ST/PwBD/EXS", "Rs. 100/- (Intimation Charges only)"],
         ["All candidates other than SC/ST/PWD/EXS", "Rs. 850/-"]],
    )
    assert D.classify(t) == "fee"
    fees = D.parse_fee_table(t)
    assert [(f["categories"], f.get("except"), f["amount"]) for f in fees] == [
        (["SC", "ST", "PwBD", "Ex-Servicemen"], None, 100),
        (["SC", "ST", "PwBD", "Ex-Servicemen"], True, 850),
    ]


def test_pay_table_is_not_a_fee_table():
    t = table(["Post", "Pay"], [["Constable (General Duty)", "Level- 3 Rs. 21700-69100/-"]])
    assert D.classify(t) != "fee"


def test_schedule_table_maps_events():
    t = table(["Activity", "Important Dates"], [
        ["Opening date for Online Registration", "08-May-2026 :10.00"],
        ["Last date of Online Submission of Application", "07-June-2026: 18.00"],
        ["Date of Computer Based Test", "12.07.2026"],
    ])
    assert D.classify(t) == "schedule"
    events = D.parse_schedule(t, REF)
    assert [(e["key"], e["date"]) for e in events] == [
        ("registration_open", "2026-05-08"),
        ("registration_deadline", "2026-06-07"),
        ("exam_date", "2026-07-12"),
    ]


def test_relaxation_table_ignores_age_ceilings():
    t = table(["Sl.", "Category", "Age Relaxation"], [
        ["1.", "Scheduled Castes/ Scheduled Tribes", "5 years"],
        ["2.", "Other Backward Classes (Non-Creamy Layer)", "3 years"],
        ["3.", "Widows, divorced women", "Age concession upto the age of 35 years"],
    ])
    rows = D.parse_relaxation(t)
    assert [(r["categories"], r.get("years")) for r in rows] == [
        (["SC", "ST"], 5), (["OBC-NCL"], 3), (["Widow", "Divorcee"], None)]


def test_exam_pattern_table():
    t = table(["S. No", "Name of Test", "No. of Questions", "Max. Marks", "Duration"], [
        ["1", "English Language", "30", "30", "20 minutes"],
        ["2", "Reasoning Ability", "35", "35", "20 minutes"],
    ])
    assert D.classify(t) == "pattern"
    assert D.parse_pattern(t)[0] == {"paper": "English Language", "page": 1,
                                     "questions": 30, "marks": 30, "duration": "20 minutes"}


# -- prose ------------------------------------------------------------------


def test_fee_prose_with_exemption_in_next_sentence():
    text = ("Fee payable: Examination Fees @ Rs 100/- for male candidates of UR, OBC and EWS only. "
            "Candidates belonging to SC/ST, Ex-servicemen and Female candidates of all categories "
            "are exempted.")
    fees = D.fees_prose([(3, text)])
    assert (fees[0]["amount"], fees[0]["categories"]) == (100, ["Male", "Unreserved", "OBC", "EWS"])
    assert (fees[1]["amount"], fees[1]["categories"]) == (0, ["SC", "ST", "Ex-Servicemen", "Women"])


def test_fee_prose_skips_bank_charges():
    assert D.fees_prose([(1, "Bank charges: 0.80% of Fee + GST (Minimum Rs 11/-)")]) == []


def test_age_limits_skip_dependants_and_read_label_on_previous_line():
    pages = [(2, "Age limit:-\nBetween 20 to 25 years.\n"
                 "Children below the age of 18 years are dependants.\n"
                 "Maximum age not exceeding 45 years on a cumulative basis with relaxation.")]
    assert [(a["min"], a["max"]) for a in D.age_limits(pages)] == [(20, 25)]


def test_selection_stages_in_order():
    text = ("Selection Process: The selection will be through a Preliminary and Main "
            "examination followed by Interview and Document Verification.")
    assert D.selection_stages(text) == [
        "Preliminary examination", "Main examination", "Interview", "Document verification"]


def test_advertisement_number_and_links():
    assert D.advertisement_no("Advt No. 12/2025 Dated Shillong") == "12/2025"
    links = D.links_in("Apply at https://recruitment.itbpolice.nic.in. See www.itbpolice.nic.in/",
                       ["https://recruitment.itbpolice.nic.in/"])
    assert links["apply"] == ["https://recruitment.itbpolice.nic.in/"]
    assert links["other"] == ["https://www.itbpolice.nic.in/"]


def test_pay_scales():
    pay = D.pay_scales([(2, "Pay Scale: Level-4 in the Pay Matrix (Rs. 25,500-81,100)")], "u")
    assert pay[0]["levels"] == [4]
    assert pay[0]["text"] == "Pay Level 4, ₹25,500–81,100"


def test_document_kind():
    assert D.document_kind("Corrigendum No.40/2026", "") == "corrigendum"
    assert D.document_kind("CAT 2026 Information Bulletin", "") == "brochure"
    assert D.document_kind("View Advertisement", "") == "advertisement"
    assert D.document_kind("Notice", "applications are invited for") == "advertisement"


def test_summary_and_render_have_no_empty_sections():
    record = D._prune({
        "notice": {"title": "Recruitment of Assistants", "body": "in-x", "url": "https://x/a.pdf"},
        "document": {"pages": 3, "sha256": "ab" * 32, "ocr": False},
        "kind": "advertisement",
        "vacancies": {"total": 500, "by_category": {"Unreserved": 300, "SC": 200}, "rows": []},
        "fees": [{"categories": ["SC"], "amount": 0, "page": 2}],
        "dates": {"registration_deadline": {"date": "2026-10-02", "page": 1}},
        "age": {"limits": [{"min": 18, "max": 27, "evidence": "18 to 27 years", "page": 2}]},
    })
    record["summary"] = D.summarise(record)
    assert record["summary"]["vacancies"] == 500
    assert record["summary"]["apply"] == {"from": None, "until": "2026-10-02"}
    md = D.render_markdown(record)
    assert "| Vacancies | 500 (Unreserved 300 · SC 200) |" in md
    assert "SC Nil" in md
    assert "## Pay" not in md


# -- selection --------------------------------------------------------------


def notice(i, **kw):
    base = {"id": f"{i:064x}", "url": f"https://x{i}.gov.in/{i}.pdf", "title": "Advertisement",
            "doc_type": "notification", "exam": "in-x", "body": "in-x", "first_seen": "2026-09-20"}
    return {**base, **kw}


def test_select_wants_matched_pdfs_and_skips_lists():
    today = dt.datetime(2026, 9, 29, tzinfo=ingest.harvest.IST)
    notices = [
        notice(1),
        notice(2, exam=None),
        notice(3, doc_type="result"),
        notice(4, title="List of candidates provisionally selected"),
        notice(5, url="https://x.gov.in/page.html", doc_type="other"),
        notice(6, first_seen="2025-01-01"),
        notice(7, first_seen="2026-09-28"),
    ]
    chosen = ingest.select(notices, {}, limit=10, today=today)
    # new notices first, newest first; the old one is gap-filling after them
    assert [n["id"][-1] for n in chosen] == ["7", "1", "6"]
    assert len(ingest.select(notices, {}, limit=2, today=today)) == 2


def test_gap_filling_serves_the_emptiest_exams_first():
    today = dt.datetime(2026, 9, 29, tzinfo=ingest.harvest.IST)
    old = "2025-01-01"
    notices = [
        notice(1, exam="in-full", first_seen=old), notice(2, exam="in-full", first_seen="2025-02-01"),
        notice(3, exam="in-empty", first_seen=old), notice(4, exam="in-empty", first_seen="2025-03-01"),
        notice(5, exam="in-some", first_seen=old),
    ]
    gaps = {"in-full": {"gaps": [], "documents": 4},
            "in-empty": {"gaps": ["fee", "age", "pay"], "documents": 0},
            "in-some": {"gaps": ["fee"], "documents": 1}}
    chosen = ingest.select(notices, {}, limit=10, today=today, gaps=gaps)
    # one per exam per round, emptiest first; each exam's newest first
    assert [n["id"][-1] for n in chosen] == ["4", "5", "2", "3", "1"]


def test_select_retries_failures_daily_and_redoes_old_schema():
    today = dt.datetime(2026, 9, 29, 12, tzinfo=ingest.harvest.IST)
    n1, n2, n3, n4 = notice(1), notice(2), notice(3), notice(4)
    index = {
        n1["id"]: {"status": "failed", "attempts": 1, "tried": "2026-09-28T02:00:00+05:30"},
        n2["id"]: {"status": "failed", "attempts": ingest.MAX_ATTEMPTS, "tried": "2026-09-01"},
        n3["id"]: {"status": "ok", "schema": 0},
        n4["id"]: {"status": "not_pdf"},
    }
    chosen = ingest.select([n1, n2, n3, n4], index, limit=10, today=today)
    assert [n["id"][-1] for n in chosen] == ["1", "3"]


def test_select_caps_documents_per_host():
    today = dt.datetime(2026, 9, 29, tzinfo=ingest.harvest.IST)
    same_host = [notice(i, url=f"https://slow.gov.in/{i}.pdf") for i in range(1, 8)]
    chosen = ingest.select(same_host + [notice(9)], {}, limit=10, today=today)
    hosts = [n["url"].split("/")[2] for n in chosen]
    assert hosts.count("slow.gov.in") == ingest.MAX_PER_HOST
    assert "x9.gov.in" in hosts


def test_host_breaker_ignores_requests_to_dead_hosts():
    from scrapy import Request
    from scrapy.exceptions import IgnoreRequest

    from examhub_pipeline.crawl.middlewares import HostBreaker

    class Spider:
        dead_hosts = {"nta.ac.in"}

    mw = HostBreaker()
    assert mw.process_request(Request("https://ssc.gov.in/a.pdf"), Spider()) is None
    with pytest.raises(IgnoreRequest):
        mw.process_request(Request("https://nta.ac.in/a.pdf"), Spider())
