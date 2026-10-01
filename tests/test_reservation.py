"""The reservation vocabulary: spellings map to one class, classes never merge."""

from __future__ import annotations

import pytest

from examhub_pipeline import catalogue as C
from examhub_pipeline import reservation as R

V = R.load()


def test_the_vocabulary_lints_clean():
    assert V.lint(set(C.load().jurisdictions)) == []


@pytest.mark.parametrize("text,jurisdiction,expected", [
    # Every spelling of the unreserved class is Unreserved.
    ("General", None, ["Unreserved"]),
    ("UR/EWS/OBC/SC/ST", None, ["Unreserved", "EWS", "OBC", "SC", "ST"]),
    ("Gen", None, ["Unreserved"]),
    ("UG", None, ["Unreserved"]),
    ("GT", "tn", ["Unreserved"]),
    ("GM", "ka", ["Unreserved"]),
    ("OM", "jk", ["Unreserved"]),
    ("OC", "tg", ["Unreserved"]),
    # ...but only where the notice's jurisdiction uses that spelling.
    ("GM", "in", []),
    # Different classes stay different.
    ("OBC-NCL", None, ["OBC-NCL"]),
    ("OBC (Non-Creamy Layer)", None, ["OBC-NCL"]),
    ("OBC", None, ["OBC"]),
    ("Most Backward Classes", None, []),
    ("Scheduled Castes (Arunthathiyar)", "tn", ["tn:SC(A)"]),
    ("SC Group II", "tg", ["tg:SC-II"]),
    ("Backward Class Muslims", "tn", ["tn:BCM"]),
    # A sub-class suffix the vocabulary does not know is not its prefix.
    ("BC-X", None, []),
    ("OBC-A", "up", []),
    ("OBC-A", "wb", ["wb:OBC-A"]),
    # Lower-case look-alikes are not classes.
    ("Ph.D in B.Sc", None, []),
    ("general studies", None, []),
    ("UG courses", None, []),
    # "All candidates" only stands alone.
    ("for all candidates", None, ["All candidates"]),
    ("women of all categories", None, ["Women"]),
    ("VH/HH/OH", None, ["PwBD-A", "PwBD-B", "PwBD-C"]),
])
def test_classes_in(text, jurisdiction, expected):
    assert V.classes_in(text, jurisdiction) == expected


def test_family_is_for_filtering_only():
    assert V.classes["hr:DSC"].family == "SC"
    assert V.classes_in("DSC", "hr") == ["hr:DSC"]
    assert V.short("hr:DSC") == "DSC"


def test_unmatched_leaves_what_the_vocabulary_does_not_know():
    assert V.unmatched("SC/ST/BC-X", None) == "/ /BC-X"


def test_lint_catches_a_claimed_twice_spelling_and_a_bad_family():
    bad = R.Vocabulary({"class": [
        {"id": "A", "axis": "vertical", "aliases": ["same"]},
        {"id": "B", "axis": "vertical", "aliases": ["same"], "family": "zz:X"},
        {"id": "kl:X", "axis": "vertical", "jurisdictions": ["kl"], "aliases": ["x"]},
    ]})
    errs = "\n".join(bad.lint({"kl"}))
    assert "claimed by both 'A' and 'B'" in errs
    assert "family 'zz:X' is not a national class" in errs
    assert "'kl:X': needs a `source`" in errs
