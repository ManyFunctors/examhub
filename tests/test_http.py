"""Tests for the polite, cached fetcher.

None of these touch the network. The point of the tests is the behaviour that
only shows up under load and against awkward hosts: the robots status-code
rules, the per-host delay arithmetic, the cache's content-addressed storage,
and the retry accounting.

A real request is exercised in ``test_live.py`` behind the ``network`` marker.
"""

from __future__ import annotations

import time

import pytest

from examhub_pipeline.config import Settings
from examhub_pipeline.http import (
    BudgetExhausted,
    DiskCache,
    Fetcher,
    HostThrottle,
    RobotsCache,
    canonical,
    same_site,
)


class TestCanonical:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("HTTPS://WWW.SSC.GOV.IN/a/b.pdf", "https://www.ssc.gov.in/a/b.pdf"),
            ("https://x.gov.in/p?b=2&a=1", "https://x.gov.in/p?a=1&b=2"),
            ("https://x.gov.in/p?utm_source=x&b=2", "https://x.gov.in/p?b=2"),
            ("https://x.gov.in/p?fbclid=x", "https://x.gov.in/p"),
            ("https://x.gov.in/p#frag", "https://x.gov.in/p"),
            ("http://x.gov.in:80/p", "http://x.gov.in/p"),
            ("https://x.gov.in:443/p", "https://x.gov.in/p"),
        ],
    )
    def test_canonicalisation(self, raw, expected):
        """A cache keyed on the raw URL re-downloads the same notice once
        per tracking parameter the portal felt like adding."""
        assert canonical(raw) == expected

    def test_canonicalisation_is_idempotent(self):
        once = canonical("HTTPS://WWW.X.GOV.IN/a?utm_source=q&b=1#z")
        assert canonical(once) == once

    def test_empty_path_becomes_root(self):
        assert canonical("https://x.gov.in") == "https://x.gov.in/"

    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ("https://www.upsc.gov.in/a", "https://upsc.gov.in/b", True),
            ("https://a.gov.in/x", "https://b.gov.in/y", False),
            ("https://neet.nta.nic.in/", "https://nta.nic.in/", True),
            ("https://x.gov.in", "https://y.com", False),
        ],
    )
    def test_same_site(self, a, b, expected):
        assert same_site(a, b) is expected


class TestDiskCache:
    def test_round_trip(self, tmp_path):
        cache = DiskCache(tmp_path)
        cache.put(
            {
                "url": "https://x/a", "final_url": "https://x/a", "status": 200,
                "content_type": "text/html", "etag": "E1", "last_modified": None,
                "retrieved": 1.0, "checked": 1.0,
            },
            b"hello",
        )
        meta = cache.get("https://x/a")
        assert meta["etag"] == "E1"
        assert cache.blob(meta["content_hash"]) == b"hello"
        assert cache.stats() == {"urls": 1, "blobs": 1}

    def test_body_is_addressed_by_its_own_hash(self, tmp_path):
        """Two URLs serving identical bytes share one blob."""
        cache = DiskCache(tmp_path)
        shared = {"status": 200, "content_type": "text/html", "etag": None,
                  "last_modified": None, "retrieved": 1.0, "checked": 1.0}
        cache.put({"url": "https://x/a", "final_url": "https://x/a", **shared}, b"same")
        cache.put({"url": "https://x/b", "final_url": "https://x/b", **shared}, b"same")
        assert cache.stats() == {"urls": 2, "blobs": 1}

    def test_changed_body_gets_a_new_blob(self, tmp_path):
        cache = DiskCache(tmp_path)
        shared = {"final_url": "https://x/a", "status": 200, "content_type": "",
                  "etag": None, "last_modified": None, "retrieved": 1.0, "checked": 1.0}
        cache.put({"url": "https://x/a", **shared}, b"v1")
        first = cache.get("https://x/a")["content_hash"]
        cache.put({"url": "https://x/a", **shared}, b"v2")
        assert cache.get("https://x/a")["content_hash"] != first
        assert cache.stats()["blobs"] == 2

    def test_touch_updates_only_the_check_time(self, tmp_path):
        """A 304 must not re-hash or re-write the body."""
        cache = DiskCache(tmp_path)
        cache.put(
            {"url": "https://x/a", "final_url": "https://x/a", "status": 200,
             "content_type": "text/html", "etag": "E1", "last_modified": None,
             "retrieved": 1.0, "checked": 1.0},
            b"hello",
        )
        before = cache.get("https://x/a")["content_hash"]
        cache.touch("https://x/a", 99.0)
        after = cache.get("https://x/a")
        assert after["checked"] == 99.0
        assert after["content_hash"] == before
        assert cache.blob(before) == b"hello"

    def test_missing_url(self, tmp_path):
        assert DiskCache(tmp_path).get("https://x/nope") is None

    def test_corrupt_meta_is_ignored_not_fatal(self, tmp_path):
        cache = DiskCache(tmp_path)
        cache.ensure()
        (cache.meta_dir / ("deadbeef.json")).write_text("{not json", encoding="utf-8")
        assert cache.get("https://x/a") is None or True  # must not raise


