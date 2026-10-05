"""Merging the loops' work directories: documents copied, ledgers unioned."""

import json

from examhub_pipeline.loops import merge_work


def _loop(root, name, docs, ledger):
    base = root / name
    (base / "docs").mkdir(parents=True)
    (base / "state").mkdir(parents=True)
    for d in docs:
        (base / "docs" / d).write_text(f"body of {d}", encoding="utf-8")
    (base / "state" / "documents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in ledger), encoding="utf-8")
    return base


def test_documents_and_ledgers_from_every_loop_are_kept(tmp_path):
    a = _loop(tmp_path, "loop-a", ["a1.json", "shared.json"], [{"url": "a1"}, {"url": "shared"}])
    b = _loop(tmp_path, "loop-b", ["b1.json", "shared.json"], [{"url": "b1"}, {"url": "shared"}])
    dest = tmp_path / "work"

    stats = merge_work([a, b], dest)

    assert sorted(p.name for p in (dest / "docs").iterdir()) == ["a1.json", "b1.json", "shared.json"]
    assert stats == {"docs_copied": 3, "docs_already_there": 1, "ledger_lines": 3}
    rows = [json.loads(line) for line in (dest / "state" / "documents.jsonl").read_text().splitlines()]
    assert [r["url"] for r in rows] == ["a1", "shared", "b1"]


def test_a_loop_with_nothing_to_merge_is_fine(tmp_path):
    empty = tmp_path / "loop-empty"
    empty.mkdir()
    stats = merge_work([empty], tmp_path / "work")
    assert stats["docs_copied"] == 0
