"""A notice with a stray line-separator character in its text must survive a round trip."""
from examhub_pipeline.crawl import harvest


def test_read_jsonl_keeps_a_line_with_nel_and_line_separator(tmp_path):
    path = tmp_path / "n.jsonl"
    rows = [{"id": "a", "url": "https://x/\u0085name"}, {"id": "b", "title": "two parts"}]
    harvest.write_jsonl(path, rows)
    assert harvest.read_jsonl(path) == rows
