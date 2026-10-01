"""Tests for the seed registry and deterministic link classification.

Discovery is the only place this tool touches other people's servers before
anyone has looked at a diff, so the classifier has to be conservative in the
direction that costs the host something: a false positive is a request to
someone else's government web server, and a false negative is a notice a
maintainer has to find by hand.
"""

from __future__ import annotations

import pytest

from examhub_pipeline.sources import (
    SEED_SOURCES,
    Source,
    classify_links,
    get_source,
    get_source_by_url,
    infer_tier,
    is_document_url,
    looks_like_notice,
    name_date_hint,
    priority_for,
    tier_for,
)


class TestRegistry:
    def test_the_registry_is_not_empty(self):
        assert len(SEED_SOURCES) >= 20

    def test_keys_are_unique(self):
        keys = [s.key for s in SEED_SOURCES]
        assert len(keys) == len(set(keys))

    def test_every_source_has_a_usable_notices_url(self):
        for source in SEED_SOURCES:
            assert source.notices_url.startswith("https://"), source.key
            assert source.host, source.key

    def test_every_source_documents_its_own_host(self):
        """Otherwise every discovery hit would be dropped as off-site."""
        for source in SEED_SOURCES:
            assert source.host in source.document_hosts, source.key

    def test_exam_kind_implies_a_category(self):
        job = Source("k", "n", "https://x.gov.in/", exam_kind="job")
        assert job.default_category == "Government"
        admission = Source("k", "n", "https://x.gov.in/", exam_kind="admission")
        assert admission.default_category == "Academic"

    def test_lookup_by_key(self):
        assert get_source("ssc").name.startswith("Staff Selection")
        assert get_source("nope") is None

    def test_lookup_by_url_prefers_the_most_specific_source(self):
        assert get_source_by_url("https://ugcnet.nta.ac.in/").key == "ugcnet"
        assert get_source_by_url("https://ssc.gov.in/uploads/x.pdf").key == "ssc"

    def test_the_most_specific_source_wins(self):
        """
        NTA's suffix match on ugcnet.nta.ac.in is ten characters; UGC NET's
        exact match is the whole fifteen. Ranking by "exact beats suffix"
        alone got this backwards, because NTA also lists the exam subdomains
        as document hosts.
        """
        assert get_source_by_url("https://nta.nic.in/x").key == "nta"
        assert get_source_by_url("https://nta.ac.in/").key == "nta"
        assert get_source_by_url("https://ugcnet.nta.ac.in/").key == "ugcnet"
        assert get_source_by_url("https://neet.nta.nic.in/").key == "neet"
        assert get_source_by_url("https://www.ugc.gov.in/").key == "ugcnet"

    def test_lookup_by_url_returns_none_for_an_unknown_host(self):
        assert get_source_by_url("https://example.com/x") is None


class TestTierInference:
    @pytest.mark.parametrize(
        "text,url,expected",
        [
            ("Corrigendum", "https://x.gov.in/c.pdf", "corrigendum"),
            ("Addendum to the notice", "https://x.gov.in/a.pdf", "corrigendum"),
            ("Press Release", "https://x.gov.in/p.pdf", "press_release"),
            ("Postponement of the examination", "https://x.gov.in/p.pdf", "press_release"),
            ("Notification for recruitment", "https://x.gov.in/n.pdf", "notification_pdf"),
            ("Advertisement for the post of", "https://x.gov.in/a.pdf", "notification_pdf"),
            ("Key Dates", "https://x.gov.in/kd", "official_portal"),
            ("", "https://x.gov.in/dates", "official_portal"),
        ],
    )
    def test_tiers(self, text, url, expected):
        assert infer_tier(text, url) == expected

    def test_a_pdf_with_no_word_is_a_notification(self):
        assert infer_tier("Download", "https://x.gov.in/a.pdf") == "notification_pdf"

    def test_tier_for_never_returns_an_unknown_value(self):
        for text, url in [("", ""), ("x", "y"), ("corrigendum", "z")]:
            assert tier_for(text, url) in {
                "notification_pdf", "official_portal", "corrigendum",
                "press_release", "other",
            }


