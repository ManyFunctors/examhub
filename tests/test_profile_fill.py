"""Profiles fill records only when the cycle matches and the record has no value of its own."""

import datetime as dt

from examhub_pipeline import profile_fill, record

SRC = {"url": "https://example.gov.in/notice.pdf", "page": 2}


def rec(cycle="2026"):
    r = record.skeleton(title="X 2026", slug="x-2026", body="in-x", exam_id="in-x", cycle=cycle)
    return r


def profile(cycle="2026-12", **fields):
    return {"exam": "in-x", "cycle": cycle, "fields": fields}


def dates(**kw):
    return {"dates": {k: {**v, "source": SRC} for k, v in kw.items()}}


def test_matching_cycle_fills_the_application_window_and_the_exam_date():
    r = rec()
    p = profile(**dates(registration_open={"date": "2026-10-08"}, registration_deadline={"until": "2026-10-28"},
                        exam_date={"date": "2026-12-01"}))
    notes = profile_fill.fill_record(r, p, same_cycle_records=1)
    assert r["dates"]["application"]["from"] == dt.date(2026, 10, 8)
    assert r["dates"]["application"]["to"] == dt.date(2026, 10, 28)
    exam = r["dates"]["stages"][0]["exam"]
    assert exam["from"] == dt.date(2026, 12, 1) and exam["to"] == "unknown" and exam["status"] == "confirmed"
    assert len(notes) == 3
    assert {e["evidence_field"] for e in r["provenance"]["evidence"]} >= {"dates.application.from"}


def test_another_cycle_is_never_written():
    r = rec("2027")
    p = profile("2026-01", **dates(exam_date={"date": "2026-01-18"}))
    assert profile_fill.fill_record(r, p, same_cycle_records=1) == []


def test_a_date_years_away_is_refused():
    r = rec("2026")
    p = profile("2026", **dates(exam_date={"date": "2017-10-29"}))
    assert profile_fill.fill_record(r, p, same_cycle_records=1) == []


def test_a_real_value_is_never_overwritten():
    r = rec()
    r["dates"]["application"].update({"from": dt.date(2026, 9, 1), "to": dt.date(2026, 9, 30), "status": "confirmed"})
    p = profile(**dates(registration_open={"date": "2026-10-08"}, registration_deadline={"until": "2026-10-28"}))
    assert profile_fill.fill_record(r, p, same_cycle_records=1) == []
    assert r["dates"]["application"]["from"] == dt.date(2026, 9, 1)


def test_vacancies_need_a_table_and_a_single_record():
    p = profile(vacancies={"value": {"total": 120, "from": "table", "evidence": "Total 120",
                                     "by_category": {"Unreserved": 60, "EWS": 12, "OBC": 32, "SC": 12, "ST": 4, "PwBD": 5}},
                           "source": SRC})
    r = rec()
    assert profile_fill.fill_record(r, p, same_cycle_records=2) == []
    assert profile_fill.fill_record(r, profile(vacancies={"value": {"total": 120, "from": "text"}, "source": SRC}),
                                    same_cycle_records=1) == []
    assert profile_fill.fill_record(r, p, same_cycle_records=1) == ["posts.vacancies_total = 120"]
    assert r["posts"]["vacancies_total"] == 120 and r["posts"]["vacancies_status"] == "confirmed"


def test_a_table_whose_columns_do_not_add_up_is_not_trusted():
    p = profile(vacancies={"value": {"total": 705, "from": "table",
                                     "by_category": {"Unreserved": 968, "EWS": 210, "BC": 259}}, "source": SRC})
    assert profile_fill.fill_record(rec(), p, same_cycle_records=1) == []


def _vac(rows, total, title="Notification: Detailed CEN"):
    return {"vacancies": {"value": {"from": "table", "total": total, "rows": [{"label": "x", "total": n} for n in rows]},
                          "source": {**SRC, "title": title}}}


def test_a_zone_table_counts_when_its_rows_add_up():
    r = rec()
    profile_fill.fill_record(r, profile(**_vac([60, 40], 100)), same_cycle_records=1)
    assert r["posts"]["vacancies_total"] == 100
    r = rec()
    profile_fill.fill_record(r, profile(**_vac([60, 30], 100)), same_cycle_records=1)
    assert r["posts"]["vacancies_total"] != "100"


