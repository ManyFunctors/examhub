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