class TestNoticeDetection:
    @pytest.mark.parametrize(
        "text,url,expected",
        [
            # Real notification PDFs must be kept.
            ("Combined Graduate Level Examination 2026", "https://ssc.gov.in/x/cgl2026.pdf", True),
            ("Notice for Recruitment of Constable", "https://x.gov.in/notice/2026-07-01-police.pdf", True),
            ("Civil Services Preliminary Examination 2027 Notification", "https://upsc.gov.in/2027/notice.pdf", True),
            ("Examination Schedule of UGC-NET June 2025", "https://ugcnet.nta.ac.in/images/schedule.pdf", True),
            ("Extension of last date for submission", "https://x.gov.in/images/extension.pdf", True),
            # Navigation must not.
            ("Home", "https://ssc.gov.in/", False),
            ("Login", "https://ssc.gov.in/login.aspx", False),
            ("About Us", "https://x.gov.in/about", False),
            ("Tenders", "https://x.gov.in/tender.pdf", False),
            ("Contact Us", "https://x.gov.in/contact", False),
            ("Results 2011", "https://x.gov.in/results2011.html", False),
            # A scan with a meaningless name is not a notice.
            ("scan0001", "https://ssc.gov.in/uploads/scan0001.pdf", False),
            # Fragment and non-navigable schemes.
            ("", "#main-content", False),
            ("Skip to main content", "https://x.gov.in/page#main-content", False),
            ("Mail", "mailto:help@x.gov.in", False),
        ],
    )
    def test_classification(self, text, url, expected):
        assert looks_like_notice(text, url) is expected

    def test_is_document_url(self):
        assert is_document_url("https://x.gov.in/a.pdf")
        assert is_document_url("https://x.gov.in/a.pdf?download=1")
        assert not is_document_url("https://x.gov.in/a.aspx")

    def test_an_html_notice_page_must_look_dated(self):
        assert looks_like_notice("Notice 2026", "https://x.gov.in/notice")
        assert not looks_like_notice("Notice", "https://x.gov.in/notice")


class TestNameDateHint:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://x.gov.in/a/advt_15-06-2027.pdf", "2027-06-15"),
            ("https://x.gov.in/a/advt_2027-06-15.pdf", "2027-06-15"),
            ("https://x.gov.in/a/n_15_06_2027.pdf", "2027-06-15"),
            ("https://x.gov.in/a/cgl2026.pdf", "2026"),
            ("https://x.gov.in/a/x.pdf", None),
            # A day and month with no year is a fragment, never a date.
            ("https://x.gov.in/a/advt_15-06.pdf", "15-06"),
            # 13 is not a month, so there is no date here at all.
            ("https://x.gov.in/a/advt_15-13-2027.pdf", "2027"),
        ],
    )
    def test_hints(self, url, expected):
        assert name_date_hint("", url) == expected

    def test_a_hint_is_never_a_usable_value(self):
        for url in ("https://x.gov.in/advt_15-06-2027.pdf", "https://x.gov.in/cgl2026.pdf"):
            hint = name_date_hint("", url)
            assert hint is not None
            if hint.count("-") == 2:
                import datetime as _dt

                _dt.date.fromisoformat(hint)  # a real ISO date, sortably


class TestPriority:
    def test_a_self_describing_notice_outranks_a_read_more_link(self):
        """
        nta.ac.in has 344 PDFs all linked as "Read More". With a request
        budget, the budget has to go to the links that say what they are, or
        the run spends its whole allowance on whichever ones happened to
        appear first in the HTML.
        """
        described = priority_for(
            "Examination Schedule of UGC - NET June 2025 - reg.",
            "https://ugcnet.nta.ac.in/images/public-notice-for-schedule.pdf",
        )
        anonymous = priority_for(
            "Read More", "https://nta.ac.in/Download/Notice/Notice_20260925215817.pdf"
        )
        assert described > anonymous + 30

    def test_navigation_is_deprioritised(self):
        assert priority_for("Home", "https://ssc.gov.in/") < 20

    def test_priority_is_bounded(self):
        for text in ("", "Read More", "Notification 2026 admission of corigendum"):
            for url in ("https://x.gov.in/a.pdf", "https://x.gov.in/2026-07-01/notice"):
                value = priority_for(text, url)
                assert 0 <= value <= 100


