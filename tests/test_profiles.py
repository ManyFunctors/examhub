"""Exam profiles: the per-field merge rule and the gap list."""

from __future__ import annotations

from examhub_pipeline import profiles as P

EXAM = {"id": "in-x", "name": "X Recruitment", "purpose": "recruitment", "conducted_by": "in-y"}


def rec(i, kind="advertisement", published="2026-05-01", ocr=False, **fields):
    return {"notice": {"id": f"n{i}", "url": f"https://x/{i}.pdf", "title": f"doc {i}",
                       "exam": "in-x", "published": published},
            "document": {"ocr": ocr, "fetched": published}, "kind": kind, **fields}


def test_cycle_key():
    assert P.cycle_key("in-x/2026-mar") == (2026, 3)
    assert P.cycle_key("2025") == (2025, 0)
    assert P.cycle_key(None) == (0, 0)


def test_per_cycle_fields_never_come_from_an_older_cycle():
    old = rec(1, published="2024-03-01", fees=[{"categories": ["All candidates"], "amount": 500, "page": 3}],
              vacancies={"total": 90, "from": "table", "page": 1},
              selection=["Written examination", "Interview"])
    new = rec(2, published="2026-04-01", dates={"exam_date": {"date": "2026-11-01", "page": 1}})
    p = P.build_profile(EXAM, [old, new], {"n1": "in-x/2024", "n2": "in-x/2026"})
    assert p["cycle"] == "2026"
    assert "fee" not in p["fields"] and "vacancies" not in p["fields"]
    assert set(p["gaps"]) >= {"fee", "vacancies"}
    # a stable fact carries over, and says from when
    assert p["fields"]["selection"]["value"] == ["Written examination", "Interview"]
    assert p["fields"]["selection"]["carried_from"] == "2024"
    assert p["fields"]["exam_date"]["value"] == "2026-11-01"


def test_advertisement_table_beats_a_later_notice_for_terms_but_not_for_dates():
    advt = rec(1, published="2026-05-01", vacancies={"total": 500, "from": "table", "page": 2},
               dates={"exam_date": {"date": "2026-10-01", "page": 1, "from": "table"}})
    later = rec(2, kind="notice", published="2026-08-01",
                vacancies={"total": 7, "from": "text", "page": 1},
                dates={"exam_date": {"date": "2026-10-20", "page": 1}})
    p = P.build_profile(EXAM, [advt, later], {"n1": "in-x/2026", "n2": "in-x/2026"})
    assert p["fields"]["vacancies"]["value"]["total"] == 500
    assert p["fields"]["vacancies"]["alternatives"] == 1
    # the newer document moves the date: that is what a corrigendum does
    assert p["fields"]["exam_date"]["value"] == "2026-10-20"
    assert p["fields"]["dates"]["exam_date"]["source"]["notice"] == "n2"


def test_text_layer_beats_ocr():
    scan = rec(1, ocr=True, age={"limits": [{"min": 18, "max": 30, "page": 1}]})
    text = rec(2, age={"limits": [{"min": 18, "max": 27, "page": 2}]})
    p = P.build_profile(EXAM, [scan, text], {})
    assert p["fields"]["age"]["value"]["limits"][0]["max"] == 27


def test_no_documents_means_every_expected_field_is_a_gap():
    p = P.build_profile(EXAM, [], {})
    assert p["documents"] == 0 and p["gaps"] == list(P.EXPECTED["recruitment"])
    board = P.build_profile({**EXAM, "purpose": "school_board"}, [], {})
    assert board["gaps"] == ["exam_date"]
