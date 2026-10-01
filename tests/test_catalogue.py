"""The catalogue: the committed data lints clean, and the rules bite."""

from __future__ import annotations

import copy

import pytest

from examhub_pipeline import catalogue as C


@pytest.fixture(scope="module")
def cat():
    return C.load()


def test_committed_catalogue_is_clean(cat):
    assert C.lint(cat) == []


def test_catalogue_covers_every_jurisdiction(cat):
    assert len(cat.jurisdictions) == 37
    with_exams = {e["jurisdiction"] for e in cat.exams.values()}
    assert with_exams == set(cat.jurisdictions)


def _broken(cat, mutate):
    c = copy.deepcopy(cat)
    c._dupes = []
    mutate(c)
    return C.lint(c)


def test_unknown_body_reference_is_reported(cat):
    def m(c):
        c.exams["in-ssc-cgl"]["conducted_by"] = "in-nope"
    assert any("in-nope" in e for e in _broken(cat, m))


def test_year_in_exam_id_is_reported(cat):
    def m(c):
        e = dict(c.exams["in-ssc-cgl"], id="in-ssc-cgl-2026")
        c.exams[e["id"]] = e
    assert any("contains a year" in e for e in _broken(cat, m))


def test_id_without_jurisdiction_prefix_is_reported(cat):
    def m(c):
        e = dict(c.exams["in-ssc-cgl"], id="ssc-cgl")
        c.exams[e["id"]] = e
    assert any("must start with its jurisdiction" in e for e in _broken(cat, m))


def test_doubled_prefix_is_reported(cat):
    def m(c):
        e = dict(c.exams["kl-kpsc-ldc"], id="kl-kl-kpsc-ldc")
        c.exams[e["id"]] = e
    assert any("doubled" in e for e in _broken(cat, m))


def test_vocab_violation_is_reported(cat):
    def m(c):
        c.exams["in-ssc-cgl"]["purpose"] = "job"
    assert any("not in vocab.exam_purpose" in e for e in _broken(cat, m))


def test_merged_needs_successor(cat):
    def m(c):
        c.exams["in-ssc-cgl"]["status"] = "merged"
    assert any("needs a successor" in e for e in _broken(cat, m))


@pytest.mark.parametrize("body,title,expected", [
    ("in-ssc", "Notice of Combined Graduate Level Examination, 2026", ["in-ssc-cgl"]),
    ("in-ssc", "SSC CHSL 2026 Tier-I answer key", ["in-ssc-chsl"]),
    ("in-nta", "Public Notice regarding Joint CSIR-UGC NET June 2026", ["in-csir-net"]),
    ("in-nta", "Issuance of e-Certificates for UGC-NET June 2026", ["in-ugc-net"]),
    ("in-nta", "NEET (UG) 2027 information bulletin", ["in-neet-ug"]),
    ("in-upsc", "Civil Services (Main) Examination, 2026", ["in-upsc-cse"]),
    ("in-upsc", "Indian Forest Service (Main) Examination, 2026", ["in-upsc-ifos"]),
    ("kl-kpsc", "Last Grade Servants - various departments", ["kl-kpsc-lgs"]),
    # Scoped by body: SSC's CGL cannot be matched from a state commission.
    ("od-ossc", "Combined Graduate Level Examination 2026", ["od-ossc-cgl"]),
])
def test_matcher(cat, body, title, expected):
    assert C.Matcher(cat).match(body, title) == expected


def test_matcher_returns_nothing_for_unrelated_notice(cat):
    assert C.Matcher(cat).match("in-ssc", "Tender for housekeeping services") == []


@pytest.mark.parametrize("title,label", [
    ("SSC CGL 2026 notice", "2026"),
    ("UGC NET December 2026", "2026-dec"),
    ("Tentative calendar", None),
    ("Advertisement 2025 and 2026", "2026"),
])
def test_cycle_label(title, label):
    assert C.cycle_label(title) == label


def test_every_exam_pattern_compiles(cat):
    m = C.Matcher(cat)
    assert m._by_body  # built without raising


def test_dump_is_loadable(tmp_path, cat):
    import tomllib
    text = "\n".join(C.dump_items("exams", list(cat.exams.values())[:50]))
    data = tomllib.loads(text)
    assert [e["id"] for e in data["exams"]] == list(cat.exams)[:50]
