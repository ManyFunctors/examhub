"""A short notice sets its schedule as label-above-date lines, which OCR garbles a little."""
import datetime as dt

from examhub_pipeline import documents

REF = dt.date(2026, 10, 8)
NOTICE = '''Online Submission of Application Form through Website
(https://csirnet.nta.nic.in/)
07™ October 2026 to 05" November 2026
(upto 11:50 P.M.)
Last date of successful transaction of fee through
Credit/Debit Card/Net Banking/UPI
05" November 2026 (upto 11:50 P.M.)
Correction in Particulars of Application Form on the
website only
10" November 2026 to 12" November 2026
Announcement of the City of Examination
To be announced later
Date of Examination
19, 22" and 27 December 2026
Duration of Examination
180 minutes
'''


def by_key(events):
    return {e["key"]: e for e in events}


def test_label_above_date_lines_become_events():
    ev = by_key(documents.parse_schedule_lines([(1, NOTICE)], REF))
    assert (ev["registration_open"]["date"], ev["registration_open"]["until"]) == ("2026-10-07", "2026-11-05")
    assert ev["payment_deadline"]["date"] == "2026-11-05"
    assert ev["correction_window"]["date"] == "2026-11-10"
    assert (ev["exam_date"]["date"], ev["exam_date"]["until"]) == ("2026-12-19", "2026-12-27")


def test_a_long_document_is_not_read_this_way():
    assert documents.parse_schedule_lines([(n, NOTICE) for n in range(1, 8)], REF) == []


def test_pipe_rows_and_unpunctuated_ordinals():
    text = ('Online Submission of Application Form through Website | 07TM October 2026 to 05" November 2026\n'
            'Date of Examination\n19" 22" and 27" December 2026\n')
    ev = by_key(documents.parse_schedule_lines([(1, text)], REF))
    assert (ev["registration_open"]["date"], ev["registration_open"]["until"]) == ("2026-10-07", "2026-11-05")
    assert (ev["exam_date"]["date"], ev["exam_date"]["until"]) == ("2026-12-19", "2026-12-27")
