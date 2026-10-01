"""Discovery: new exam series and sources from the harvest, and adopting them."""

from __future__ import annotations

import shutil

import pytest

from examhub_pipeline import catalogue as C
from examhub_pipeline import discovery as D


@pytest.fixture(scope="module")
def cat():
    return C.load()


@pytest.fixture
def no_ignores(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "IGNORE_FILE", tmp_path / "none.toml")


def notice(i, title, body="cg-cgpsc", doc_type="notification", **kw):
    return {"id": f"{i:064x}", "body": body, "feed": f"{body}/x", "title": title,
            "url": f"https://example.gov.in/{i}.pdf", "doc_type": doc_type,
            "first_seen": "2026-09-01T00:00:00+05:30", **kw}


@pytest.mark.parametrize("title,expected", [
    ("Admit card for Zircon Surveyor Exam 2025", [("Zircon Surveyor", "Exam")]),
    ("Result of Junior Legal Officer Examination-2024", [("Junior Legal Officer", "Examination")]),
    ("Notice regarding postponement of examination", []),
])
def test_series_names(title, expected):
    assert D.series_names(title) == expected


def test_new_series_needs_repeated_evidence(cat, no_ignores):
    notices = [
        notice(1, "Advertisement for Zircon Surveyor Exam 2025"),
        notice(2, "Model answers of Zircon Surveyor Exam 2025", doc_type="answer_key"),
        notice(3, "Result of Quartz Warden Exam 2024", doc_type="result"),
    ]
    exams, _ = D.discover(cat, notices)
    by_id = {p["entry"]["id"]: p for p in exams}
    assert "cg-cgpsc-zircon-surveyor" in by_id
    entry = by_id["cg-cgpsc-zircon-surveyor"]["entry"]
    assert entry["conducted_by"] == "cg-cgpsc" and entry["purpose"] == "recruitment"
    # one result notice is not a series yet
    assert not any("quartz" in i for i in by_id)


def test_ignore_names_drop_fragments(cat, monkeypatch, tmp_path):
    ignore = tmp_path / "ignore.toml"
    ignore.write_text("ignore_names = ['^zircon']\n")
    monkeypatch.setattr(D, "IGNORE_FILE", ignore)
    notices = [notice(1, "Advertisement for Zircon Surveyor Exam 2025"),
               notice(2, "Syllabus for Zircon Surveyor Exam 2025")]
    exams, _ = D.discover(cat, notices)
    assert not any("zircon" in p["id"] for p in exams)


def test_url_key():
    assert D._url_key("https://www.X.gov.in/notices/") == D._url_key("http://x.gov.in/notices")


def test_source_proposals_need_matches_and_skip_known_feeds(cat, no_ignores):
    known = next(f for f in cat.feeds.values() if f["body"] == "cg-cgpsc")
    pages = [
        {"id": "https://psc.cg.gov.in/new-board.html", "body": "cg-cgpsc", "text": "New Board",
         "matched": 3, "notices": 10},
        {"id": "https://psc.cg.gov.in/one.html", "body": "cg-cgpsc", "text": "One", "matched": 1},
        {"id": known["url"].replace("https://", "http://"), "body": "cg-cgpsc", "text": "Known",
         "matched": 9},
    ]
    feeds = [{"id": "https://psc.cg.gov.in/feed/", "body": "cg-cgpsc", "title": "RSS", "matched": 1}]
    props = D.source_proposals(cat, pages, feeds)
    urls = sorted(p["entry"]["url"] for p in props)
    assert urls == ["https://psc.cg.gov.in/feed/", "https://psc.cg.gov.in/new-board.html"]
    rss = next(p for p in props if p["entry"]["adapter"] == "rss")
    assert rss["id"].startswith("feed:cg-cgpsc:")


# -- adopting ---------------------------------------------------------------


@pytest.fixture
def catdir(tmp_path):
    d = tmp_path / "catalogue"
    shutil.copytree(C.CATALOGUE_DIR, d)
    return d


NEW_EXAM = """
[[exams]]
id = "cg-cgpsc-zircon-surveyor"
name = "CGPSC Zircon Surveyor Examination"
jurisdiction = "cg"
purpose = "recruitment"
conducted_by = "cg-cgpsc"
frequency = "irregular"
match = { any = ['Zircon\\W+Surveyor'] }
status = "active"
"""


def test_add_writes_to_the_jurisdiction_file(catdir):
    counts, errors = C.add(NEW_EXAM, catdir)
    assert errors == [] and counts.get("exams") == 1
    assert "cg-cgpsc-zircon-surveyor" in (catdir / "cg.toml").read_text()
    assert C.lint(C.load(catdir)) == []
    assert C.fmt(catdir) == []  # already canonical


def test_add_refuses_existing_ids_and_lint_errors(catdir, cat):
    existing = next(iter(e for e in cat.exams.values() if e["jurisdiction"] == "cg"))
    snippet = NEW_EXAM.replace("cg-cgpsc-zircon-surveyor", existing["id"])
    _, errors = C.add(snippet, catdir)
    assert errors and existing["id"] in errors[0]

    broken = NEW_EXAM.replace('conducted_by = "cg-cgpsc"', 'conducted_by = "cg-nobody"')
    before = (catdir / "cg.toml").read_text()
    _, errors = C.add(broken, catdir)
    assert errors
    assert (catdir / "cg.toml").read_text() == before
