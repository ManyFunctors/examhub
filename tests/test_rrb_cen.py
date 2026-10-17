"""RRB CEN pages: one row per file and language, matched to the exam by CEN number."""
from examhub_pipeline import catalogue as C
from examhub_pipeline.crawl.adapters import rrb_cen_table

PAGE = """<table class="cnp_list cnp_list_new"><tbody>
<tr class="publicR"><td><Strong>1</Strong></td><td>07/2025</td><td>Exam Schedule</td><td>Exam city intimation</td><td> 14-09-2026 </td>
<td><select><option value="">Select Language</option>
<option value="/-/image/111CEN_07_2025_Hindi.pdf/examsDocuments">Hindi</option>
<option value="/-/image/112CEN_07_2025_English.pdf/examsDocuments">English</option></select></td></tr></tbody></table>"""
FEED = {"id": "in-rrb/cen-documents", "body": "in-rrb"}


def test_one_row_per_language_with_cen_in_the_title():
    rows = list(rrb_cen_table(FEED, "https://rrb.indianrailways.gov.in/getdata?cennum=07/2025", PAGE))
    assert [r["url"].rsplit("/", 2)[-2] for r in rows] == ["111CEN_07_2025_Hindi.pdf", "112CEN_07_2025_English.pdf"]
    assert rows[0]["title"].startswith("(07/2025) Exam Schedule:") and rows[0]["published"] == "2026-09-14"


def test_cen_number_picks_the_exam():
    m = C.Matcher(C.load())
    title = "(07/2025) Exam Schedule: Exam city intimation (14-09-2026) [English]"
    assert m.match("in-rrb", title) == ["in-rrb-ntpc-ug"]
    assert m.match("in-rrb", "(09/2025) Notification: Detailed CEN", "https://x/CEN_09_2025.pdf") == ["in-rrb-group-d"]
