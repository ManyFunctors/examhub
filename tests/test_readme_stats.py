"""The README's stats table, regenerated from the catalogue and site, not hand-edited."""
from pathlib import Path

from examhub_pipeline import readme_stats


def _readme(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "README.md"
    p.write_text(f"# ExamHub\n\n<!-- stats:start -->\n{body}\n<!-- stats:end -->\n\nmore text\n")
    return p


def test_replaces_only_whats_between_the_markers(tmp_path, monkeypatch):
    import examhub_pipeline.catalogue as catalogue_mod

    class FakeCat:
        def stats(self):
            return {"exams": 3, "bodies": 2, "feeds": 4}

    monkeypatch.setattr(catalogue_mod, "load", lambda: FakeCat())
    exams = tmp_path / "exams"
    exams.mkdir()
    (exams / "a.md").write_text("x")
    (exams / "b.md").write_text("x")
    harvest = tmp_path / "harvest"
    harvest.mkdir()

    readme = _readme(tmp_path, "stale numbers here")
    changed = readme_stats.fill(readme, apply=True, exams_dir=exams, directory=harvest, log=lambda *_: None)

    assert changed == 1
    text = readme.read_text()
    assert "stale numbers here" not in text
    assert "| Exam pages | 2 |" in text
    assert "| Exams in the catalogue | 3 |" in text
    assert "more text" in text  # untouched outside the markers


def test_unchanged_table_reports_no_change(tmp_path, monkeypatch):
    import examhub_pipeline.catalogue as catalogue_mod

    class FakeCat:
        def stats(self):
            return {"exams": 1, "bodies": 1, "feeds": 1}

    monkeypatch.setattr(catalogue_mod, "load", lambda: FakeCat())
    exams = tmp_path / "exams"
    exams.mkdir()
    harvest = tmp_path / "harvest"
    harvest.mkdir()

    first = readme_stats.table(exams, harvest)
    readme = _readme(tmp_path, first)
    assert readme_stats.fill(readme, apply=True, exams_dir=exams, directory=harvest, log=lambda *_: None) == 0


def test_missing_markers_is_a_no_op(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# ExamHub\n\nno markers here\n")
    assert readme_stats.fill(readme, apply=True, log=lambda *_: None) == 0
    assert readme.read_text() == "# ExamHub\n\nno markers here\n"


def test_a_partial_notice_copy_never_shrinks_the_shown_figure(tmp_path, monkeypatch):
    import examhub_pipeline.catalogue as catalogue_mod

    class FakeCat:
        def stats(self):
            return {"exams": 3, "bodies": 2, "feeds": 4}

    monkeypatch.setattr(catalogue_mod, "load", lambda: FakeCat())
    exams = tmp_path / "exams"
    exams.mkdir()
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    # 2,756 lines: what the harvest branch holds, against 56,000+ already shown.
    (harvest / "notices.jsonl").write_text("\n".join("{}" for _ in range(2756)) + "\n")
    readme = tmp_path / "README.md"
    readme.write_text(
        "<!-- stats:start -->\n| | |\n|---|---|\n| Notices seen so far | 56,000+ |\n<!-- stats:end -->\n"
    )
    logs: list[str] = []
    readme_stats.fill(readme, apply=True, exams_dir=exams, directory=harvest, log=logs.append)
    assert "| Notices seen so far | 56,000+ |" in readme.read_text()
    assert any("kept 56,000+" in line for line in logs)


def test_the_links_fill_keeps_the_record_page_when_nothing_was_checked():
    from examhub_pipeline import links

    class FakeCat:
        exams = {"e1": {"official_url": "https://guess.example/"}}
        bodies = {}

    rec = {
        "exam_id": "e1",
        "title": "Some Exam 2026",
        "links": {"link_official_page": "https://kept.example/exam", "link_apply": "unknown", "documents": []},
    }
    links.fix(rec, FakeCat(), checks={})
    assert rec["links"]["link_official_page"] == "https://kept.example/exam"