def test_a_corrigendum_table_never_sets_the_total():
    r = rec()
    profile_fill.fill_record(r, profile(**_vac([60, 40], 100, "Corrigendum no.1 of CEN 02/2026")), same_cycle_records=1)
    assert r["posts"]["vacancies_total"] != "100"

def test_a_window_given_as_one_row_sets_both_ends():
    r = rec()
    p = profile(**dates(registration_open={"date": "2026-10-07", "until": "2026-11-05"}))
    profile_fill.fill_record(r, p, same_cycle_records=1)
    assert r["dates"]["application"]["from"] == dt.date(2026, 10, 7)
    assert r["dates"]["application"]["to"] == dt.date(2026, 11, 5)


def test_age_band_fills_an_unknown_age_rule_with_plain_relaxations():
    from examhub_pipeline.profile_fill import fill_record
    rec = {"cycle": "2026", "eligibility": [{"age": {"applies": "unknown", "age_as_of": "unknown", "age_min": "unknown",
                                                    "age_max": "unknown", "relaxations": "none"}}]}
    age = {"value": {"limits": [{"min": 21, "max": 30, "evidence": "min 21 max 30", "page": 3}], "as_on": "2026-06-30",
                     "relaxations": [{"categories": ["OBC-NCL"], "years": 3}, {"categories": ["Widow", "Women"], "years": 9}]},
           "source": {"url": "https://x.test/a.pdf", "page": 3}}
    profile = {"cycle": "2026", "fields": {"age": age}}
    assert fill_record(rec, profile, same_cycle_records=1)
    rule = rec["eligibility"][0]["age"]
    assert (rule["age_min"], rule["age_max"], rule["applies"]) == (21, 30, "yes")
    assert rule["relaxations"] == [{"relaxation_category": "OBC-NCL", "relaxation": "+3"}]
    # a real value is never overwritten
    assert fill_record(rec, profile, same_cycle_records=1) == []


def test_notices_are_listed_as_documents_only_for_the_cycle():
    from examhub_pipeline.profile_fill import attach_notices
    rec = {"exam_id": "x", "cycle": "2026", "links": {"documents": []}}
    notices = [
        {"exam": "x", "url": "https://a.test/Advt_2026.pdf", "title": "Advt", "doc_type": "notification"},
        {"exam": "x", "url": "https://a.test/Notice_20260924.pdf", "title": "Notice", "doc_type": "notification"},
        {"exam": "x", "url": "https://a.test/Old_2025.pdf", "title": "Old", "doc_type": "notification"},
        {"exam": "x", "url": "https://a.test/Gone_2026.pdf", "title": "Gone", "doc_type": "notification", "gone_since": "t"},
        {"exam": "y", "url": "https://a.test/Other_2026.pdf", "title": "Other", "doc_type": "notification"},
        {"exam": "x", "url": "https://a.test/Res_2026.pdf", "title": "Res", "doc_type": "result"},
    ]
    attach_notices(rec, notices, same_cycle_records=1)
    assert [d["document_url"] for d in rec["links"]["documents"]] == ["https://a.test/Advt_2026.pdf"]
    assert attach_notices(rec, notices, same_cycle_records=2) == []


def test_documents_are_ordered_capped_and_titled():
    from examhub_pipeline.profile_fill import attach_notices
    rec = {"exam_id": "x", "cycle": "2026", "links": {"documents": []}}
    notices = [{"exam": "x", "url": f"https://a.test/PR_2026_{i}.pdf", "title": f"Press note {i}",
                "doc_type": "press_release", "published": f"2026-0{i + 1}-01"} for i in range(6)]
    notices.append({"exam": "x", "url": "https://a.test/Advt_2026.pdf", "title": "EXAM NAME LONG PREFIX HERE 2026 - Detailed advertisement",
                    "doc_type": "notification", "published": "2026-01-01", "published_from": "title"})
    attach_notices(rec, notices, same_cycle_records=1)
    docs = rec["links"]["documents"]
    assert [d["document_type"] for d in docs] == ["notification"] + ["press_release"] * 3
    assert docs[0]["document_title"] == "Detailed advertisement" and docs[0]["document_published"] == "unknown"
    assert [d["document_title"] for d in docs[1:]] == ["Press note 5", "Press note 4", "Press note 3"]


