"""Sources with an exam date coming up soon are picked for tonight's recheck."""
import datetime as dt

from examhub_pipeline import priority


def _rec(body: str, **dates) -> dict:
    return {"bodies": [{"body": body, "body_role": "conducts"}], "dates": dates}


def test_a_record_due_soon_is_picked_over_one_due_later(tmp_path, monkeypatch):
    exams = tmp_path / "exams"
    exams.mkdir()
    today = dt.date(2026, 10, 1)

    from examhub_pipeline import record as record_mod

    def fake_load(path):
        name = path.stem
        if name == "soon":
            return _rec("in-ibps", application={"to": dt.date(2026, 10, 3)}), ""
        return _rec("in-upsc", application={"to": dt.date(2027, 6, 1)}), ""

    monkeypatch.setattr(record_mod, "load", fake_load)
    (exams / "soon.md").write_text("x")
    (exams / "later.md").write_text("x")

    due = priority.due_bodies(exams, within_days=5, today=today)
    assert due == {"in-ibps": dt.date(2026, 10, 3)}


def test_a_past_date_does_not_count_as_due(tmp_path, monkeypatch):
    exams = tmp_path / "exams"
    exams.mkdir()
    today = dt.date(2026, 10, 1)

    from examhub_pipeline import record as record_mod
    monkeypatch.setattr(
        record_mod, "load",
        lambda path: (_rec("in-ssc", application={"to": dt.date(2026, 9, 1)}), ""),
    )
    (exams / "a.md").write_text("x")

    assert priority.due_bodies(exams, within_days=5, today=today) == {}


def test_due_sources_maps_the_body_to_its_seed_source_by_short_name(tmp_path, monkeypatch):
    # Against the real catalogue, a record naming a body with a seed source
    # (IBPS) resolves to that source's key.
    exams = tmp_path / "exams"
    exams.mkdir()
    today = dt.date(2026, 10, 1)
    from examhub_pipeline import record as record_mod

    monkeypatch.setattr(
        record_mod, "load",
        lambda path: (_rec("in-ibps", application={"to": dt.date(2026, 10, 3)}), ""),
    )
    (exams / "a.md").write_text("x")

    assert priority.due_sources(exams, within_days=5, today=today) == ["ibps"]


def test_rotation_source_is_deterministic_for_a_given_day():
    today = dt.date(2026, 10, 1)
    assert priority.rotation_source(today) == priority.rotation_source(today)


def test_tonight_sources_tops_up_with_rotation_when_nothing_is_due(tmp_path):
    exams = tmp_path / "exams"
    exams.mkdir()
    today = dt.date(2026, 10, 1)
    sources = priority.tonight_sources(exams, within_days=5, cap=3, today=today)
    assert sources == [priority.rotation_source(today)]