class TestClassifyLinks:
    @pytest.fixture
    def source(self):
        return Source(
            key="x", name="Test Commission", notices_url="https://x.gov.in/notices",
            document_hosts=("x.gov.in", "cdn.x.gov.in"),
        )

    def test_off_host_links_are_dropped(self, source):
        # Distinct anchors, because identical ones are deduplicated as the
        # same document -- which is the point of the next test.
        links = [
            ("Notification for Constable 2026", "https://elsewhere.com/notice.pdf"),
            ("Notification for Sub Inspector 2026", "https://cdn.x.gov.in/notice.pdf"),
            ("Notification for Driver 2026", "https://x.gov.in/notice.pdf"),
        ]
        refs = list(classify_links(links, source))
        assert [r.url for r in refs] == [
            "https://cdn.x.gov.in/notice.pdf",
            "https://x.gov.in/notice.pdf",
        ]

    def test_subdomains_are_allowed(self, source):
        refs = list(classify_links([("Notice 2026", "https://www.x.gov.in/n.pdf")], source))
        assert len(refs) == 1

    def test_lookalike_host_is_rejected(self, source):
        # notx.gov.in must not be treated as x.gov.in.
        # A prefix match on the last two labels is how a crawler ends up
        # politely fetching from somebody entirely different.
        refs = list(classify_links([("Notice 2026", "https://notx.gov.in/n.pdf")], source))
        assert refs == []

    def test_the_same_url_is_collapsed(self, source):
        links = [
            ("Notice B 2026", "https://x.gov.in/b.pdf"),
            ("Notice A 2026", "https://x.gov.in/a.pdf"),
            ("Notice B 2026", "https://x.gov.in/b.pdf"),
        ]
        refs = list(classify_links(links, source))
        assert [r.url for r in refs] == ["https://x.gov.in/b.pdf", "https://x.gov.in/a.pdf"]

    def test_the_same_document_under_five_urls_is_fetched_once(self, source):
        """Government index pages repeat one document several times with the
        same anchor and different URLs. The URL-only check spent the whole
        request budget downloading one notice five times over."""
        links = [
            (f"Advance Intimation for Allotment of Examination City {suffix}",
             f"https://x.gov.in/images/advance-intimation-{n}.pdf")
            for n, suffix in enumerate(
                ["- reg.", " reg.", " - Reg.", " Reg.", " REG."], start=1
            )
        ]
        refs = list(classify_links(links, source))
        assert len(refs) == 1, [r.url for r in refs]

    def test_uninformative_anchors_are_not_deduplicated(self, source):
        """300 links called "Read More" are not 300 copies of one document.
        Deduplicating on the anchor alone would throw away 299 of them."""
        links = [
            ("Read More", f"https://x.gov.in/Notice_{n:08d}.pdf") for n in range(1, 6)
        ]
        refs = list(classify_links(links, source))
        assert len(refs) == 5

    def test_metadata_is_attached(self, source):
        refs = list(
            classify_links(
                [("Corrigendum for the 2026 advertisement", "https://x.gov.in/c_15-06-2027.pdf")],
                source,
                page_url="https://x.gov.in/notices",
            )
        )
        ref = refs[0]
        assert ref.tier == "corrigendum"
        assert ref.name_date == "2027-06-15"
        assert ref.from_page == "https://x.gov.in/notices"
        assert ref.body == "Test Commission"
        # A corrigendum is still a document. A fetch budget that skipped them
        # would skip exactly the notices that supersede the recorded ones.
        assert ref.is_document is True
