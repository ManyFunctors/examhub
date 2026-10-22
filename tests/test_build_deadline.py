"""A build that runs out of time still saves its index and profiles."""

from examhub_pipeline.crawl import harvest, ingest


def test_build_past_its_deadline_saves_what_it_has(tmp_path, monkeypatch):
    work, out = tmp_path / "work", tmp_path / "harvest"
    work.mkdir()
    rows = []
    for n in range(3):
        pdf = work / f"{n}.pdf"
        pdf.write_bytes(b"%PDF-1.4 not really")
        rows.append({"id": f"n{n}", "status": "fetched", "pdf": str(pdf), "tried": "2026-10-17T00:00:00+00:00",
                     "notice": {"id": f"n{n}", "body": "b", "exam": None, "title": "t", "url": f"https://x/{n}.pdf"}})
    harvest.write_jsonl(work / "fetched.jsonl", rows)
    monkeypatch.setenv("EXAMHUB_BUILD_SECONDS", "0")  # already out of time after the first PDF
    monkeypatch.setattr(ingest, "refresh_profiles", lambda directory=None: {"profiles": 0})
    counts = ingest.build(work, out, jobs=1)
    assert counts["ok"] + counts["failed"] + counts["skipped"] == 3
    assert (out / "documents" / "index.jsonl").exists()
    assert not (work / "fetched.jsonl").exists()  # consumed, so a second build is not double counted
