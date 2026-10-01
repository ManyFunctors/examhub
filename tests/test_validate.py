"""Tests for the verification layer, with the model stubbed out.

Two things are being checked here:

* the *policy* -- which verdict a given set of model answers produces, and
  which of those verdicts may write a value;
* the *questions* -- that the `noul` and `choice` shapes are what Laya needs,
  and that the option list is closed, so the model cannot invent a value.

The accuracy of the model itself is **not** tested here; it is measured, and
the numbers live in the README and in `data/devset`. `test_devset.py` runs the
measurement behind the `model` marker.
"""

from __future__ import annotations

import pytest

from examhub_pipeline.candidates import (
    adjudicate,
    find_candidates,
)
from examhub_pipeline.config import Settings
from examhub_pipeline.extract import Chunk, ExtractedDoc
from examhub_pipeline.validate import (
    VERDICTS,
    LayaValidator,
    ModelUnavailable,
    _best,
    _calibration,
    _choice_confidence,
    _choice_for,
    _margin,
    _questions,
    _same_value,
    _score,
    _score_values,
    _strongest_noul,
    _validate_field,
    select_chunks,
    unvalidated_results,
    validate_record,
)

# --------------------------------------------------------------------------
# A stub model
# --------------------------------------------------------------------------


class StubValidator(LayaValidator):
    """A LayaValidator whose `predict` returns a scripted answer.

    It bypasses `load()` and the call budget so the policy can be tested
    without the checkpoint. Everything downstream of the model -- question
    construction, chunk selection, gating, verdict selection -- runs for real.
    """

    def __init__(self, settings, answer=None, fail=False):
        super().__init__(settings)
        self.answer = answer or {}
        self.fail = fail
        self._loaded = True
        self.seen: list[tuple[dict, dict]] = []

    def _predict(self, state, questions, kind, field):
        from examhub_pipeline.validate import _Call

        self.seen.append((dict(state), dict(questions)))
        self.calls.append(
            _Call(field=field, kind=kind, chars=len(state.get("document", "")),
                  seconds=0.001, checkpoint="stub")
        )
        if self.fail:
            raise ModelUnavailable("stub refuses")
        return self.answer


def make_doc(text: str, pages: int = 1, is_ocr: bool = False) -> ExtractedDoc:
    chunks = [
        Chunk(index=i, text=piece, page=pages, is_ocr=is_ocr)
        for i, piece in enumerate([text])
    ]
    return ExtractedDoc(
        url="https://x.gov.in/n.pdf", text=text, chunks=chunks,
        media_type="application/pdf", is_ocr=is_ocr, pages=pages,
        char_count=len(text),
    )


NOTICE = (
    "2. SCHEDULE OF EXAMINATION\n"
    "The examination will be held on 15.06.2026 at 10:00 AM.\n"
    "Last date to apply: 22.02.2026 up to 23:00 hours.\n"
)


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


