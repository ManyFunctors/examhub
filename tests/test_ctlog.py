"""crt.sh database lookup: oldest-queried domains first, within a time budget."""
from examhub_pipeline.crawl import ctlog


class FakeConn:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if params:
            self.asked.append(params["d"])
        self._last = self.rows.get(params["d"], []) if params else []
        return self

    def fetchall(self):
        return self._last


def test_oldest_queried_first_and_marked():
    conn = FakeConn({"nta.nic.in": [("neet.nta.nic.in", "2026-09-01 00:00:00")]})
    cursors = {"crtsh:upsc.gov.in": "2026-09-30"}
    out = ctlog.lookup(["upsc.gov.in", "nta.nic.in"], cursors, connect=lambda: conn)
    assert conn.asked == ["nta.nic.in", "upsc.gov.in"]
    assert out["nta.nic.in"] == [{"name_value": "neet.nta.nic.in", "not_before": "2026-09-01 00:00:00"}]
    assert cursors["crtsh:nta.nic.in"] > "2026"


def test_budget_stops_the_run_and_an_unreachable_database_is_no_crash():
    ticks = iter([0, 0, 999, 999])
    conn = FakeConn({})
    out = ctlog.lookup(["a.in", "b.in"], {}, budget=10, connect=lambda: conn, clock=lambda: next(ticks))
    assert list(out) == ["a.in"]

    def down():
        raise OSError("no route")
    assert ctlog.lookup(["a.in"], {}, connect=down) == {}
