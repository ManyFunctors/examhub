"""Merging one exam's two files: what merges, what is kept, what stops a merge."""

import datetime as dt

import pytest

from examhub_pipeline import dedupe


def rec(slug, **kw):
    r = {"title": "CAT 2026", "title_official": "Common Admission Test, 2026", "slug": slug,
         "title_aliases": ["CAT"], "exam_id": "in-cat", "cycle": "2026",
         "dates": {"application": {"from": dt.date(2026, 8, 3), "to": "not_announced", "status": "confirmed"}},
         "fee": {"rows": [{"fee_category": "all", "fee_rupees": "not_announced"}]},
         "links": {"link_apply": "https://iimcat.ac.in/", "documents": []},
         "provenance": {"evidence": []}}
    r.update(kw)
    return r


def test_the_merge_keeps_every_fact_of_both():
    a = rec("mgt-cat-2026")
    b = rec("d5-cat-2026", title="Common Admission Test (CAT) 2026",
            dates={"application": {"from": dt.date(2026, 8, 3), "to": dt.date(2026, 9, 22), "status": "confirmed"}},
            fee={"rows": [{"fee_category": "General", "fee_rupees": 2700}]},
            links={"link_apply": "https://iimcat.ac.in/register", "documents": [{"document_url": "https://iimcat.ac.in/n.pdf"}]},
            provenance={"evidence": [{"evidence_words": "registration 2026-08-03 to 2026-09-22"}]})
    m = dedupe.merge(a, b)
    assert m["dates"]["application"]["to"] == dt.date(2026, 9, 22)
    assert m["fee"]["rows"] == [{"fee_category": "General", "fee_rupees": 2700}]
    assert m["links"]["link_apply"] == "https://iimcat.ac.in/register"
    assert m["title_aliases"] == ["CAT", "Common Admission Test (CAT) 2026"]
    assert m["aliases"] == ["/exams/d5-cat-2026/"]
    assert m["slug"] == "mgt-cat-2026"
    assert not dedupe.lost(m, a) and not dedupe.lost(m, b)


def test_two_different_facts_stop_the_merge():
    a = rec("a", dates={"application": {"from": dt.date(2026, 1, 11), "to": dt.date(2026, 1, 31), "status": "confirmed"}})
    b = rec("b", dates={"application": {"from": dt.date(2026, 1, 11), "to": dt.date(2026, 3, 19), "status": "confirmed"}})
    with pytest.raises(dedupe.Conflict):
        dedupe.merge(a, b)


def test_links_on_two_sites_stop_the_merge():
    with pytest.raises(dedupe.Conflict):
        dedupe.merge(rec("a"), rec("b", links={"link_apply": "https://xatonline.in/registration", "documents": []}))


def test_omr_is_the_narrower_pen_and_paper():
    assert dedupe._merge("pen_paper", "omr", "dates.stages.stage_mode") == "omr"
