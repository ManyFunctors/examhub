"""Wayback copies: what is sent, what is skipped, and what survives a failure."""

import json

import httpx

from examhub_pipeline import archive


def setup(tmp_path, docs, done=()):
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "index.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    if done:
        (tmp_path / "archived.jsonl").write_text("".join(json.dumps(d) + "\n" for d in done))


def fake(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_an_existing_snapshot_is_used_and_a_new_one_saved(tmp_path):
    setup(tmp_path, [{"url": "https://a.in/old.pdf", "status": "ok"},
                     {"url": "https://a.in/new.pdf", "status": "ok"},
                     {"url": "https://a.in/bad.pdf", "status": "error"}])
    sent = []

    def handler(req):
        sent.append(str(req.url))
        if req.url.host == "archive.org":
            old = "old.pdf" in str(req.url)
            return httpx.Response(200, json={"archived_snapshots": {"closest": {
                "available": True, "url": "https://web.archive.org/web/1/https://a.in/old.pdf"}} if old else {}})
        return httpx.Response(200, headers={"content-location": "/web/2/https://a.in/new.pdf"})

    out = archive.run(directory=tmp_path, exams_dir=None, client=fake(handler), sleep=lambda s: None, log=lambda s: None)
    assert (out.found, out.archived, out.failed) == (1, 1, 0)
    assert not any("bad.pdf" in u for u in sent)
    rows = {r["url"]: r for r in map(json.loads, (tmp_path / "archived.jsonl").read_text().splitlines())}
    assert rows["https://a.in/new.pdf"]["snapshot"] == "https://web.archive.org/web/2/https://a.in/new.pdf"


def test_done_and_recently_failed_urls_are_skipped(tmp_path):
    setup(tmp_path, [{"url": "https://a.in/x.pdf", "status": "ok"}, {"url": "https://a.in/y.pdf", "status": "ok"}],
          [{"url": "https://a.in/x.pdf", "snapshot": "s"},
           {"url": "https://a.in/y.pdf", "error": "e", "tried": archive._now()}])
    out = archive.run(directory=tmp_path, exams_dir=None, client=fake(lambda r: 1 / 0), log=lambda s: None)
    assert out.skipped == 2 and not (out.found or out.archived or out.failed)


def test_a_rate_limit_ends_the_run_and_keeps_what_was_done(tmp_path):
    setup(tmp_path, [{"url": f"https://a.in/{n}.pdf", "status": "ok"} for n in range(3)])

    def handler(req):
        if req.url.host == "archive.org":
            return httpx.Response(200, json={"archived_snapshots": {}})
        return httpx.Response(429)

    out = archive.run(directory=tmp_path, exams_dir=None, client=fake(handler), sleep=lambda s: None, log=lambda s: None)
    assert out.stopped and out.archived == 0
    assert (tmp_path / "archived.jsonl").exists()


def test_a_url_that_keeps_failing_is_tried_less_often():
    assert [archive.wait_days({"failures": n}) for n in (1, 2, 3, 5)] == [7, 14, 28, 90]


def test_a_snapshot_reaches_the_record_that_links_the_document(tmp_path):
    from examhub_pipeline import record
    setup(tmp_path, [], [{"url": "https://a.in/n.pdf", "snapshot": "https://web.archive.org/web/1/https://a.in/n.pdf"}])
    exams = tmp_path / "exams"
    exams.mkdir()
    rec = {"title": "X", "links": {"documents": [
        {"document_url": "https://a.in/n.pdf", "document_archive": "not_archived"},
        {"document_url": "https://a.in/other.pdf", "document_archive": "not_archived"}]}}
    (exams / "x.md").write_text(record.dumps(rec))
    assert archive.fill_records(exams, directory=tmp_path, apply=True, log=lambda s: None) == 1
    docs = record.load(exams / "x.md")[0]["links"]["documents"]
    assert [d["document_archive"] for d in docs] == ["https://web.archive.org/web/1/https://a.in/n.pdf", "not_archived"]