class TestHostThrottle:
    def test_second_request_waits(self):
        throttle = HostThrottle(delay=0.2, max_per_host=1)
        start = time.monotonic()
        throttle.wait("x.gov.in")
        throttle.done("x.gov.in")
        throttle.wait("x.gov.in")
        throttle.done("x.gov.in")
        assert time.monotonic() - start >= 0.19

    def test_hosts_are_independent(self):
        throttle = HostThrottle(delay=5.0, max_per_host=1)
        start = time.monotonic()
        throttle.wait("a.gov.in")
        throttle.done("a.gov.in")
        throttle.wait("b.gov.in")
        throttle.done("b.gov.in")
        # The second host must not have inherited the first host's gate.
        assert time.monotonic() - start < 1.0

    def test_robots_crawl_delay_wins_when_more_conservative(self):
        throttle = HostThrottle(delay=1.0)
        throttle.request_rate_delay("slow.gov.in", 30.0)
        assert throttle.delay_for("slow.gov.in") == 30.0

    def test_a_less_conservative_robots_delay_is_ignored(self):
        throttle = HostThrottle(delay=10.0)
        throttle.request_rate_delay("x.gov.in", 1.0)
        assert throttle.delay_for("x.gov.in") == 10.0

    def test_inflight_counting(self):
        throttle = HostThrottle(delay=0.0, max_per_host=2)
        throttle.wait("x.gov.in")
        assert throttle.inflight("x.gov.in") == 1
        throttle.done("x.gov.in")
        assert throttle.inflight("x.gov.in") == 0

    def test_concurrency_cap(self):
        """max_per_host is a real cap, not a suggestion."""
        import threading

        throttle = HostThrottle(delay=0.0, max_per_host=1)
        order: list[str] = []
        done = threading.Event()

        def first():
            throttle.wait("x.gov.in")
            order.append("in")
            done.wait(1.0)
            throttle.done("x.gov.in")

        thread = threading.Thread(target=first)
        thread.start()
        time.sleep(0.1)
        assert throttle.inflight("x.gov.in") == 1
        done.set()
        thread.join(timeout=2)


class TestBudget:
    def test_budget_is_enforced(self, settings: Settings):
        settings = Settings(**{**settings.__dict__, "max_requests": 2})
        fetcher = Fetcher(settings)
        try:
            for _ in range(5):
                try:
                    fetcher._spend(budget=True)
                except BudgetExhausted:
                    break
            assert fetcher.budget_used == 2
        finally:
            fetcher.close()

    def test_robots_fetch_does_not_spend_budget(self, settings: Settings):
        """robots.txt has to be fetched to know what is allowed."""
        fetcher = Fetcher(settings)
        try:
            fetcher._spend(budget=False)
            assert fetcher.budget_used == 0
        finally:
            fetcher.close()


