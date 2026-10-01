"""Which body a legacy record belongs to, from its names and links."""

from examhub_pipeline import records


def test_a_body_on_one_folder_of_a_shared_host_owns_only_that_folder(monkeypatch):
    monkeypatch.setattr(records, "_body_index", lambda: {
        "host:exams.nta.nic.in/jipmat": {"in-iim-jipmat"},
        "host:nta.ac.in": {"in-nta"},
    })
    rec = lambda url: {"bodies": [], "provenance": {"source_url": url}}
    assert records.body_ids(rec("https://exams.nta.nic.in/jipmat/notice.pdf")) == {"in-iim-jipmat"}
    assert records.body_ids(rec("https://exams.nta.nic.in/cuet-pg/")) == set()
    assert records.body_ids(rec("https://nta.ac.in/Downloads")) == {"in-nta"}