class TestAvailability:
    def test_disabled_settings_report_unavailable(self, settings: Settings):
        settings = Settings(**{**settings.__dict__, "enable_model": False})
        validator = LayaValidator(settings)
        assert validator.available is False
        with pytest.raises(ModelUnavailable):
            validator.load()

    def test_missing_laya_reports_unavailable(self, settings: Settings, monkeypatch):
        """The pipeline must run with no model at all, loudly."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "laya" or name.startswith("laya."):
                raise ImportError("no module named laya")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        validator = LayaValidator(Settings(**{**settings.__dict__, "enable_model": True}))
        assert validator.available is False

    def test_the_call_budget_is_enforced(self, settings: Settings):
        """A bad registry must not spin for an hour on a CPU-only box at
        six seconds a call."""
        from examhub_pipeline.validate import _Call

        validator = LayaValidator(Settings(**{**settings.__dict__, "max_model_calls": 2}))
        validator._loaded = True
        validator._router = object()
        for _ in range(2):
            validator.calls.append(_Call(field="x", kind="noul", chars=1,
                                         seconds=0.0, checkpoint="stub"))
        assert validator.budget_left() == 0
        with pytest.raises(ModelUnavailable, match="budget"):
            validator._predict({"document": "x"}, {"q": {"type": "noul"}}, "noul", "exam_date")


# --------------------------------------------------------------------------
# Question construction
# --------------------------------------------------------------------------


class TestQuestions:
    def test_both_questions_ride_in_one_call(self):
        """A single forward pass. On this CPU box a pass costs roughly what
        two passes cost jointly, so asking both together is close to free."""
        questions = _questions("exam_date", ["exam_date: 2026-06-15"])
        assert set(questions) == {"publishes_field", "field_value"}
        assert questions["publishes_field"]["type"] == "noul"
        assert questions["field_value"]["type"] == "choice"

    def test_noul_criteria_are_keyed_true_and_false(self):
        """Those keys *are* the option text the model reads. Any other key is
        rejected by Laya, and accepted-but-dropped criteria are a documented
        way to get confidently wrong answers."""
        criteria = _questions("exam_date", ["x"])["publishes_field"]["criteria"]
        assert set(criteria) == {"true", "false"}
        assert "does not state" in criteria["false"]

    def test_the_option_list_is_closed(self):
        """The model picks from what the regex layer found. It cannot
        introduce a value that is not in the list."""
        options = ["exam_date: 2026-06-15", "exam_date: 2026-06-22"]
        criteria = _questions("exam_date", options)["field_value"]["criteria"]
        assert set(criteria) == {"option_1", "option_2", "none_of_these"}
        assert list(criteria.values())[:2] == options

    def test_a_single_candidate_is_still_a_two_way_question(self):
        criteria = _questions("exam_date", ["only one"])["field_value"]["criteria"]
        assert set(criteria) == {"option_1", "none_of_these"}


# --------------------------------------------------------------------------
# Answer parsing
# --------------------------------------------------------------------------


class TestAnswerParsing:
    def test_confidence_is_the_top_probability_not_the_library_field(self):
        """Laya reported confidence 0.02 for a choice whose top probability
        was 0.41. Gating on the library's own field would have marked every
        single field undecided."""
        answer = {"confidence": 0.0204, "answer_confidence": 0.4069,
                  "probabilities": {"a": 0.4069, "b": 0.2405, "c": 0.3526}}
        assert _choice_confidence(answer, answer["probabilities"]) == pytest.approx(0.4069)

    def test_confidence_falls_back_when_there_are_no_probabilities(self):
        assert _choice_confidence({"answer_confidence": 0.5}, {}) == 0.5
        assert _choice_confidence({"confidence": 0.4}, {}) == 0.4
        assert _choice_confidence({}, {}) is None

    def test_margin(self):
        assert _margin({"a": 0.5, "b": 0.2, "c": 0.3}) == pytest.approx(0.2)
        assert _margin({"a": 0.5}) is None
        assert _margin({}) is None

    def test_choice_lookup(self):
        options = ["one", "two", "three"]
        assert _choice_for(options, "option_2") == "two"
        assert _choice_for(options, "none_of_these") == "none of these"
        assert _choice_for(options, None) is None
        assert _choice_for(options, "option_9") is None

    def test_value_comparison_handles_both_date_spellings(self):
        assert _same_value("Last date to apply: 2026-02-22", "2026-02-22")
        assert _same_value("Last date to apply: 22.02.2026", "2026-02-22")
        assert not _same_value("Last date to apply: 23.02.2026", "2026-02-22")

    def test_best_window_prefers_the_confident_answer(self):
        from examhub_pipeline.validate import _Window

        weak = _Window(chunk=Chunk(0, "a", 1), noul_p=0.9, choice="option_1",
                       choice_confidence=0.3, margin=0.01)
        strong = _Window(chunk=Chunk(1, "b", 1), noul_p=0.4, choice="option_1",
                         choice_confidence=0.7, margin=0.3)
        assert _best([weak, strong]) is strong

    def test_strongest_noul_is_the_maximum_not_the_mean(self):
        """A date table is one page of sixty. Averaging sixty chunks where one
        says yes and fifty-nine are eligibility boilerplate drowns the answer,
        and erring towards "ask" rather than "assert absence" is the
        conservative direction."""
        from examhub_pipeline.validate import _Window

        chunks = [Chunk(i, "x", i + 1) for i in range(60)]
        windows = [
            _Window(chunk=c, noul_p=0.99, choice=None, choice_confidence=None, margin=None)
            if i == 41
            else _Window(chunk=c, noul_p=0.1, choice=None, choice_confidence=None, margin=None)
            for i, c in enumerate(chunks)
        ]
        assert _strongest_noul(windows) == pytest.approx(0.99)


# --------------------------------------------------------------------------
# Verdict policy
# --------------------------------------------------------------------------


def adjudications_for(text: str):
    return adjudicate(find_candidates(text, "https://x.gov.in/n.pdf"))


class TestVerdicts:
    @pytest.fixture
    def adj(self):
        return adjudications_for(NOTICE)

    def _validate(self, settings, adj, answer, field="exam_date"):
        validator = StubValidator(settings, answer=answer)
        return _validate_field(make_doc(NOTICE), field, adj[field], validator,
                               settings, "the examination")

    def _answers(self, noul=0.9, choice="option_1", conf=0.7, runner_up=None):
        """A scripted model reply.

        `conf` is the probability of the chosen option and `runner_up` of the
        strongest alternative, so a "confidently wrong" answer and a
        "correct but barely" answer are both expressible. Getting this
        backwards was a bug in the first version of this test: putting the
        low probability on option_1 made `none_of_these` the top option, so
        the gate under test never ran.
        """
        alternatives = [k for k in ("option_2", "none_of_these") if k != choice]
        probs = {choice: conf}
        # Split what is left over between the alternatives so the distribution
        # sums to 1 the way a real one does. `runner_up` pins the strongest
        # alternative when a test needs a specific shape.
        if runner_up is None:
            rest = (1.0 - conf) / len(alternatives)
            for other in alternatives:
                probs[other] = round(rest, 4)
        else:
            probs[alternatives[0]] = runner_up
            probs[alternatives[1]] = round(max(0.01, 1.0 - conf - runner_up), 4)
        assert probs[choice] == max(probs.values()), (
            f"fixture is wrong: {choice} is not the top option in {probs}"
        )
        return {
            "answers": {
                "publishes_field": {"type": "noul", "noul": noul},
                "field_value": {
                    "type": "choice", "choice": choice,
                    "probabilities": probs,
                    "answer_confidence": max(probs.values()),
                },
            }
        }

    def test_our_value_picked_confidently_is_verified(self, settings, adj):
        result = self._validate(settings, adj, self._answers())
        assert result.verdict == "verified"
        assert result.should_store is True
        assert result.value == "2026-06-15"
        assert result.publish_probability == 0.9

    def _windows_asked(self, settings, adj, answer):
        doc = make_doc(NOTICE)
        doc.chunks = [Chunk(index=i, text=NOTICE, page=i + 1) for i in range(3)]
        validator = StubValidator(settings, answer=answer)
        _validate_field(doc, "exam_date", adj["exam_date"], validator, settings, "the examination")
        return len(validator.seen)

    def test_a_confirmed_value_stops_after_one_window(self, settings, adj):
        assert self._windows_asked(settings, adj, self._answers()) == 1

    def test_an_unconfirmed_value_asks_every_window(self, settings, adj):
        disputed = self._answers(choice="none_of_these", conf=0.7)
        assert self._windows_asked(settings, adj, disputed) == 3

    def test_the_option_list_comes_from_the_candidates(self, settings, adj):
        """The first option is always our adjudicated value, and a correct
        answer is 'option_1'. If that stops being true this test fails
        loudly rather than the pipeline silently writing a wrong date."""
        validator = StubValidator(settings, answer=self._answers())
        _validate_field(make_doc(NOTICE), "exam_date", adj["exam_date"], validator,
                        settings, "the examination")
        state, questions = validator.seen[0]
        criteria = questions["field_value"]["criteria"]
        assert "2026-06-15" in criteria["option_1"]

    def test_none_of_these_is_disputed_and_writes_nothing(self, settings, adj):
        result = self._validate(settings, adj, self._answers(choice="none_of_these"))
        assert result.verdict == "disputed"
        assert result.should_store is False
        assert "value was NOT written" in result.reason

    def test_a_low_confidence_pick_is_undecided(self, settings, adj):
        """The model picked our value and we do not trust it enough to write.

        The gate is set above the achievable top probability rather than below
        it: with three options the top cannot go much under a third, so a
        fixture of 0.30/0.25/0.45 would have had "none of these" winning and
        would not have exercised the gate at all.
        """
        settings = Settings(**{**settings.__dict__, "choice_confidence_threshold": 0.9})
        result = self._validate(settings, adj, self._answers(conf=0.5))
        assert result.model_choice == "option_1"
        assert result.choice_confidence == 0.5
        assert result.verdict == "undecided"
        assert result.should_store is False
        assert "below the 0.90 gate" in result.reason

    def test_a_distractor_won_confidently_is_disputed(self, settings, adj):
        # Two candidates means option_2 exists.
        adj2 = adjudicate(
            find_candidates(
                NOTICE + "The date of the examination is 22.06.2026.", "u"
            )
        )
        answer = {
            "answers": {
                "publishes_field": {"type": "noul", "noul": 0.9},
                "field_value": {
                    "type": "choice", "choice": "option_2",
                    "probabilities": {"option_1": 0.2, "option_2": 0.7,
                                      "none_of_these": 0.1},
                },
            }
        }
        result = _validate_field(make_doc(NOTICE), "exam_date", adj2["exam_date"],
                                 StubValidator(settings, answer=answer), settings, "x")
        assert result.verdict == "disputed"
        assert "2026-06-22" in result.reason

    def test_a_found_candidate_the_model_cannot_see_is_a_tripwire(self, settings, adj):
        """Low presence probability next to a found candidate usually means a
        mislabelled date. It escalates; it never removes the key."""
        settings = Settings(**{**settings.__dict__, "absence_threshold": 0.5})
        result = self._validate(settings, adj, self._answers(noul=0.1))
        assert result.verdict == "undecided"
        assert "does not see this field" in result.reason
        assert result.should_store is False

    def test_no_model_answer_at_all(self, settings, adj):
        result = self._validate(settings, adj, {"answers": {}})
        assert result.verdict == "not_validated"
        assert result.should_store is False

    def test_a_failing_window_does_not_stop_the_run(self, settings, adj):
        """One unusable window must not lose the whole field, and must not
        crash the run either: validate_record catches the failure per field
        and marks the field unvalidated."""
        settings = Settings(**{**settings.__dict__, "max_chunks_per_candidate": 1})
        results = validate_record(make_doc(NOTICE), adj, StubValidator(settings, fail=True),
                                  settings)
        assert results["exam_date"].verdict == "not_validated"
        assert results["exam_date"].should_store is False
        # ...and the other fields still get an answer.
        assert all(r.verdict in VERDICTS for r in results.values())

    def test_ocr_is_carried_into_the_verdict(self, settings):
        """A value read off an OCR'd page is a lower-quality value and the
        reviewer has to be told before reading anything else."""
        text = NOTICE
        adj = adjudicate(find_candidates(text, "u", pages=[(1, text, True)]))
        assert adj["exam_date"].chosen.is_ocr is True
        validator = StubValidator(settings, answer=self._answers())
        result = _validate_field(make_doc(text, is_ocr=True), "exam_date",
                                 adj["exam_date"], validator, settings, "x")
        assert result.is_ocr is True
        assert "OCR" in result.reason


class TestOnlyVerifiedWrites:
    @pytest.fixture
    def adj(self):
        return adjudications_for(NOTICE)

    def test_absent_is_deterministic_not_model_driven(self, settings, adj):
        """This is the correction the measurements forced: the model cannot
        decide presence, so no candidate means absent, full stop."""
        # This notice has no registration_open at all.
        assert "registration_open" not in adj
        results = validate_record(make_doc(NOTICE), adj, StubValidator(settings),
                                  settings)
        assert results["registration_open"].verdict == "absent"
        assert results["registration_open"].should_store is False
        assert "does not publish it" in results["registration_open"].reason

    def test_month_only_is_absent_with_a_note(self, settings):
        adj = adjudicate(find_candidates("The tentative exam date is in June 2027.", "u"))
        results = validate_record(make_doc("x"), adj, StubValidator(settings), settings)
        assert results["exam_date"].verdict == "absent"
        assert "coarser than a day" in results["exam_date"].reason

    def test_every_known_field_gets_a_row(self, settings, adj):
        """A silent field is indistinguishable from a field nobody checked,
        so absence has to be stated rather than inferred from a gap."""
        from examhub_pipeline.candidates import FIELDS

        results = validate_record(make_doc(NOTICE), adj, StubValidator(settings), settings)
        assert set(results) == {f.key for f in FIELDS}
        assert all(r.verdict in VERDICTS for r in results.values())

    def test_without_a_model_found_values_are_flagged_and_absent_ones_are_not(
        self, settings, adj
    ):
        """Absence does not need a model -- that is the whole point of deciding
        it deterministically. Found values are flagged instead of written."""
        validator = LayaValidator(Settings(**{**settings.__dict__, "enable_model": False}))
        results = validate_record(make_doc(NOTICE), adj, validator, settings)
        assert results["exam_date"].verdict == "not_validated"
        assert results["registration_deadline"].verdict == "not_validated"
        assert results["result_date"].verdict == "absent"
        assert all(not r.should_store for r in results.values())

    def test_a_portal_tier_vacancy_count_is_never_stored(self, settings, adj):
        """Tier 2 aggregators are discovery-only, never a number."""
        text = NOTICE + "Total No. of Posts: 1044"
        adj2 = adjudicate(find_candidates(text, "u"))
        results = validate_record(make_doc(text), adj2, StubValidator(settings),
                                  settings, source_tier="official_portal")
        assert results["vacancies"].verdict == "heuristic"
        assert results["vacancies"].should_store is False

    def test_unvalidated_results_helper(self, settings, adj):
        results = unvalidated_results(adj, "no model")
        assert all(r.verdict == "not_validated" for r in results.values())
        assert all(r.reason == "no model" for r in results.values())


# --------------------------------------------------------------------------
# Chunk selection
# --------------------------------------------------------------------------


class TestChunkSelection:
    def test_the_chunk_with_the_evidence_is_chosen(self):
        """The deterministic layer already knows where the evidence is.
        Asking the model to re-derive that is the expensive and less reliable
        half of the job."""
        chunks = [
            Chunk(0, "Reservation rules apply to all candidates.", 1),
            Chunk(1, "Last date to apply: 22.02.2026 up to 23:00 hours.", 2),
            Chunk(2, "More boilerplate about candidates.", 3),
        ]
        doc = ExtractedDoc(url="u", text="", chunks=chunks)
        chosen = select_chunks(doc, "registration_deadline", "2026-02-22", limit=1)
        assert chosen[0] is chunks[1]

    def test_the_opening_chunk_is_always_considered(self):
        """On a government notice the first page is the summary table where
        the body states its own answer."""
        chunks = [Chunk(i, "unrelated filler " * 20, i + 1) for i in range(5)]
        doc = ExtractedDoc(url="u", text="", chunks=chunks)
        chosen = select_chunks(doc, "exam_date", "2026-06-15", limit=1)
        assert chosen and chosen[0] is chunks[0]

    def test_the_limit_is_respected(self):
        chunks = [Chunk(i, "last date to apply 22.02.2026 " * 5, i + 1) for i in range(10)]
        doc = ExtractedDoc(url="u", text="", chunks=chunks)
        assert len(select_chunks(doc, "registration_deadline", "2026-02-22", limit=3)) <= 3

    def test_a_document_with_no_chunks_selects_nothing(self):
        assert select_chunks(ExtractedDoc(url="u", text="x", chunks=[]), "exam_date", "") == []


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


class TestScoring:
    def test_auc_is_reported_because_accuracy_at_one_threshold_is_misleading(self):
        # The multilingual checkpoint's real shape: nearly everything pinned
        # near 1.0, so accuracy at a 0.75 gate looks fine while AUC says the
        # signal is barely there.
        rows = [("present", 0.99), ("present", 0.90), ("absent", 0.98), ("absent", 0.85)]
        score = _score(rows, Settings())
        assert score["auc"] == 0.75
        # At the configured 0.75 gate this looks like 50%; the best threshold
        # finds 75%. Reporting only the first would hide how little signal
        # there is, and reporting only the second would hide how bad the
        # default is.
        assert score["accuracy"] == 0.5
        assert score["best_accuracy"] == 0.75
        assert score["best_threshold"] == 0.9

    def test_a_perfect_separating_score(self):
        rows = [("present", 0.9), ("present", 0.8), ("absent", 0.2), ("absent", 0.1)]
        score = _score(rows, Settings())
        assert score["auc"] == 1.0
        assert score["best_accuracy"] == 1.0

    def test_a_chance_score(self):
        """The multilingual checkpoint's real behaviour on the presence
        question: every probability at 1.0 and no discrimination at all."""
        rows = [("present", 1.0)] * 5 + [("absent", 1.0)] * 5
        score = _score(rows, Settings())
        assert score["auc"] == 0.5
        assert score["mean_present"] == score["mean_absent"] == 1.0

    def test_empty_input(self):
        assert _score([], Settings())["n"] == 0
        assert _score_values([])["n"] == 0
        assert _calibration([])["bins"] == []

    def test_value_scoring_only_counts_rows_with_a_value(self):
        rows = [
            {"expect_value": "2026-06-15", "correct": True, "confidence": 0.6},
            {"expect_value": None, "correct": False, "confidence": 0.1},
        ]
        assert _score_values(rows)["n"] == 1
        assert _score_values(rows)["accuracy"] == 1.0

    def test_calibration_bins_are_monotone_in_the_right_direction(self):
        rows = [("present", 0.9)] * 4 + [("absent", 0.1)] * 4
        table = _calibration(rows, bins=2)
        populated = [b for b in table["bins"] if b["n"]]
        assert populated[0]["mean_p"] < populated[1]["mean_p"]
        assert populated[0]["fraction_present"] < populated[1]["fraction_present"]
        assert table["ece"] < 0.2

    def test_p_equal_to_one_lands_in_the_top_bin(self):
        """The last bin is closed, or a probability of exactly 1.0 falls
        through every bin and disappears from the table."""
        table = _calibration([("present", 1.0)], bins=5)
        assert table["bins"][-1]["n"] == 1

    def test_latency_stats(self):
        validator = StubValidator(Settings())
        from examhub_pipeline.validate import _Call

        for seconds in (0.1, 0.2, 0.3):
            validator.calls.append(_Call(field="x", kind="noul", chars=100,
                                         seconds=seconds, checkpoint="stub"))
        stats = validator.latency_stats()
        assert stats["calls"] == 3
        assert stats["median_ms"] == 200.0
        assert stats["mean_chars"] == 100

    def test_latency_stats_when_empty(self):
        assert LayaValidator(Settings()).latency_stats() == {}
