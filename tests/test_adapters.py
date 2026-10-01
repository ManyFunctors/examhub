"""Feed adapters against small, verbatim-shaped pages. No network."""

from __future__ import annotations

import json

import pytest

from examhub_pipeline import catalogue as C
from examhub_pipeline.crawl import adapters as A
from examhub_pipeline.crawl import harvest as H

FEED = {"id": "x-body/feed", "body": "x-body", "url": "https://x.gov.in/n", "adapter": "html_links"}

NTA_LIKE = """
<html><body>
<nav><ul class="menu"><li><a href="/about">About</a></li><li><a href="/Download/Notice/menu.pdf">Notice</a></li></ul></nav>
<div class="news">
  <li>Issuance of Certificates for Joint CSIR-UGC NET June 2026, Examination. 25/09/2026
      <a href="/Download/Notice/Notice_20260925215817.pdf">Read More</a></li>
  <li>Public Notice for UGC-NET June 2026 (1.2 MB) <a href="/Download/Notice/Notice_2.pdf">Click here</a></li>
</div>
<footer><a href="/Download/Notice/footer.pdf">Disclaimer</a></footer>
</body></html>
"""


def test_read_more_takes_its_title_from_the_row():
    rows = A.run(FEED, "https://nta.ac.in/", NTA_LIKE)
    titles = [r["title"] for r in rows]
    assert any(t.startswith("Issuance of Certificates for Joint CSIR-UGC NET") for t in titles)
    assert rows[0]["published"] == "2026-09-25"


def test_site_chrome_is_skipped():
    urls = [r["url"] for r in A.run(FEED, "https://nta.ac.in/", NTA_LIKE)]
    assert not any("menu.pdf" in u or "footer.pdf" in u for u in urls)


def test_size_and_click_here_noise_is_removed():
    rows = A.run(FEED, "https://nta.ac.in/", NTA_LIKE)
    assert any(r["title"] == "Public Notice for UGC-NET June 2026" for r in rows)


def test_urls_are_absolute_and_canonical():
    rows = A.run(FEED, "https://NTA.ac.in/x/", NTA_LIKE)
    assert all(r["url"].startswith("https://nta.ac.in/Download/Notice/") for r in rows)
    assert rows[0]["id"] == A.notice_id(rows[0]["url"])


KERALA_LIKE = """
<table><tr><th>Title</th><th>Category Number</th><th>Last date</th></tr>
<tr><td><a href="/index.php/extra-ordinary-gazette-date-31082026">EXTRA ORDINARY GAZETTE DATE 31/08/2026</a></td>
    <td><a href="/index.php/extra-ordinary-gazette-date-31082026">CAT.NO : 130/2026 TO CAT.NO : 150/2026</a></td>
    <td><time datetime="2026-10-07T12:00:00Z">07/10/2026</time></td></tr></table>
"""


def test_scoped_feed_keeps_rows_without_notice_words():
    feed = dict(FEED, item_selector="table tr")
    rows = A.run(feed, "https://keralapsc.gov.in/index.php/notifications", KERALA_LIKE)
    assert len(rows) == 1
    assert rows[0]["doc_type"] == "notification"


def test_html_table_uses_longest_cell_and_first_date():
    feed = dict(FEED, adapter="html_table")
    page = """<table><tr><td>1</td><td>12-09-2026</td><td>Advertisement for Junior Engineer posts 2026</td>
              <td><a href="a.pdf">View</a></td></tr></table>"""
    rows = A.run(feed, "https://x.gov.in/", page)
    assert rows[0]["title"] == "Advertisement for Junior Engineer posts 2026"
    assert rows[0]["published"] == "2026-09-12"


