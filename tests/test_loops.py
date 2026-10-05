"""The loop plan: one CI loop per jurisdiction, split so no loop is too big."""

from types import SimpleNamespace

from examhub_pipeline import priority


def _cat(feeds_per_state: dict[str, int], inactive: int = 0):
    feeds, bodies = {}, {}
    for state, n in feeds_per_state.items():
        bodies[f"{state}-body"] = {"jurisdiction": state}
        for i in range(n):
            feeds[f"{state}-{i:03d}"] = {"body": f"{state}-body", "adapter": "html_links",
                                         "status": "active"}
    for i in range(inactive):
        feeds[f"off-{i}"] = {"body": "ap-body", "adapter": "html_links", "status": "inactive"}
    return SimpleNamespace(feeds=feeds, bodies=bodies)


def test_one_loop_per_small_jurisdiction():
    plan = priority.loop_plan(_cat({"ap": 3, "up": 5}))
    assert [p["bucket"] for p in plan] == ["ap", "up"]
    assert plan[0]["sources"] == "ap-000,ap-001,ap-002"


def test_a_large_jurisdiction_is_split_into_chunks():
    plan = priority.loop_plan(_cat({"in": priority.LOOP_MAX_FEEDS * 2 + 1}))
    assert [p["bucket"] for p in plan] == ["in-1", "in-2", "in-3"]
    assert max(len(p["sources"].split(",")) for p in plan) == priority.LOOP_MAX_FEEDS
    all_keys = [k for p in plan for k in p["sources"].split(",")]
    assert len(all_keys) == len(set(all_keys)) == priority.LOOP_MAX_FEEDS * 2 + 1


def test_inactive_and_non_html_feeds_are_left_out():
    cat = _cat({"ap": 2}, inactive=3)
    cat.feeds["pdf-feed"] = {"body": "ap-body", "adapter": "pdf_links", "status": "active"}
    plan = priority.loop_plan(cat)
    assert plan[0]["sources"] == "ap-000,ap-001"
