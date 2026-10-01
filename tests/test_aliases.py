"""An other name that names a different kind of eligibility test is dropped."""

from examhub_pipeline import aliases
from examhub_pipeline.catalogue import Catalogue

CAT = Catalogue(vocab={}, jurisdictions={}, feeds={}, bodies={},
                exams={"ka-kset": {"id": "ka-kset", "name": "Karnataka State Eligibility Test"}})


def test_a_tet_name_on_a_set_exam_is_wrong():
    rec = {"exam_id": "ka-kset", "title_official": "Karnataka State Eligibility Test, 2026",
           "title_aliases": ["KSET", "KTET", "Karnataka TET"]}
    assert aliases.wrong(rec, CAT) == ["KTET", "Karnataka TET"]


def test_a_shared_name_stays():
    rec = {"exam_id": "x", "title_official": "NEET (PG), 2027", "title_aliases": ["NEET", "NEET PG"]}
    assert aliases.wrong(rec, CAT) == []
