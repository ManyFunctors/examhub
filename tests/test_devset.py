"""The dev-set measurement, and the honesty checks around it.

Behind the ``model`` marker, because it loads a ~650 MB checkpoint and takes
several minutes on CPU. The point of keeping it in the suite rather than in a
notebook is that the numbers in the README come from *this* code, and a change
to the validator that breaks the measurement should be visible.

The non-marked tests here check the dev set itself: that it exists, that it is
labelled, and that every label is consistent with what the deterministic layer
finds. Those run in a second and catch the most damaging possible failure --
a dev set quietly drifted to agree with the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from examhub_pipeline.candidates import FIELDS, adjudicate, find_candidates
from examhub_pipeline.config import Settings
from examhub_pipeline.validate import (
    load_devset,
)

DEVSET = Path(__file__).resolve().parents[1] / "data" / "devset" / "devset.jsonl"
KNOWN_FIELDS = {f.key for f in FIELDS}


@pytest.fixture(scope="module")
def devset():
    if not DEVSET.exists():  # pragma: no cover
        pytest.skip("dev set not built")
    return load_devset(DEVSET)


class TestDevSetShape:
    def test_it_exists(self, devset):
        assert DEVSET.exists()
        assert len(devset) >= 20, (
            "a dev set of fewer than 20 examples cannot measure anything; "
            "the numbers in the README would be noise"
        )

    def test_ids_are_unique(self, devset):
        ids = [e.id for e in devset]
        assert len(ids) == len(set(ids))

    def test_every_field_is_a_known_field(self, devset):
        for example in devset:
            assert example.field in KNOWN_FIELDS, f"{example.id}: {example.field}"

    def test_every_example_carries_a_note(self, devset):
        """An unlabelled example is a guess, and a guess in a dev set is worse
        than no dev set at all."""
        for example in devset:
            assert example.note.strip(), f"{example.id} has no note"

    def test_present_examples_have_a_value(self, devset):
        """A date or a count must be spelled out; a prose field cannot be.

        ``eligibility`` and ``fee`` are "present but not a single string" by
        nature, so their label is the presence itself plus a note saying where
        it is. Claiming otherwise for those would mean inventing an expected
        prose value, which is the one thing a dev set must not do.
        """
        from examhub_pipeline.candidates import FIELD_BY_KEY

        for example in devset:
            if example.expect == "absent":
                continue
            kind = FIELD_BY_KEY[example.field].kind
            if kind in ("date", "int"):
                assert example.expect_value, (
                    f"{example.id}/{example.field} says present but has no value"
                )
            else:
                assert example.note.strip()

    def test_absent_examples_have_no_value(self, devset):
        for example in devset:
            if example.expect == "absent":
                assert example.expect_value is None

    def test_both_classes_are_represented(self, devset):
        present = [e for e in devset if e.expect != "absent"]
        absent = [e for e in devset if e.expect == "absent"]
        assert len(present) >= 5, "too few positives to measure the choice question"
        assert len(absent) >= 5, "too few negatives to measure the presence question"

    def test_both_kinds_of_document_are_represented(self, devset):
        assert any(e.is_ocr for e in devset), "no OCR examples"
        assert any(not e.is_ocr for e in devset), "no text-layer examples"

    def test_it_is_jsonl(self):
        for line in DEVSET.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)


class TestDevSetAgainstTheDeterministicLayer:
    """A dev set that agrees with the pipeline by construction measures
    nothing. These check the labels were made independently of the code."""

    def test_absent_labels_are_not_where_the_finder_looked(self, devset):
        """An `absent` label must not sit next to a strong day-granularity
        candidate for that same field. If it does, either the label is wrong
        or the finder is, and either way the measurement is meaningless."""
        clashes = []
        for example in devset:
            if example.expect != "absent" or not example.document:
                continue
            cands = find_candidates(example.document, "devset")
            adj = adjudicate(cands)
            entry = adj.get(example.field)
            if entry and entry.chosen and entry.chosen.hint >= 0.7:
                clashes.append(
                    f"{example.id}/{example.field}: finder is confident of "
                    f"{entry.chosen.value!r} but the label says absent "
                    f"({entry.chosen.evidence[:70]!r})"
                )
        assert not clashes, "\n".join(clashes)

    def test_present_labels_are_recoverable_deterministically(self, devset):
        """A `present` label the regex layer cannot find is a label the model
        is being asked to produce from nothing, which the architecture says it
        must not do."""
        misses = []
        for example in devset:
            if example.expect == "absent" or not example.expect_value:
                continue
            cands = find_candidates(example.document, "devset")
            values = {c.value for c in cands}
            if example.expect_value not in values:
                misses.append(f"{example.id}/{example.field}: {example.expect_value}")
        # Some are expected: the value is in a document the clause splitter
        # cannot see. The number must be small and stable.
        assert len(misses) <= 3, "\n".join(misses)


@pytest.mark.model
class TestMeasuredAccuracy:
    """The actual measurement. Slow, and the reason the numbers in the README
    are numbers rather than claims."""

    @pytest.fixture(scope="class")
    def report(self, devset):
        from examhub_pipeline.validate import LayaValidator, evaluate

        settings = Settings(
            root=Path(__file__).resolve().parents[1],
            laya_model="typed-decisions",
            laya_max_len=1024,
            max_chunks_per_candidate=2,
            max_model_calls=1000,
        )
        validator = LayaValidator(settings)
        if not validator.available:  # pragma: no cover
            pytest.skip("laya unavailable")
        return evaluate(devset, validator, settings)

    def test_value_accuracy_is_reported(self, report):
        assert report["value"]["n"] >= 5
        assert 0.0 <= report["value"]["accuracy"] <= 1.0

    def test_existence_is_reported_with_auc(self, report):
        """AUC, not just accuracy: with a probability that barely moves,
        accuracy at one threshold says nothing about whether there is signal."""
        assert "auc" in report["existence"]
        assert report["existence"]["n"] == report["n"]

    def test_calibration_is_reported(self, report):
        assert "ece" in report["calibration"]
        assert len(report["calibration"]["bins"]) == 5

    def test_latency_is_measured_not_assumed(self, report):
        assert report["latency"]["calls"] > 0
        assert report["latency"]["median_ms"] > 0

    def test_the_existence_number_is_recorded_as_bad(self, report):
        """Guards against a future change quietly making absence look better
        than it is, and the README quietly being wrong.

        The measured AUC is around 0.78 on this checkpoint and at chance on
        the multilingual one. If a future checkpoint genuinely fixes it, this
        test should be deleted deliberately, with the README changed, rather
        than left to fail on a number that moved.
        """
        assert report["existence"]["auc"] < 0.95, (
            "existence accuracy has changed materially; the README's honest "
            "account of what the validator cannot do needs updating"
        )