def test_json_api_with_url_template():
    feed = dict(FEED, adapter="json_api", items_path="data",
                fields={"title": "examName", "url": "navigationUrl", "code": "examCode"},
                url_template="https://ssc.gov.in{url}")
    body = json.dumps({"data": [{"examName": "Combined Graduate Level Examination, 2026",
                                 "navigationUrl": "/ApplicationForm/cglform", "examCode": "CGL"}]})
    rows = A.run(feed, feed["url"], body)
    assert rows[0]["url"] == "https://ssc.gov.in/ApplicationForm/cglform"
    assert rows[0]["raw"]["code"] == "CGL"


def test_rss():
    feed = dict(FEED, adapter="rss")
    body = """<rss><channel><item><title>Recruitment notification 2026</title>
              <link>https://x.gov.in/a.pdf</link><pubDate>Tue, 29 Sep 2026 10:00:00 +0530</pubDate></item></channel></rss>"""
    rows = A.run(feed, feed["url"], body)
    assert rows[0]["published"] == "2026-09-29"


@pytest.mark.parametrize("text,iso", [
    ("25/09/2026", "2026-09-25"), ("25.9.2026", "2026-09-25"), ("2026-09-25", "2026-09-25"),
    ("25th September, 2026", "2026-09-25"), ("Sept 25, 2026", "2026-09-25"),
    ("September 2026", None), ("31/02/2026", None),
])
def test_parse_date_never_invents_a_day(text, iso):
    assert A.parse_date(text) == iso


@pytest.mark.parametrize("title,kind", [
    ("Corrigendum to Advertisement No. 5/2026", "corrigendum"),
    ("Provisional Answer Key for CGL Tier I", "answer_key"),
    ("Download Admit Card for Constable GD", "admit_card"),
    ("Final Result of CSE 2025", "result"),
    ("Tentative Calendar of Examinations 2027", "calendar"),
    ("Notification for Junior Engineer 2026", "notification"),
])
def test_doc_type(title, kind):
    assert A.classify_doc_type(title) == kind


def test_body_class_tokens_are_not_chrome():
    # WordPress puts "home page-template ..." on <body>; that is not a menu.
    page = """<html><body class="home page-template-default has-header-image">
      <div class="entry"><p>Advertisement No. 3/2026 for Clerk posts <a href="/wp-content/a.pdf">Download</a></p></div>
    </body></html>"""
    assert len(A.run(FEED, "https://x.gov.in/", page)) == 1


def test_chrome_holding_most_documents_is_content():
    # A notice board built as a mega-menu: the "menu" is where the notices are.
    items = "".join(f'<li class="menu-item"><a href="/n{i}.pdf">Recruitment notice {i}</a></li>' for i in range(8))
    page = f"""<html><body><nav><a href="/about">About</a><a href="/rti.pdf">RTI manual</a></nav>
      <ul class="menu">{items}</ul></body></html>"""
    urls = [r["url"] for r in A.run(FEED, "https://x.gov.in/", page)]
    assert len(urls) == 8 and not any("rti" in u for u in urls)


def test_long_whitespace_runs_are_linear():
    import time
    t = time.time()
    A.clean(" " * 200_000 + "Notice 1.2 MB" + "\n" * 200_000)
    assert time.time() - t < 1


def test_looks_unrendered():
    assert A.looks_unrendered('<html><body><div id="root"></div><script>app()</script></body></html>')
    links = "".join(f'<a href="/{i}">notice {i}</a>' for i in range(12))
    assert not A.looks_unrendered(f"<html><body><p>{'word ' * 200}</p>{links}</body></html>")


def test_merge_is_stable_when_nothing_changes(tmp_path):
    cat = C.load()
    row = {"id": A.notice_id("https://ssc.gov.in/a.pdf"), "url": "https://ssc.gov.in/a.pdf",
           "title": "Combined Graduate Level Examination, 2026", "published": None,
           "body": "in-ssc", "feed": "in-ssc/notice-board", "doc_type": "notification"}
    H.merge_notices(cat, [dict(row)], {"in-ssc/notice-board"}, directory=tmp_path)
    first = (tmp_path / "notices.jsonl").read_bytes()
    H.merge_notices(cat, [dict(row)], {"in-ssc/notice-board"}, directory=tmp_path)
    assert (tmp_path / "notices.jsonl").read_bytes() == first
    got = json.loads(first)
    assert got["exam"] == "in-ssc-cgl" and got["cycle"] == "in-ssc-cgl/2026"


