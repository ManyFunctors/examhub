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
