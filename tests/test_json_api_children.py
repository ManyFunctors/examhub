"""json_api: one row per child (an SSC notice's attachments), backslash paths fixed."""
import json

from examhub_pipeline.crawl.adapters import json_api

FEED = {"id": "t/n", "body": "t", "yields": "notices", "items_path": "data", "children_path": "attachments",
        "fields": {"title": "headline", "url": "path", "date": "createdAt"},
        "url_template": "https://x.test/api/attachment/{url}"}


def test_each_attachment_is_a_row():
    body = json.dumps({"data": [
        {"headline": "Notice A", "createdAt": "2026-10-09T10:00:00Z",
         "attachments": [{"path": "uploads\\a\\one.pdf"}, {"path": "uploads\\a\\two.pdf"}]},
        {"headline": "No files", "attachments": []},
    ]})
    rows = list(json_api(FEED, "https://x.test/", body))
    assert [r["url"] for r in rows] == ["https://x.test/api/attachment/uploads/a/one.pdf",
                                         "https://x.test/api/attachment/uploads/a/two.pdf"]
    assert {r["title"] for r in rows} == {"Notice A"}
