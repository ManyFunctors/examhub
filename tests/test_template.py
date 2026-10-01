"""The template checker, against the template itself and the site's records."""

import copy
import tomllib
from pathlib import Path

import pytest

from examhub_pipeline import template
from examhub_pipeline.record import split_front_matter

SITE = Path(__file__).resolve().parents[1] / "site" / "content" / "exams"


@pytest.fixture(scope="module")
def example() -> dict:
    return tomllib.loads(template.template_text())


def errors(record: dict) -> list[str]:
    return [str(p) for p in template.check(record) if p.level == "error"]


def test_the_template_passes_its_own_check(example):
    assert template.check(example) == []


def test_a_missing_key_is_an_error(example):
    rec = copy.deepcopy(example)
    del rec["posts"]["vacancies_status"]
    assert errors(rec) == ["posts: missing vacancies_status"]


def test_a_word_outside_the_list_is_an_error(example):
    rec = copy.deepcopy(example)
    rec["purpose"] = "Recruitment"
    assert len(errors(rec)) == 1 and "'Recruitment'" in errors(rec)[0]


def test_a_sentinel_may_stand_for_any_value(example):
    rec = copy.deepcopy(example)
    rec["posts"]["vacancies_total"] = "not_announced"
    rec["dates"]["stages"][0]["stage_parts"] = "unknown"
    assert errors(rec) == []


def test_a_window_needs_both_ends_or_neither(example):
    rec = copy.deepcopy(example)
    del rec["dates"]["application"]["to"]
    assert errors(rec) == ["dates.application: has only one of from/to"]


def test_a_number_where_a_date_belongs_is_an_error(example):
    rec = copy.deepcopy(example)
    rec["title"] = 2026
    assert errors(rec) == ["title: number where the template has text"]


@pytest.mark.skipif(not SITE.is_dir(), reason="no site records")
def test_every_site_record_passes():
    bad = {}
    for path in sorted(SITE.glob("*.md")):
        rec = tomllib.loads(split_front_matter(path.read_text(encoding="utf-8"))[0])
        found = [str(p) for p in template.check(rec)]
        if found:
            bad[path.name] = found[:3]
    assert bad == {}