def test_a_date_printed_in_the_title_is_not_the_publication_date():
    from examhub_pipeline.profile_fill import attach_notices
    rec = {"exam_id": "x", "cycle": "2026", "links": {"documents": [
        {"document_type": "notification", "document_published": __import__("datetime").date(2026, 7, 26),
         "document_url": "https://a.test/P_2026.pdf"}]}}
    notices = [{"exam": "x", "url": "https://a.test/P_2026.pdf", "title": "Prospectus of SET Exam 26th July, 2026",
                "doc_type": "notification", "published": "2026-07-26"}]
    attach_notices(rec, notices, same_cycle_records=1)
    assert rec["links"]["documents"][0]["document_published"] == "unknown"


def test_a_long_title_is_cut_at_a_word():
    from examhub_pipeline.profile_fill import _short_title
    out = _short_title("Public Notice regarding Addition of Examination Cities and Expansion of City Choice Options for UGC-NET June 2026 Examination")
    assert out.endswith("…") and not out.endswith("June 2…") and len(out) <= 111


def test_every_listed_document_is_titled_by_notice_or_file_name_but_portals_are_not():
    from examhub_pipeline.profile_fill import attach_notices
    rec = {"exam_id": None, "cycle": "unknown", "links": {"documents": [
        {"document_type": "other", "document_url": "https://a.test/files/Detailed-Notification_CRP-PO-XVI_V1.pdf"},
        {"document_type": "other", "document_url": "https://a.test/login", "document_title": "Login"},
        {"document_type": "other", "document_url": "https://a.test/n/Notice_20260924172919.pdf"}]}}
    attach_notices(rec, [], same_cycle_records=1)
    titles = {d["document_url"].rsplit("/", 1)[-1]: d.get("document_title") for d in rec["links"]["documents"]}
    assert titles == {"Detailed-Notification_CRP-PO-XVI_V1.pdf": "Detailed Notification CRP PO XVI V1",
                      "login": None, "Notice_20260924172919.pdf": None}


def test_profile_ignores_fees_in_answer_key_notices():
    from examhub_pipeline.profiles import terms

    rows = [{"kind": "answer_key"}, {"kind": "result"}, {"kind": "brochure"}, {"kind": "admit_card"}]
    assert terms(rows) == [{"kind": "brochure"}]


def test_promote_wants_a_live_cycle():
    import datetime as dt

    from examhub_pipeline.promote import live

    today = dt.date(2026, 10, 22)
    assert live({"documents_in_cycle": 3, "fields": {"exam_date": {"value": "2026-08-22"}}}, today)
    assert not live({"documents_in_cycle": 3, "fields": {"exam_date": {"value": "2025-08-22"}}}, today)
    assert not live({"documents_in_cycle": 0, "fields": {"exam_date": {"value": "2026-08-22"}}}, today)
    assert not live({"documents_in_cycle": 2, "fields": {}}, today)


def test_vacancy_total_ignores_overlapping_reservation_columns():
    from examhub_pipeline.profile_fill import _adds_up

    cats = {"Unreserved": 6459, "OBC": 3834, "SC": 2223, "ST": 1134, "EWS": 1475,
            "PwBD-A": 154, "PwBD-B": 155, "Ex-Servicemen": 354}
    assert _adds_up({"total": 15125, "by_category": cats})
    assert not _adds_up({"total": 15000, "by_category": cats})


def test_promote_only_makes_pages_for_recurring_exams():
    from examhub_pipeline.promote import eligible

    assert eligible({"name": "AIAPGET", "frequency": "annual"})
    assert not eligible({"name": "Gujarat HC Staff Recruitment", "frequency": "irregular"})
    assert not eligible({"name": "Umbrella drives", "frequency": "annual"} | {"name": "X (umbrella)"})


def test_born_between_dates_fill_the_age_rule():
    from examhub_pipeline.profile_fill import _fill_born

    text = ("A candidate must have attained the age of 21 years and must not have attained the age of 32 years "
            "on the 1st of August, 2026 i.e., the candidate must have been born not earlier than 2nd August, 1994 "
            "and not later than 1st August, 2005")
    rec = {"eligibility": [{"age": {"applies": "unknown", "age_as_of": "unknown", "age_born_from": "unknown", "age_born_to": "unknown"}}],
           "provenance": {"evidence": []}}
    notes = _fill_born(rec, {"value": {"clauses": [{"text": text, "page": 3}]}, "source": {}}, 2026)
    age = rec["eligibility"][0]["age"]
    assert notes and str(age["age_born_from"]) == "1994-08-02" and str(age["age_born_to"]) == "2005-08-01"
    assert str(age["age_as_of"]) == "2026-08-01" and age["applies"] == "yes"