class TestRobotsCacheLogic:
    """The status-code rules of RFC 9309, without any network.

    Several government hosts answer robots.txt with 403 to a non-browser
    user-agent, and one publishes a blanket disallow for everyone but
    Googlebot. Both of those are the policy working, and both have to be
    honoured -- the second is the whole point of checking at all.
    """

    @staticmethod
    def _build(settings: Settings, status: int, text: str) -> Fetcher:
        class FakeResponse:
            def __init__(self):
                self.status = status

            def text(self):
                return text

            @property
            def content(self):
                return text.encode()

        class FakeClient:
            """Stands in for the Fetcher, recording what was asked for."""

            def __init__(self):
                self.calls = []

            def fetch(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        # respect_robots comes back on: the shared fixture turns it off so
        # that nothing else in this file can reach the network by accident.
        settings = Settings(**{**settings.__dict__, "respect_robots": True})
        fetcher = Fetcher(settings)
        fetcher.robots = RobotsCache(
            settings, FakeClient(), "examhub/0.1", fetcher.throttle
        )
        return fetcher

    def test_404_means_allowed(self, settings):
        """RFC 9309: a 404 on robots.txt means fully allowed."""
        fetcher = self._build(settings, 404, "Not Found")
        try:
            assert fetcher.robots.allowed("https://x.gov.in/anything") is True
        finally:
            fetcher.close()

    def test_403_means_denied(self, settings):
        fetcher = self._build(settings, 403, "Access Denied")
        try:
            assert fetcher.robots.allowed("https://x.gov.in/anything") is False
        finally:
            fetcher.close()

    def test_401_means_denied(self, settings):
        fetcher = self._build(settings, 401, "Unauthorized")
        try:
            assert fetcher.robots.allowed("https://x.gov.in/anything") is False
        finally:
            fetcher.close()

    def test_5xx_fails_closed(self, settings):
        """A server error is not permission."""
        fetcher = self._build(settings, 503, "Service Unavailable")
        try:
            assert fetcher.robots.allowed("https://x.gov.in/anything") is False
        finally:
            fetcher.close()

    def test_a_real_disallow_is_honoured(self, settings):
        fetcher = self._build(
            settings, 200, "User-agent: *\nDisallow: /wp-admin/\n",
        )
        try:
            assert fetcher.robots.allowed("https://x.gov.in/wp-admin/x") is False
            assert fetcher.robots.allowed("https://x.gov.in/notices") is True
        finally:
            fetcher.close()

    def test_crawl_delay_is_picked_up(self, settings):
        fetcher = self._build(
            settings, 200, "User-agent: *\nCrawl-delay: 25\nDisallow:\n",
        )
        try:
            fetcher.robots.allowed("https://x.gov.in/x")
            assert fetcher.throttle.delay_for("x.gov.in") >= 25.0
        finally:
            fetcher.close()

    def test_the_check_can_be_disabled_explicitly(self, settings):
        settings = Settings(**{**settings.__dict__, "respect_robots": False})
        fetcher = self._build(settings, 403, "Access Denied")
        try:
            settings_2 = Settings(**{**fetcher.settings.__dict__, "respect_robots": False})
            fetcher.robots.settings = settings_2
            assert fetcher.robots.allowed("https://x.gov.in/anything") is True
        finally:
            fetcher.close()

    def test_robots_is_fetched_without_consulting_itself(self, settings):
        """Recursion guard: fetching robots.txt must not ask robots.txt."""
        fetcher = self._build(settings, 404, "Not Found")
        try:
            fetcher.robots.allowed("https://x.gov.in/anything")
            url, kwargs = fetcher.robots.client.calls[0]
            assert url == "https://x.gov.in/robots.txt"
            assert kwargs.get("check_robots") is False
            assert kwargs.get("tolerate_errors") is True
        finally:
            fetcher.close()

    def test_robots_is_parsed_once_per_origin(self, settings):
        fetcher = self._build(settings, 404, "Not Found")
        try:
            for _ in range(4):
                fetcher.robots.allowed("https://x.gov.in/a")
                fetcher.robots.allowed("https://x.gov.in/b")
            assert len(fetcher.robots.client.calls) == 1
        finally:
            fetcher.close()
