"""Short titles: where each comes from, and what is left alone."""

from pathlib import Path

import pytest

from examhub_pipeline import names, record
from examhub_pipeline.catalogue import Catalogue


@pytest.fixture
def cat() -> Catalogue:
    return Catalogue(
        vocab={},
        jurisdictions={"tr": {"id": "tr", "name": "Tripura"}, "in": {"id": "in", "name": "India (Union)"}},
        bodies={
            "in-ibps": {"id": "in-ibps", "name": "Institute of Banking Personnel Selection", "short_name": "IBPS", "jurisdiction": "in"},
            "tr-tpsc": {"id": "tr-tpsc", "name": "Tripura Public Service Commission", "short_name": "TPSC", "jurisdiction": "tr"},
            "in-boi": {"id": "in-boi", "name": "Bank of India", "short_name": "Bank of India", "jurisdiction": "in"},
        },
        feeds={},
        exams={
            "in-ibps-clerk": {"id": "in-ibps-clerk", "short_name": "IBPS Clerk"},
            "in-boi-rec": {"id": "in-boi-rec", "short_name": "Bank of India Recruitment"},
        },
    )


def rec(title, *, exam="", body="", cycle="2026", aliases="none", slug="x-2026"):
    return {"title": title, "title_official": title, "exam_id": exam, "cycle": cycle, "slug": slug,
            "title_aliases": aliases, "bodies": [{"body": body, "body_role": "conducts"}]}


def test_the_catalogue_short_name_comes_first(cat):
    r = rec("Customer Service Associate (Clerk), 2026", exam="in-ibps-clerk", body="in-ibps",
            aliases=["IBPS CSA"])
    assert names.short_title(r, cat) == ("IBPS Clerk 2026", "catalogue")


def test_an_umbrella_catalogue_name_is_passed_over(cat):
    r = rec("Specialist Officers (Scale I to Scale IV), 2026", exam="in-boi-rec", body="in-boi")
    assert names.short_title(r, cat) == ("Bank of India Specialist Officers 2026", "notice")


def test_an_alias_serves_when_the_catalogue_has_none(cat):
    r = rec("Nursing Officer, 2026-27 (through NORCET-11)", aliases=["ESIC NORCET"], cycle="2026")
    assert names.short_title(r, cat) == ("ESIC NORCET 2026", "alias")


def test_the_notice_name_loses_its_filler_and_the_place_the_body_implies(cat):
    r = rec("Tripura Food Safety Officer Written Examination, 2026", body="tr-tpsc")
    assert names.short_title(r, cat)[0] == "TPSC Food Safety Officer 2026"


def test_a_bracket_acronym_replaces_the_words_it_spells(cat):
    assert names._collapse_acronyms("Cost and Management Accountant (CMA) Final") == "CMA Final"
    # one capital is a qualifier, not an acronym
    assert names._collapse_acronyms("Police Constable (Civil)") == "Police Constable (Civil)"


@pytest.mark.parametrize("cycle, official, label", [
    ("2026", "", "2026"),
    ("2026-27", "", "2026-27"),
    ("2026-22", "", "2026"),          # an edition number, not a span of years
    ("unknown", "Exam, 2025", "2025"),
])
def test_the_cycle_label(cycle, official, label):
    assert names._cycle_label(cycle, official) == label


def test_a_name_the_cutting_broke_is_refused():
    assert not names._whole("APPSC Brief Notifications, ( Batch) 2026-27")
    assert names._whole("JEE Main Session 1 2027")


def write(folder: Path, name: str, r: dict) -> Path:
    path = folder / name
    path.write_text(record.dumps(r), encoding="utf-8")
    return path


def test_fill_names_siblings_apart_and_reports_duplicates(tmp_path, cat, monkeypatch):
    monkeypatch.setattr(names.catalogue_mod, "load", lambda: cat)
    for n in (1, 2):
        write(tmp_path, f"eng-jee-main-2027-session-{n}.md",
              rec(f"Joint Entrance Examination Main, 2027 (Session {n})", aliases=["JEE Main"],
                  cycle="2027", slug=f"eng-jee-main-2027-session-{n}"))
    for group in ("d5", "mgt"):
        write(tmp_path, f"{group}-cat-2026.md", rec("Common Admission Test, 2026", aliases=["CAT"],
                                                     slug=f"{group}-cat-2026"))
    out = names.fill(tmp_path, apply=True, log=lambda s: None)
    assert {v[1] for v in out.renamed.values()} == {"JEE Main Session 1 2027", "JEE Main Session 2 2027"}
    assert out.duplicates == [("d5-cat-2026.md", "mgt-cat-2026.md")]
    assert record.load(tmp_path / "eng-jee-main-2027-session-1.md")[0]["title"] == "JEE Main Session 1 2027"


def test_a_title_set_by_hand_is_never_touched(tmp_path, cat, monkeypatch):
    monkeypatch.setattr(names.catalogue_mod, "load", lambda: cat)
    r = rec("Customer Service Associate (Clerk), 2026", exam="in-ibps-clerk")
    r["title"] = "IBPS Clerk (CSA) 2026"
    write(tmp_path, "a.md", r)
    out = names.fill(tmp_path, apply=True, log=lambda s: None)
    assert out.kept == 1 and not out.renamed