def test_notice_that_leaves_its_feed_is_marked_gone_not_deleted(tmp_path):
    cat = C.load()
    row = {"id": "a", "url": "https://ssc.gov.in/a.pdf", "title": "x", "body": "in-ssc",
           "feed": "in-ssc/notice-board", "doc_type": "other"}
    H.merge_notices(cat, [row], {"in-ssc/notice-board"}, directory=tmp_path)
    H.merge_notices(cat, [], {"in-ssc/notice-board"}, directory=tmp_path)
    got = H.read_jsonl(tmp_path / "notices.jsonl")
    assert len(got) == 1 and "gone_since" in got[0]
    # A feed that failed this run says nothing about its notices.
    H.merge_notices(cat, [], set(), directory=tmp_path)
    assert H.read_jsonl(tmp_path / "notices.jsonl")[0]["gone_since"] == got[0]["gone_since"]


def test_health_alerts_when_yield_drops_to_zero(tmp_path):
    base = {"id": "f", "body": "b", "url": "u", "ok": True, "status": 200}
    H.write_health([dict(base, count=12, checked="t1")], directory=tmp_path)
    alerts = H.write_health([dict(base, count=0, checked="t2")], directory=tmp_path)
    assert [a["id"] for a in alerts] == ["f"]


def _row(url, title, feed="in-ssc/notice-board", body="in-ssc", published=None):
    return {"id": A.notice_id(url), "url": url, "title": title, "body": body, "feed": feed,
            "doc_type": A.classify_doc_type(title, url), "published": published}


def test_change_log_and_atom(tmp_path):
    cat = C.load()
    a = _row("https://ssc.gov.in/a.pdf", "Combined Graduate Level Examination, 2026")
    H.merge_notices(cat, [a], {"in-ssc/notice-board"}, directory=tmp_path)
    atom = (tmp_path / "feed.atom").read_text()
    assert "in-ssc-cgl" in atom and "urn:sha256:" in atom
    # Nothing new: the Atom file and the change log are untouched.
    logs = sorted((tmp_path / "changes").glob("*.jsonl"))
    before = logs[0].read_text()
    H.merge_notices(cat, [a], {"in-ssc/notice-board"}, directory=tmp_path)
    assert (tmp_path / "feed.atom").read_text() == atom
    assert logs[0].read_text() == before
    # Gone is logged once, then nothing.
    H.merge_notices(cat, [], {"in-ssc/notice-board"}, directory=tmp_path)
    H.merge_notices(cat, [], {"in-ssc/notice-board"}, directory=tmp_path)
    changes = [json.loads(l)["change"] for l in logs[0].read_text().splitlines()]
    assert changes == ["new", "gone"]


def test_not_modified_keeps_the_previous_health_line(tmp_path):
    base = {"id": "f", "body": "b", "url": "u"}
    H.write_health([dict(base, ok=True, status=200, count=7, etag='"x"', checked="t1")], directory=tmp_path)
    first = (tmp_path / "feed-health.jsonl").read_text()
    H.write_health([dict(base, ok=True, not_modified=True, etag='"x"', checked="t2")], directory=tmp_path)
    assert (tmp_path / "feed-health.jsonl").read_text() == first


