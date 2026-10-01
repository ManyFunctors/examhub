"""Tests for the field diff and the review bundle.

The review output is the only thing a human looks at, so its shape is a
contract: a status change shows as a status change, a value the verifier
disbelieved is left alone, and a run that learned nothing produces no diff.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from examhub_pipeline import record as rec_ops
from examhub_pipeline.config import Settings
from examhub_pipeline.review import (
    ReviewBundle,
    build_bundle,
    diff_records,
    load_baseline,
)
from examhub_pipeline.validate import ValidationResult

PATH = "content/exams/ssc-cgl-2027.md"
EXAM = "dates.stages[1].exam"
CHECKED = dt.datetime(2026, 8, 1, 10, 0, tzinfo=rec_ops.IST)


def record(exam: str | None = None, provisional: bool = False, vacancies: int | None = None) -> dict:
    r = rec_ops.skeleton(title="SSC CGL 2027", slug="ssc-cgl-2027", body="in-ssc")
    if exam:
        rec_ops.set_value(r, "exam_date", exam, provisional=provisional)
    if vacancies is not None:
        rec_ops.set_value(r, "vacancies", str(vacancies))
    rec_ops.touch(r, CHECKED)
    return r


def verified(field, value, confidence=0.72, publishes=0.81) -> ValidationResult:
    return ValidationResult(
        field=field, verdict="verified", value=value,
        choice_confidence=confidence, publish_probability=publishes,
        reason="the model picked our value",
    )


class TestDiff:
    def test_no_change(self):
        a = record("2027-06-15")
        assert all(not c.is_material for c in diff_records(a, rec_ops.copy_of(a)))

    def test_a_changed_date_is_reported(self):
        changes = {c.field: c for c in diff_records(record("2027-06-15"), record("2027-06-22"))}
        assert changes[EXAM].kind == "changed"
        assert changes[EXAM].before == "2027-06-15 (confirmed)"
        assert changes[EXAM].after == "2027-06-22 (confirmed)"
        assert changes[EXAM].is_material

    def test_a_status_change_is_its_own_kind(self):
        """Confirmed -> tentative suppresses a countdown on the site."""
        changes = {c.field: c for c in diff_records(record("2027-06-15"),
                                                     record("2027-06-15", provisional=True))}
        assert changes[EXAM].kind == "status-change"
        assert changes[EXAM].after == "2027-06-15 (tentative)"

    def test_an_added_date(self):
        changes = {c.field: c for c in diff_records(record(), record("2027-06-15"))}
        assert changes[EXAM].before == "not_announced"
        assert changes[EXAM].kind == "changed"

    def test_verdicts_attach_to_the_unchanged_field_too(self):
        a = record("2027-06-15")
        changes = {c.field: c for c in diff_records(a, rec_ops.copy_of(a),
                                                     {EXAM: verified("exam_date", "2027-06-15")})}
        assert changes[EXAM].kind == "unchanged"
        assert changes[EXAM].verdict == "verified"
        assert changes[EXAM].confidence == 0.72

    def test_a_window_end_verdict_covers_the_window(self):
        a = record()
        b = rec_ops.copy_of(a)
        rec_ops.set_value(b, "registration_deadline", "2027-07-01")
        changes = {c.field: c for c in diff_records(
            a, b, {"dates.application.to": verified("registration_deadline", "2027-07-01")})}
        assert changes["dates.application"].verdict == "verified"


class TestBundle:
    @pytest.fixture
    def bundle(self, settings: Settings):
        return build_bundle(
            settings,
            [(PATH, record("2027-06-15"), record("2027-06-22"),
              {EXAM: verified("exam_date", "2027-06-22")}, {})],
            meta={"model_available": True, "ocr_documents": 0},
            stamp="20260927T120000Z",
        )

    def test_it_writes_a_usable_bundle(self, bundle: ReviewBundle, settings: Settings):
        root = bundle.write(settings)
        for name in ("summary.txt", "report.json", "review.patch", "propose.patch",
                     "before/ssc-cgl-2027.md", "after/ssc-cgl-2027.md"):
            assert (root / name).exists(), name

    def test_the_patch_is_applicable(self, bundle: ReviewBundle, settings: Settings):
        patch = (bundle.write(settings) / "review.patch").read_text()
        assert patch.startswith(f"--- a/{PATH}")
        assert f"+++ b/{PATH}" in patch
        assert "-    from         = 2027-06-15" in patch
        assert "+    from         = 2027-06-22" in patch

    def test_the_report_is_machine_readable(self, bundle: ReviewBundle, settings: Settings):
        report = json.loads((bundle.write(settings) / "report.json").read_text())
        assert report["meta"]["model_available"] is True
        assert report["records"][0]["path"] == PATH
        assert report["records"][0]["no_op"] is False
        assert report["counts"]["verified"] >= 1

    def test_the_summary_fits_one_screen(self, bundle: ReviewBundle):
        summary = bundle.render_summary()
        assert PATH in summary and EXAM in summary
        assert len(summary.splitlines()) < 40
        assert "Nothing has been written to the site" in summary

    def test_a_verified_change_is_flagged_green(self, bundle: ReviewBundle):
        line = [ln for ln in bundle.render_summary().splitlines() if EXAM in ln][0]
        assert line.strip().startswith(f"✓ ~ {EXAM}: 2027-06-15 (confirmed) -> 2027-06-22 (confirmed)")
        assert "model 0.72" in line and "publishes p=0.81" in line

    def test_a_missing_model_is_announced_loudly(self, settings: Settings):
        bundle = build_bundle(
            settings,
            [(PATH, record(), record(vacancies=100),
              {"posts.vacancies_total": ValidationResult(field="vacancies", verdict="not_validated", value="100")},
              {})],
            meta={"model_available": False}, stamp="s",
        )
        summary = bundle.render_summary()
        assert "Laya was NOT available" in summary
        assert "unverified" in summary

    def test_ocr_is_announced_loudly(self, settings: Settings):
        bundle = build_bundle(
            settings,
            [(PATH, record(), record(vacancies=100),
              {"posts.vacancies_total": ValidationResult(field="vacancies", verdict="verified",
                                                         value="100", is_ocr=True)},
              {"ocr": True})],
            meta={"model_available": True, "ocr_documents": 1}, stamp="s",
        )
        summary = bundle.render_summary()
        assert "OCR" in summary and "can be wrong" in summary

    def test_last_checked_alone_is_not_a_material_change(self, settings: Settings):
        """A run that only moved last_checked has learned nothing, and a nightly
        pull request for it is how an automated job gets muted."""
        a = record("2027-06-15")
        b = rec_ops.copy_of(a)
        rec_ops.touch(b, CHECKED + dt.timedelta(days=30))
        bundle = build_bundle(settings, [(PATH, a, b, {}, {})], stamp="s")
        assert bundle.material == []
        assert bundle.unified_patch() == ""
        assert "No material changes" in bundle.render_summary()

    def test_a_new_document_row_alone_is_not_material(self, settings: Settings):
        a = record()
        b = rec_ops.copy_of(a)
        rec_ops.add_evidence(b, field="dates.application", url="https://ssc.gov.in/n.pdf", words="x")
        assert build_bundle(settings, [(PATH, a, b, {}, {})], stamp="s").material == []

    def test_lint_errors_surface_in_the_summary(self, settings: Settings):
        a = record()
        b = rec_ops.copy_of(a)
        b["purpose"] = "Recruitment"
        bundle = build_bundle(settings, [(PATH, a, b, {}, {})], stamp="s")
        assert "LINT" in bundle.render_summary()

    def test_a_disputed_value_is_not_written(self, settings: Settings):
        """The whole point: a value the model disbelieved stays as it was."""
        a = record("2027-06-15")
        bundle = build_bundle(
            settings,
            [(PATH, a, rec_ops.copy_of(a),
              {EXAM: ValidationResult(field="exam_date", verdict="disputed", value="2027-06-22",
                                      model_choice="none_of_these", reason="the document says otherwise")},
              {})],
            meta={"model_available": True}, stamp="s",
        )
        assert bundle.material == []
        assert bundle.counts()["disputed"] == 1

    def test_unverified_is_counted_separately(self, settings: Settings):
        bundle = build_bundle(
            settings,
            [(PATH, record(), record(vacancies=100),
              {"posts.vacancies_total": ValidationResult(field="vacancies", verdict="not_validated", value="100")},
              {})],
            meta={"model_available": False}, stamp="s",
        )
        # the status set with the count shares its verdict
        assert bundle.counts()["not_validated"] == 2
        assert {c.field for c in bundle.unverified} == {"posts.vacancies_total", "posts.vacancies_status"}


class TestBaseline:
    def test_a_missing_baseline_is_not_an_error(self, settings: Settings):
        assert load_baseline(settings, "content/exams/nope.md") is None

    def test_a_broken_baseline_is_not_fatal(self, settings: Settings):
        """One malformed file must not end a run."""
        target = settings.content_rel("content/exams/broken.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("no front matter here", encoding="utf-8")
        assert load_baseline(settings, "content/exams/broken.md") is None

    def test_a_path_escaping_the_repo_is_refused(self, settings: Settings):
        assert load_baseline(settings, "../../../etc/passwd") is None

    def test_a_good_baseline_loads(self, settings: Settings):
        target = settings.content_rel("content/exams/good.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rec_ops.dumps(record("2027-06-15"), "Body text.\n"), encoding="utf-8")
        loaded, body = load_baseline(settings, "content/exams/good.md")
        assert loaded["title"] == "SSC CGL 2027"
        assert body.strip() == "Body text."
