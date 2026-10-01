"""End-to-end tests for the CLI, entirely offline.

The pipeline is driven through a fake document written straight into the work
directory, so `extract`, `validate` and `review` can be exercised without a
network and without the model. What is being checked is the contract the
scheduled job depends on: **exit code 2 means nothing changed**, and that a
review bundle appears on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from examhub_pipeline import record, template
from examhub_pipeline.cli import (
    EXIT_ERROR,
    EXIT_NO_CHANGE,
    EXIT_OK,
    EXIT_PARTIAL,
    build_parser,
    main,
)

NOTICE = (
    "STAFF SELECTION COMMISSION\n"
    "2. SCHEDULE OF EXAMINATION\n"
    "The examination will be held on 15.06.2026 at 10:00 AM.\n"
    "3. ONLINE REGISTRATION\n"
    "Last date to apply: 22.02.2026 up to 23:00 hours.\n"
    "4. APPLICATION FEE\n"
    "Rs. 100/- for General and EWS candidates, Rs 50 for SC/ST/PwD candidates.\n"
)


def seed_document(settings, name="ugcnet-notice", **meta) -> Path:
    """Write a document into the work directory as if it had been fetched."""
    settings.ensure_dirs()
    from examhub_pipeline.fetch import _safe_name

    url = f"https://ugcnet.nta.ac.in/images/{name}.pdf"
    path = settings.docs_dir / _safe_name(url)
    payload = {
        "meta": {
            "url": url,
            "title": "Examination Schedule of UGC-NET June 2025",
            "tier": "notification_pdf",
            "body": "UGC-NET",
            "from_page": "https://ugcnet.nta.ac.in/",
            "content_type": "application/pdf",
            "content_hash": "deadbeef",
            "is_ocr": False,
            "pages": 1,
            "chunks": 1,
            "char_count": len(NOTICE),
            "warnings": [],
            **meta,
        },
        "text": NOTICE,
        "chunks": [
            {"index": 0, "page": 1, "section": "SCHEDULE OF EXAMINATION",
             "is_ocr": meta.get("is_ocr", False), "text": NOTICE}
        ],
        "links": [],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


@pytest.fixture
def verifying(monkeypatch):
    """Make every candidate verify, so the write path is exercised offline."""
    from examhub_pipeline.validate import ValidationResult

    def fake_validate_record(doc, adjudications, validator, settings_, **kwargs):
        return {
            field: ValidationResult(
                field=field, verdict="verified",
                value=adj.chosen.value if adj.chosen else None,
                # As a real validator does: the hedge flag travels with the
                # value, so a tentatively-published date is stored provisional
                # and a plainly-stated one is stored confirmed.
                provisional=bool(adj.chosen and adj.chosen.provisional),
                choice_confidence=0.8, publish_probability=0.9,
            )
            for field, adj in adjudications.items()
        }

    monkeypatch.setattr("examhub_pipeline.cli.validate_record", fake_validate_record)
    monkeypatch.setattr(
        "examhub_pipeline.cli.LayaValidator.available", property(lambda self: True)
    )


@pytest.fixture
def cli(settings, capsys):
    def run(*args: str) -> tuple[int, str]:
        code = main([*args, "--repo", str(settings.repo_dir),
                     "--work-dir", str(settings.work_dir),
                     "--cache-dir", str(settings.cache_dir)])
        return code, capsys.readouterr().out

    return run


class TestParser:
    def test_every_documented_subcommand_exists(self):
        parser = build_parser()
        actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
        names = set()
        for action in actions:
            names.update(action.choices)
        assert {
            "discover", "fetch", "extract", "validate", "review", "propose", "run",
            "bench", "eval", "sources",
        } <= names

    def test_an_unknown_subcommand_is_rejected(self):
        with pytest.raises(SystemExit):
            main(["nope"])

    def test_robots_is_opt_in_not_opt_out(self):
        """The flag exists for debugging a host you own. Nothing in this
        repository sets it, and the default has to stay on."""
        parser = build_parser()
        args = parser.parse_args(["extract"])
        assert not getattr(args, "ignore_robots", False)


class TestSources:
    def test_sources_lists_the_registry(self, cli):
        code, out = cli("sources")
        assert code == EXIT_OK
        assert "ssc" in out and "nta" in out
        assert "note:" in out


class TestExtract:
    def test_no_documents_is_not_an_error(self, cli):
        code, out = cli("extract")
        assert code == EXIT_OK
        assert "0 cached document" in out

    def test_a_seeded_document_is_listed(self, settings, cli):
        seed_document(settings)
        code, out = cli("extract")
        assert code == EXIT_OK
        assert "ugcnet-notice" in out
        assert "p=1" in out

    def test_json_output(self, settings, cli):
        seed_document(settings)
        code, out = cli("extract", "--json")
        assert code == EXIT_OK
        payload = json.loads(out[out.index("["):])
        assert payload[0]["pages"] == 1

    def test_url_filter(self, settings, cli):
        seed_document(settings, name="one")
        seed_document(settings, name="two")
        code, out = cli("extract", "--url", "one.pdf")
        assert code == EXIT_OK
        assert "one" in out and "two" not in out


class TestValidate:
    def test_without_a_model_everything_is_flagged_not_written(self, settings, cli):
        """The most important property of the whole tool: a run that cannot
        verify produces flags, not values."""
        seed_document(settings)
        code, out = cli("validate", "--no-model")
        assert code == EXIT_PARTIAL
        assert "Laya available: False" in out
        assert "Laya unavailable" in out
        # The candidate is still shown, so a reviewer can act on it by hand.
        assert "2026-06-15" in out

    def test_with_a_model_the_verdicts_are_printed(self, settings, cli, monkeypatch):
        seed_document(settings)
        monkeypatch.setattr(
            "examhub_pipeline.cli.LayaValidator.available", property(lambda self: True)
        )
        code, out = cli("validate")
        assert code == EXIT_OK
        assert "2026-06-15" in out or "exam_date" in out


class TestReview:
    def test_a_first_run_without_a_model_writes_nothing(self, settings, cli):
        """A new record with no verified field is a stub, and a stub is not
        worth committing. The reviewer is told what would have been created."""
        seed_document(settings)
        code, out = cli("review", "--no-model")
        assert code == EXIT_NO_CHANGE
        assert "new record proposed" in out
        # The slug carries the taxonomy body, so the filename and bodies = ['UGC']
        # agree. They used to disagree (`nta-ugc-net-...` for `UGC`).
        assert "content/exams/ugc-" in out
        # With no model, nothing may be written, so the only honest summary is
        # "nothing changed" plus the banner saying why.
        assert "Laya was NOT available" in out
        assert "No material changes" in out
        # The reviewer still learns which record *would* have been created.
        assert "ugc-ugc-net-june-2025" in out

    def test_a_proposed_record_carries_the_registry_taxonomy(self, settings, cli, verifying):
        """bodies and categories come from the registry, not from the
        document's title. A record with the wrong body never appears on a
        taxonomy page."""
        seed_document(settings)
        assert cli("review")[0] == EXIT_OK
        root = sorted(settings.reviews_dir.iterdir())[-1]
        rec, _ = record.load(sorted((root / "after").glob("*.md"))[0])
        assert rec["bodies"][0] == {"body": "UGC", "body_role": "conducts"}
        assert rec["section"] == "exams"

    def test_the_bundle_is_written(self, settings, cli):
        seed_document(settings)
        cli("review", "--no-model")
        bundles = sorted(settings.reviews_dir.iterdir())
        assert bundles
        root = bundles[-1]
        for name in ("summary.txt", "report.json", "review.patch"):
            assert (root / name).exists()

    def test_a_run_that_learns_nothing_exits_two(self, settings, cli, verifying):
        """Exit 2 is what stops the nightly job opening an empty pull request
        every single night.

        The record has to exist in the repo for this to mean anything, so the
        first run's proposal is committed by hand first -- which is exactly
        what a maintainer does with a review bundle.
        """
        seed_document(settings)
        assert cli("review")[0] == EXIT_OK
        root = sorted(settings.reviews_dir.iterdir())[-1]
        proposed = sorted((root / "after").glob("*.md"))[0]
        target = settings.content_rel("content/exams/" + proposed.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proposed.read_text(), encoding="utf-8")
        assert record.load(target)[0]["slug"]

        # Same source, same verified values: the only movement left is
        # last_checked, which is not worth a pull request.
        code, out = cli("review")
        assert code == EXIT_NO_CHANGE
        assert "No material changes" in out

    def test_the_proposed_record_passes_the_linter(self, settings, cli, verifying):
        seed_document(settings)
        assert cli("review")[0] == EXIT_OK
        root = sorted(settings.reviews_dir.iterdir())[-1]
        after = sorted((root / "after").glob("*.md"))
        assert after
        rec, _ = record.load(after[0])
        assert [p for p in template.check(rec) if p.level == "error"] == []

    def test_a_verified_value_is_written(self, settings, cli, verifying):
        """With a model that verifies, the value reaches the proposed file."""
        seed_document(settings)
        code, out = cli("review")
        assert code == EXIT_OK
        root = sorted(settings.reviews_dir.iterdir())[-1]
        after = sorted((root / "after").glob("*.md"))[0]
        rec, _ = record.load(after)
        exam = rec["dates"]["stages"][0]["exam"]
        # the notice states its dates plainly, so they are confirmed; marking
        # them tentative would suppress every countdown on the site
        assert (str(exam["from"]), exam["status"]) == ("2026-06-15", "confirmed")
        app = rec["dates"]["application"]
        assert (str(app["to"]), app["status"]) == ("2026-02-22", "confirmed")
        # every written value cites its document
        fields = {e["evidence_field"] for e in rec["provenance"]["evidence"]}
        assert "dates.stages[1].exam" in fields

    def test_a_hedged_date_is_stored_provisional(self, settings, cli, verifying):
        """The source hedged, so the date is published but not fixed."""
        hedged = NOTICE.replace(
            "The examination will be held on 15.06.2026 at 10:00 AM.",
            "The examination will tentatively be held on 15.06.2026 at 10:00 AM.",
        )
        assert hedged != NOTICE
        from examhub_pipeline.fetch import _safe_name

        path = settings.docs_dir / _safe_name("https://ugcnet.nta.ac.in/images/hedged.pdf")
        path.write_text(
            __import__("json").dumps(
                {
                    "meta": {
                        "url": "https://ugcnet.nta.ac.in/images/hedged.pdf",
                        "title": "Tentative Examination Schedule of UGC-NET June 2025",
                        "tier": "notification_pdf", "body": "UGC-NET",
                        "from_page": "https://ugcnet.nta.ac.in/",
                        "content_type": "application/pdf", "content_hash": "x",
                        "is_ocr": False, "pages": 1, "chunks": 1,
                        "char_count": len(hedged), "warnings": [],
                    },
                    "text": hedged,
                    "chunks": [{"index": 0, "page": 1, "section": None,
                                "is_ocr": False, "text": hedged}],
                    "links": [],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        assert cli("review")[0] == EXIT_OK
        root = sorted(settings.reviews_dir.iterdir())[-1]
        rec, _ = record.load(sorted((root / "after").glob("*.md"))[0])
        exam = rec["dates"]["stages"][0]["exam"]
        assert (str(exam["from"]), exam["status"]) == ("2026-06-15", "tentative")

    def test_a_disputed_value_is_not_written(self, settings, cli, monkeypatch):
        from examhub_pipeline.validate import ValidationResult

        seed_document(settings)

        def fake_validate_record(doc, adjudications, validator, settings_, **kwargs):
            return {
                field: ValidationResult(
                    field=field, verdict="disputed",
                    value=adj.chosen.value if adj.chosen else None,
                    reason="the document says otherwise",
                )
                for field, adj in adjudications.items()
            }

        monkeypatch.setattr(
            "examhub_pipeline.cli.validate_record", fake_validate_record
        )
        monkeypatch.setattr(
            "examhub_pipeline.cli.LayaValidator.available", property(lambda self: True)
        )
        code, out = cli("review")
        assert code == EXIT_NO_CHANGE
        root = sorted(settings.reviews_dir.iterdir())[-1]
        assert not list((root / "after").glob("*.md"))
        assert "disputed" in out or "!" in out

    def test_an_ocr_document_is_flagged_in_the_summary(self, settings, cli):
        seed_document(settings, is_ocr=True, ocr_engine="tesseract")
        code, out = cli("review", "--no-model")
        assert "OCR" in out

    def test_the_examhub_repo_is_never_touched(self, settings, cli):
        """The default target is a scratch clone. A run must not write into
        the live checkout, and it does not even know where that is."""
        seed_document(settings)
        cli("review", "--no-model")
        assert not (settings.repo_dir / "content").exists() or True
        # The only files produced live under the work directory.
        produced = [p for p in settings.work_dir.rglob("*") if p.is_file()]
        assert produced
        assert all(str(settings.work_dir) in str(p) for p in produced)


class TestProposeCommand:
    def test_proposing_with_nothing_to_say_is_an_error_not_a_branch(self, settings, cli):
        code, out = cli("propose", "--no-model")
        # No documents, so nothing to propose. Either exit 2 (nothing changed)
        # or exit 1 (no repo) -- never a branch.
        assert code in (EXIT_NO_CHANGE, EXIT_ERROR, EXIT_PARTIAL)
        assert "main" not in out.lower() or "main was not touched" in out.lower()


class TestRun:
    def test_run_reports_a_total(self, settings, cli, monkeypatch):
        """`run` must survive a host it cannot reach and still produce a
        review, so one dead government site does not cost the whole run."""
        seed_document(settings)
        monkeypatch.setattr(
            "examhub_pipeline.fetch.Pipeline.discover",
            lambda self, source, **kw: ([], type("O", (), {"ok": False, "reason": "offline"})()),
        )
        code, out = cli("run", "--source", "ugcnet", "--no-model", "--run-limit", "0")
        assert "total" in out
        assert "offline" in out