def test_tiers_ignore_the_first_crawl_backlog(tmp_path):
    from datetime import datetime
    cat = C.load()
    F = "kl-kpsc/exam-updates"
    assert "tier" not in cat.feeds[F]
    today = datetime.fromisoformat("2026-09-29T10:00:00+05:30")
    rows = [dict(_row(f"https://keralapsc.gov.in/{i}.pdf", f"notice {i}", feed=F, body="kl-kpsc"), first_seen="2026-09-28T02:00:00+05:30")
            for i in range(3)]
    H.write_jsonl(tmp_path / "notices.jsonl", rows)
    assert H.feed_tiers(cat, tmp_path, today)[F] == "cold"
    rows.append(dict(_row("https://keralapsc.gov.in/new.pdf", "new", feed=F, body="kl-kpsc"), first_seen="2026-09-29T09:00:00+05:30"))
    H.write_jsonl(tmp_path / "notices.jsonl", rows)
    assert H.feed_tiers(cat, tmp_path, today)[F] == "hot"
    rows = [dict(_row("https://keralapsc.gov.in/p.pdf", "p", feed=F, body="kl-kpsc", published="2026-07-01"), first_seen="2026-09-28T02:00:00+05:30")]
    H.write_jsonl(tmp_path / "notices.jsonl", rows)
    assert H.feed_tiers(cat, tmp_path, today)[F] == "warm"


def test_pinned_tier_wins(tmp_path):
    assert H.feed_tiers(C.load(), tmp_path)["in-upsc/active-exams"] == "hot"


def test_aggregator_matching_needs_the_body_named():
    m = C.Matcher(C.load())
    assert m.match_any_body("UPSC declares final result of Civil Services Examination, 2025") == ["in-upsc-cse"]
    assert m.match_any_body("Recruitment of Assistants in the Ministry") == []


def test_signed_urls_have_one_identity():
    a = ("https://rrpdocuments.aiimsexams.ac.in/1790-31.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256"
         "&X-Amz-Date=20260928T214836Z&X-Amz-Expires=604800&X-Amz-Signature=d19a&X-Amz-SignedHeaders=host"
         "&response-content-type=application%2Fpdf")
    b = a.replace("214836Z", "215637Z").replace("d19a", "fc0c")
    assert A.canonical_url(a) == A.canonical_url(b) == "https://rrpdocuments.aiimsexams.ac.in/1790-31.pdf"
    # An unsigned query is identity, even with the same short parameter names.
    assert A.canonical_url("https://x.gov.in/view.aspx?sp=2&id=9") == "https://x.gov.in/view.aspx?sp=2&id=9"


def test_stored_notices_are_recanonicalised(tmp_path):
    cat = C.load()
    u1 = "https://ssc.gov.in/a.pdf?X-Amz-Signature=1&X-Amz-Date=1"
    u2 = "https://ssc.gov.in/a.pdf?X-Amz-Signature=2&X-Amz-Date=2"
    old = [dict(_row(u, "Combined Graduate Level Examination, 2026"), id=f"legacy{i}", url=u, first_seen=fs)
           for i, (u, fs) in enumerate([(u1, "2026-09-01T00:00:00+05:30"), (u2, "2026-09-02T00:00:00+05:30")])]
    H.write_jsonl(tmp_path / "notices.jsonl", old)
    H.merge_notices(cat, [_row(u2, "Combined Graduate Level Examination, 2026")], {"in-ssc/notice-board"}, directory=tmp_path)
    got = H.read_jsonl(tmp_path / "notices.jsonl")
    assert len(got) == 1 and got[0]["first_seen"] == "2026-09-01T00:00:00+05:30" and "gone_since" not in got[0]


def test_a_timeout_is_not_an_alert_until_it_lasts_a_day(tmp_path):
    base = {"id": "f", "body": "b", "url": "u"}
    H.write_health([dict(base, ok=True, status=200, count=5, checked="2026-09-28T00:00:00+05:30")], directory=tmp_path)
    fail = dict(base, ok=False, count=0, error="DownloadTimeoutError")
    assert H.write_health([dict(fail, checked="2026-09-28T01:00:00+05:30")], directory=tmp_path) == []
    assert H.write_health([dict(fail, checked="2026-09-28T12:00:00+05:30")], directory=tmp_path) == []
    alerts = H.write_health([dict(fail, checked="2026-09-29T02:00:00+05:30")], directory=tmp_path)
    assert [a["alert"] for a in alerts] == ["failing for a day"]
    # Raised once, not on every later run.
    assert H.write_health([dict(fail, checked="2026-09-29T03:00:00+05:30")], directory=tmp_path) == []


