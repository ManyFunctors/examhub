"""Links placed by what they are (the link check), not by what their addresses look like."""

from examhub_pipeline import links
from examhub_pipeline.catalogue import Catalogue
from examhub_pipeline.crawl.linkcheck import classify

CAT = Catalogue(vocab={}, jurisdictions={}, feeds={}, exams={},
                bodies={"in-upsc": {"id": "in-upsc", "website": "https://www.upsc.gov.in/"},
                        "kl-kpsc": {"id": "kl-kpsc", "website": "https://keralapsc.gov.in/"}})


def page(title="", text="", home=False, applies=()):
    return {"state": "ok", "kind": "page", "title": title, "text": text, "home": home, "apply_links": list(applies)}


def test_without_a_check_a_pdf_is_still_a_file():
    pdf = "https://www.upsc.gov.in/sites/default/files/Notif-ESEP-2027-Engl-160926.pdf"
    rec = {"bodies": [{"body": "in-upsc", "body_role": "conducts"}],
           "links": {"link_official_page": pdf, "link_apply": "https://upsconline.nic.in/", "documents": []}}
    links.fix(rec, CAT)
    assert rec["links"]["link_official_page"] == "https://www.upsc.gov.in/"
    assert [d["document_url"] for d in rec["links"]["documents"]] == [pdf]


def test_the_page_that_names_the_exam_is_the_official_page():
    pdf = "https://keralapsc.gov.in/sites/default/files/2026-08/noti-144-26.pdf"
    gazette = "https://keralapsc.gov.in/index.php/extra-ordinary-gazette-date-31082026"
    home = "https://keralapsc.gov.in/"
    thulasi = "https://thulasi.psc.kerala.gov.in/thulasi/"
    checks = {pdf: {"state": "ok", "kind": "file"},
              gazette: page("Gazette", "Electrician in Kerala State Ground Water Department, Category No 144/2026"),
              home: page("Kerala Public Service Commission", "Welcome", home=True, applies=[thulasi]),
              thulasi: {"state": "ok", "kind": "portal", "title": "Thulasi"}}
    rec = {"title": "Kerala PSC Electrician 2026", "title_official": "Electrician, Kerala State Ground Water Department, 2026",
           "bodies": [{"body": "kl-kpsc", "body_role": "conducts"}],
           "links": {"link_official_page": pdf, "link_apply": home, "documents": [{"document_url": gazette}]}}
    links.fix(rec, CAT, checks)
    assert rec["links"]["link_official_page"] == gazette
    assert rec["links"]["link_apply"] == thulasi
    assert {d["document_url"] for d in rec["links"]["documents"]} == {pdf, home}


def test_a_portal_is_the_apply_link_never_the_official_page():
    portal = "https://hpbose.org/OnlineServices/CET/TET/Instructions.aspx"
    home = "https://hpbose.org/"
    checks = {portal: {"state": "ok", "kind": "portal", "title": "HP TET Login"},
              home: page("HP Board of School Education", "HP TET November 2026 notification", home=True)}
    rec = {"title": "HP TET November 2026", "links": {"link_official_page": portal, "link_apply": home, "documents": []}}
    links.fix(rec, CAT, checks)
    assert rec["links"]["link_apply"] == portal
    assert rec["links"]["link_official_page"] == home


def test_a_page_with_no_way_to_apply_is_no_apply_link():
    home = "https://upessc.up.gov.in/"
    rec = {"links": {"link_official_page": home, "link_apply": home, "documents": []}}
    links.fix(rec, CAT, {home: page("UPESSC", "Welcome", home=True)})
    assert rec["links"]["link_apply"] == "unknown"


def test_an_exams_own_site_that_offers_to_apply_stays():
    site = "https://ugcnet.nta.nic.in/"
    rec = {"title": "UGC NET December 2026", "links": {"link_official_page": site, "link_apply": site, "documents": []}}
    links.fix(rec, CAT, {site: page("UGC NET", "UGC NET December 2026", home=True,
                                    applies=["https://ugcnet.nta.nic.in/login"])})
    assert rec["links"]["link_apply"] == site


def test_the_exams_own_page_beats_the_site_front_page():
    own = "https://www.ibps.in/index.php/specialist-officers-xvi/"
    home = "https://www.ibps.in/"
    checks = {own: page("CRP SPL-XVI", "Common Recruitment Process for Specialist Officers XVI"),
              home: page("IBPS", "Specialist Officers XVI results", home=True)}
    rec = {"title": "IBPS SO XVI", "title_aliases": ["Specialist Officers XVI"],
           "links": {"link_official_page": home, "link_apply": "unknown", "documents": [{"document_url": own}]}}
    links.fix(rec, CAT, checks)
    assert rec["links"]["link_official_page"] == own


def test_the_check_tells_a_file_a_portal_and_a_page_apart():
    assert classify("u", "https://a.in/x", 200, "application/pdf", b"%PDF-1.7")["kind"] == "file"
    login = b"<html><title>Login</title><body><form><input name=user><input type=password></form></body></html>"
    assert classify("u", "https://a.in/login", 200, "text/html", login)["kind"] == "portal"
    home = (b"<html><title>Board</title><body>" + b"news " * 60
            + b"<a href='/reg/new'>New Registration</a></body></html>")
    info = classify("u", "https://a.in/", 200, "text/html", home)
    assert info["kind"] == "page" and info["home"] and info["apply_links"] == ["https://a.in/reg/new"]
    assert classify("u", "https://a.in/x", 404, "text/html", b"<html></html>")["state"] == "not_found"


def test_a_form_with_login_fields_is_a_portal_and_script_links_are_skipped():
    form = (b"<html><body><form><input name=registration_no><input name=dob></form>"
            b"<a href='javascript:Void(0);'>Apply Online</a></body></html>")
    info = classify("u", "https://a.in/reg", 200, "text/html", form)
    assert info["kind"] == "portal" and info["apply_links"] == []


def test_a_site_that_did_not_answer_keeps_its_links():
    slow = "https://www.ssbjk.org.in/"
    rec = {"links": {"link_official_page": slow, "link_apply": slow, "documents": []}}
    assert links.fix(rec, CAT, {slow: {"state": "error", "error": "DownloadTimeoutError"}}) == []


def test_a_host_that_does_not_exist_gives_way_to_the_bodys_site():
    dead = "https://www.www.upsc.gov.in/"
    rec = {"bodies": [{"body": "in-upsc", "body_role": "conducts"}],
           "links": {"link_official_page": dead, "link_apply": dead, "documents": []}}
    links.fix(rec, CAT, {dead: {"state": "not_found", "error": "CannotResolveHostError"}})
    assert rec["links"]["link_official_page"] == "https://www.upsc.gov.in/"
    assert rec["links"]["link_apply"] == "unknown"