def test_url_title_identity_makes_each_dated_update_a_notice():
    feed = dict(FEED, keep_chrome=True, identity="url_title", include=r"^\([^)]*\d{2}/\d{4}\)")
    page = lambda d: f'<ul><li><a href="/getdata?cenum=03/2026&category=Result">(03/2026) Exam Results ({d})</a></li></ul>'
    a, b = A.run(feed, "https://x.gov.in/", page("16-09-2026")), A.run(feed, "https://x.gov.in/", page("29-09-2026"))
    assert a[0]["url"] == b[0]["url"] and a[0]["id"] != b[0]["id"]
    assert A.run(FEED, "https://x.gov.in/", page("16-09-2026"))[0]["id"] == A.notice_id(a[0]["url"])


def test_notify_pushes_matched_and_notify_all_feeds(tmp_path, capsys, monkeypatch):
    from examhub_pipeline.crawl import notify
    for k in ("NTFY_TOPIC", "TELEGRAM_BOT_TOKEN", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(k, raising=False)
    rows = [dict(_row("https://ssc.gov.in/a.pdf", "CGL 2026 notice"), exam="in-ssc-cgl"),
            _row("https://ssc.gov.in/b.pdf", "Tender for chairs"),
            _row("https://rrb.indianrailways.gov.in/getdata?x=1", "(03/2026) Exam Results (16-09-2026)",
                 feed="in-rrb/updates", body="in-rrb")]
    H.write_jsonl(tmp_path / "new.jsonl", rows)
    notify.main(["--input", str(tmp_path / "new.jsonl"), "--dry-run"])
    out = capsys.readouterr().out
    assert "CGL" in out and "(03/2026)" in out and "chairs" not in out


# --- the issue date a notice states itself ---------------------------------

@pytest.mark.parametrize("title, url, want", [
    ("05-02-2025 - Regarding postponing the written examination", "https://x.in/a.pdf", ("2025-02-05", "title")),
    ("Result dated 15.03.2023 of speed test for Stenographer", "https://x.in/a.pdf", ("2023-03-15", "title")),
    ("Important Notice", "https://mpsc.meghalaya.gov.in/notify/Notice25Sep2024a.pdf", ("2024-09-25", "url")),
    # an event, not an issue date
    ("Declaration of holiday on 5th July, 2025", "https://x.in/a.pdf", None),
    ("Final key", "https://x.in/FAK-91-2015-16-Exam-Date-21-08-2016.pdf", None),
    # a date after today is an event
    ("01-01-2027 - Exam", "https://x.in/a.pdf", None),
])
def test_a_notice_names_its_own_issue_date(title, url, want):
    assert A.stamped_date(title, url, "2026-10-01") == want


@pytest.mark.parametrize("title, want", [
    ("Ineligibility List (Interview) - 13/2021-22", "application_status"),
    ("List of Eligible Candidates for Applicn. Scrutiny - 110/2016-17", "application_status"),
    ("Conduct of Third/Mop-Up Round Physical Counselling for admission", "counselling"),
    ("TENTATIVE SEAT MATRIX OF NEET UG MEDICAL COURSES-2024", "counselling"),
    ("Walk-in-Interview for the post of Guest Faculty", "walk_in"),
    ("Notice Regarding PMT and PET Test of Driver and Fireman", "schedule"),
    ("Syllabus for the post of Assistant Protocol Officer", "syllabus"),
    # the advertisement itself, whatever else it names
    ("Advertisement for Interview of Guest faculty in Department of Sanskrit", "notification"),
    ("DETAILED ADVERTISEMENT AND SCHEME & SYLLABUS FOR CLERKSHIP EXAMINATION, 2023", "notification"),
])
def test_the_new_document_types(title, want):
    assert A.classify_doc_type(title) == want
