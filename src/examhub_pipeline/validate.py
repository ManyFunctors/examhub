"""The "verify" layer: Laya checks whether the source really says each candidate.

**Deterministic code extracts; the model verifies; never the reverse.**
``candidates.py`` found the dates. This module decides whether the document
actually publishes them, using Laya's three typed primitives in the shape they
were designed for:

``noul`` -- "does this notice publish a last date to apply at all?"
    This is the site's core rule: *absent field = not rendered*. Whether a
    field is present is a proposition about the document, and ``noul`` returns
    a calibrated P(true) for exactly that. A generative model cannot express
    the question at all; a fixed-label classifier can only answer it badly.

``choice`` -- "which of these does the notice give as the last date?"
    The candidate values *are* the options. This is what the model is good
    at: a small, closed label space over a state it has to read once.

``score`` -- reserved for grader severity, used when a document needs ranking
    rather than a label (how far a revision is from the original).

What this module deliberately does **not** do:

* It does not generate, rewrite or extract text. There is no LLM here.
* It does not create a date that ``candidates.py`` did not find. A model
  cannot invent a value; the option list is closed.
* It does not promote ``provisional`` to ``confirmed``. Thresholds decide
  presence; nothing here decides that a body has fixed a date.
* **It does not decide absence on its own.** See "Absence is deterministic"
  below -- this is the most important correction the measurements forced.

Availability is optional by design. If ``laya`` is not importable, or the
weights cannot be fetched, every candidate comes back ``not_validated`` and
the review bundle says so. The pipeline still runs, still produces a diff,
and the reviewer simply gets less help.

---

Absence is deterministic
------------------------

The original design asked ``noul`` "does this document publish a last date to
apply?" and used the answer to decide whether to emit the key. Measured on
the labelled dev set in ``data/devset`` (18 real notifications: UGC-NET
admit-card, provisional-answer-key, results press release, the NTA
examination calendar, the AIIMS key-dates page, plus short synthetic
positives and negatives), that question does not work. Four phrasings were
tried on both the ``multilingual`` and ``typed-decisions`` checkpoints:

    formulation                       best accuracy   AUC
    noul, generic presence            0.611           0.591
    noul, specific claimed value      0.500           0.584
    two-option choice, yes/no         0.667           0.688
    noul, terse "is X written"       0.611           0.591

Every one of them is at or near chance on real notice text, and the
``multilingual`` checkpoint returns P(true) = 1.000 for every document
whether the field is there or not. A threshold on a probability that does
not vary is not a threshold.

So absence is decided where the architecture says it should be -- in
deterministic code. If ``candidates.py`` found no candidate for a field, the
field is absent, full stop. The model's probability is still computed and
still reported, because it is useful context for a reviewer, but it can never
by itself add or remove a key.

The same measurement found that value verification *does* work, but only on
the ``typed-decisions`` checkpoint: 6/6 correct picks against a two-distractor
choice question, where the ``multilingual`` checkpoint scored 0/6 and always
answered the same near-uniform distractor. Hence the default checkpoint is
``typed-decisions``, not ``multilingual``, even though the latter is 2.2x
faster. Speed does not matter when the answer is wrong.
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Mapping, Sequence

from .candidates import (
    FIELD_BY_KEY,
    FIELDS,
    Adjudication,
    normalise,
)
from .config import Settings
from .extract import Chunk, ExtractedDoc

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """Laya cannot be used in this environment."""


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------

#: The vocabulary the reviewer sees. Deliberately blunt.
#:
#:  verified      the document publishes the field AND the model picked our value
#:  absent        the document does not publish the field; omit the key
#:  disputed      the document publishes the field but not our value; a human decides
#:  undecided     the model is between the thresholds; a human decides
#:  not_validated Laya is unavailable, so nothing was checked
#:  heuristic     the value came from a non-official tier; discovery only
VERDICTS = (
    "verified",
    "absent",
    "disputed",
    "undecided",
    "not_validated",
    "heuristic",
    # Not a verdict about the data. Used by the review layer for provenance
    # and other fields the pipeline maintains rather than discovers.
    "bookkeeping",
)

SYMBOL = {
    "verified": "✓",
    # Provenance and other bookkeeping: not a claim about the exam, so no
    # verdict and no colour. Marking it with the undecided symbol would put
    # a "?" on every line of every run and make the real ones invisible.
    "bookkeeping": ".",
    "absent": "·",
    "disputed": "!",
    "undecided": "?",
    "not_validated": "—",
    "heuristic": "!",
}


@dataclass(slots=True)
class ValidationResult:
    """What the model said about one field of one document."""

    field: str
    verdict: str
    #: The value the pipeline wants to store.
    value: str | None
    #: What the model chose, when it was a `choice` question.
    model_choice: str | None = None
    #: The option text of ``model_choice``, so the bundle is readable without
    #: reconstructing the question.
    model_choice_text: str | None = None
    choice_confidence: float | None = None
    choice_margin: float | None = None
    #: P(document publishes this field). From the ``noul`` question.
    publish_probability: float | None = None
    #: The calibrated probability the field is *not* published, for the record.
    absence_probability: float | None = None
    #: Why the verdict is what it is, in one line.
    reason: str = ""
    chunk_locations: list[str] = dc_field(default_factory=list)
    is_ocr: bool = False
    #: True when the source hedged around this date ("tentative", "proposed",
    #: "subject to change", or a document-level disclaimer). Travels all the
    #: way to front matter: a date the body has published but not fixed is
    #: stored `provisional`, and only a human can promote it.
    provisional: bool = False
    latency_ms: float | None = None
    checkpoint: str | None = None
    source_url: str = ""
    evidence: str = ""

    @property
    def symbol(self) -> str:
        return SYMBOL.get(self.verdict, "?")

    @property
    def should_store(self) -> bool:
        """Whether a value may be written into front matter at all.

        Only ``verified`` values may be written silently. Everything else is
        either omitted (``absent``) or flagged for a human.
        """
        return self.verdict == "verified"

    def to_json(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "verdict": self.verdict,
            "value": self.value,
            "model_choice": self.model_choice,
            "model_choice_text": self.model_choice_text,
            "choice_confidence": self.choice_confidence,
            "choice_margin": self.choice_margin,
            "provisional": self.provisional,
            "publish_probability": self.publish_probability,
            "absence_probability": self.absence_probability,
            "reason": self.reason,
            "chunks": self.chunk_locations,
            "is_ocr": self.is_ocr,
            "latency_ms": self.latency_ms,
            "checkpoint": self.checkpoint,
            "source_url": self.source_url,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------
# The validator
# --------------------------------------------------------------------------


@dataclass
class _Call:
    """One measured ``router.predict`` call. Kept for the benchmark."""

    field: str
    kind: str  # 'noul' | 'choice' | 'score'
    chars: int
    seconds: float
    checkpoint: str


class LayaValidator:
    """Thin, opinionated wrapper around :class:`laya.Router`.

    All the intelligence is in the question templates below; the wrapper
    exists to make the model optional, to route every English notice to the
    multilingual checkpoint (the English one caps at 512 tokens and a notice
    page blows straight through it), and to count every call.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[_Call] = []
        self._router: Any = None
        self._max_len_used = 0
        self._loaded = False

    # -- lifecycle --------------------------------------------------------

    def load(self) -> None:
        if self._loaded:
            return
        if not self.settings.enable_model:
            raise ModelUnavailable("model path disabled by settings")
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise ModelUnavailable(f"torch is not importable: {exc}") from exc
        torch.set_num_threads(max(1, self.settings.torch_threads))
        torch.set_grad_enabled(False)
        try:
            from laya import Router
        except Exception as exc:
            raise ModelUnavailable(
                f"laya is not importable ({exc}). Install the extra: "
                "uv pip install -e '.[model]'"
            ) from exc
        try:
            self._router = Router(default=self.settings.laya_model)
        except Exception as exc:
            raise ModelUnavailable(f"could not construct the Laya Router: {exc}") from exc
        self._loaded = True

    @property
    def available(self) -> bool:
        if not self._loaded:
            try:
                self.load()
            except ModelUnavailable:
                return False
        return True

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def budget_left(self) -> int:
        return max(0, self.settings.max_model_calls - len(self.calls))

    # -- the actual call --------------------------------------------------

    def _predict(
        self, state: Mapping[str, Any], questions: Mapping[str, Any], kind: str, field: str
    ) -> dict[str, Any]:
        self.load()
        if self.budget_left() <= 0:
            raise ModelUnavailable(
                f"model call budget of {self.settings.max_model_calls} is exhausted"
            )
        assert self._router is not None
        started = time.perf_counter()
        result = self._router.predict(
            dict(state),
            dict(questions),
            model=self.settings.laya_model,
            max_len=self.settings.laya_max_len,
        )
        elapsed = time.perf_counter() - started
        self.calls.append(
            _Call(
                field=field,
                kind=kind,
                chars=len(str(state.get("document", ""))),
                seconds=elapsed,
                checkpoint=self.settings.laya_model,
            )
        )
        self._max_len_used = max(self._max_len_used, self.settings.laya_max_len)
        return result

    def latency_stats(self) -> dict[str, float]:
        if not self.calls:
            return {}
        values = sorted(c.seconds for c in self.calls)
        return {
            "calls": float(len(values)),
            "median_ms": round(statistics.median(values) * 1000, 1),
            "min_ms": round(values[0] * 1000, 1),
            "max_ms": round(values[-1] * 1000, 1),
            "mean_chars": round(statistics.mean(c.chars for c in self.calls)),
        }


# --------------------------------------------------------------------------
# Question templates
# --------------------------------------------------------------------------

#: "Does this document publish <field> at all?" -- the absence question.
#:
#: This is the one the whole design turns on. openjev (a fixed-label
#: classifier) cannot represent "this field is not in the document"; it can
#: only pick the nearest label and be confidently wrong. Laya's ``noul``
#: returns a calibrated P(true), and a low one is *evidence of absence*
#: rather than a guess.
_PUBLISH_INSTRUCTIONS = {
    "exam_date": "Does this notice state a specific date on which the examination will be held?",
    "registration_open": "Does this notice state the date on which online registration opens?",
    "registration_deadline": "Does this notice state a last date for candidates to apply?",
    "payment_deadline": "Does this notice state a separate last date for paying the application fee?",
    "admit_card_from": "Does this notice state the date from which admit cards or hall tickets can be downloaded?",
    "admit_card_to": "Does this notice state a closing date for downloading the admit card?",
    "result_date": "Does this notice state a specific date for the declaration of the result?",
    "age_as_on": "Does this notice state a reference date on which the age limit is computed?",
    "vacancies": "Does this notice state how many posts or vacancies are on offer?",
    "fee": "Does this notice state an application fee, or state that the fee is nil?",
    "negative_marking": "Does this notice state whether there is negative marking?",
    "mode": "Does this notice state the mode in which the examination is conducted?",
    "duration": "Does this notice state how long the examination lasts?",
    "venue": "Does this notice state where the examination will be held?",
    "eligibility": "Does this notice state eligibility criteria for candidates?",
    "pay": "Does this notice state a pay scale, pay matrix level or salary range for the posts?",
}

#: The `choice` criteria. Each option is a *whole claim*, phrased the way the
#: document would phrase it, so the model is comparing text to text rather
#: than matching a bare date string it has never seen in a notice.
def _choice_criteria(
    field: str, options: Sequence[str]
) -> dict[str, str]:
    criteria: dict[str, str] = {}
    for index, option in enumerate(options, start=1):
        criteria[f"option_{index}"] = option
    criteria["none_of_these"] = (
        "The notice does not state any of these values for this field."
    )
    return criteria


def _claim_text(field: str, value: str, provisional: bool) -> str:
    label = FIELD_BY_KEY[field].label if field in FIELD_BY_KEY else field
    hedge = " (described as tentative or provisional)" if provisional else ""
    return f"{label.capitalize()}: {value}{hedge}"


# --------------------------------------------------------------------------
# Chunk selection
# --------------------------------------------------------------------------


def select_chunks(
    doc: ExtractedDoc,
    field: str,
    value: str,
    *,
    limit: int | None = None,
) -> list[Chunk]:
    """Choose the windows to ask about, cheapest-to-best.

    The deterministic layer already knows where the evidence is, because it
    found it there. Asking the model to re-derive that is the expensive and
    less reliable half of the job. So:

    1. the chunk containing the candidate's own evidence, if the evidence
       offset is known;
    2. otherwise the chunks with the densest label-word hits for this field;
    3. plus the opening chunk, which on a government notice is the summary
       table where the body states its own answer.

    Deduplicated, capped, and never more than ``limit``.
    """
    limit = limit or 3
    label = FIELD_BY_KEY[field].label if field in FIELD_BY_KEY else field
    words = [w for w in re_words(label) if len(w) > 3]
    words += _EXTRA_LABEL_WORDS.get(field, ())

    scored: list[tuple[float, int, Chunk]] = []
    for position, chunk in enumerate(doc.chunks):
        text = chunk.text
        if not text:
            continue
        score = 0.0
        low = text.lower()
        for word in words:
            score += low.count(word)
        if value and value in text:
            score += 3.0
        if _looks_like_header(text):
            score += 1.5
        if position == 0:
            score += 1.0
        scored.append((score, position, chunk))

    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = [chunk for score, _, chunk in scored[:limit] if score > 0]
    if not chosen:
        chosen = [doc.chunks[0]] if doc.chunks else []
    return chosen


_EXTRA_LABEL_WORDS: dict[str, tuple[str, ...]] = {
    "exam_date": ("examination", "exam", "held", "conducted", "prelims", "mains", "schedule"),
    "registration_deadline": ("last date", "closing date", "apply", "application", "deadline"),
    "registration_open": ("commence", "registration", "opens", "online"),
    "payment_deadline": ("fee", "payment", "paid"),
    "admit_card_from": ("admit card", "hall ticket", "download", "available"),
    "admit_card_to": ("admit card", "hall ticket", "valid"),
    "result_date": ("result", "declared", "merit"),
    "age_as_on": ("age", "born", "years"),
    "vacancies": ("vacancies", "posts", "positions", "total"),
    "fee": ("fee", "rupees", "rs"),
    "negative_marking": ("negative", "marking", "deduct", "wrong"),
    "mode": ("mode", "cbt", "computer", "omr", "offline", "online"),
    "duration": ("duration", "hours", "minutes"),
    "venue": ("centres", "centre", "venue", "centres"),
    "eligibility": ("eligibility", "eligible", "qualification", "degree", "age"),
    "pay": ("pay", "level", "scale", "salary", "grade"),
}

#: A page that starts with a table or a numbered clause is where the facts
#: are in a government notice.
_HEADER_RE = None


def _looks_like_header(text: str) -> bool:
    global _HEADER_RE
    if _HEADER_RE is None:
        import re

        _HEADER_RE = re.compile(
            r"^\s*(\d{1,2}[.)]\s|S\.?No\.?\s|Sl\.?\s|Item\s|TABLE\b|\|)", re.I
        )
    return bool(_HEADER_RE.match(text[:200]))


def re_words(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", text.lower())


# --------------------------------------------------------------------------
# The validation pass
# --------------------------------------------------------------------------


def validate_record(
    doc: ExtractedDoc,
    adjudications: Mapping[str, Adjudication],
    validator: LayaValidator,
    settings: Settings,
    *,
    exam_name: str = "this examination",
    source_tier: str = "notification_pdf",
) -> dict[str, ValidationResult]:
    """Verify every adjudicated field of one document.

    Returns a mapping of field -> result. Every field gets a result, including
    the ones that could not be checked, so the review bundle has a row for
    everything a candidate exists for.
    """
    results: dict[str, ValidationResult] = {}
    available = validator.available

    # Every field the schema knows about gets a row, not only the ones a
    # candidate turned up for. A silent field is indistinguishable from a
    # field nobody looked at, and "the body does not publish a result date"
    # is a finding the reviewer wants stated rather than inferred.
    for field in FIELDS:
        adjudications.setdefault(
            field.key,
            Adjudication(
                field=field.key,
                chosen=None,
                reason="no candidate for this field anywhere in the document",
            ),
        )

    for field, adj in sorted(adjudications.items()):
        if adj.chosen is None:
            # Nothing to verify. Two possible reasons, both deterministic:
            #
            # 1. Only month-level findings. Coarser than a day is prose, not
            #    a date, so there is nothing to store and nothing to check.
            # 2. No candidate at all for this field, which means the
            #    document does not publish it and the key is omitted.
            #
            # Deciding this here rather than by asking the model is the whole
            # point of the architecture rule. See the module docstring: the
            # model's presence question does not work on real notices.
            if adj.coarse_notes:
                reason = (
                    f"only month-level dates found ({len(adj.coarse_notes)} note(s)); "
                    "coarser than a day is prose, not a date, so the key is omitted"
                )
            else:
                reason = (
                    "no candidate for this field anywhere in the document; the body "
                    "does not publish it, so the key is omitted"
                )
            first = adj.coarse_notes[0] if adj.coarse_notes else None
            results[field] = ValidationResult(
                field=field,
                verdict="absent",
                value=None,
                reason=reason,
                is_ocr=bool(first and first.is_ocr),
                source_url=first.source_url if first else "",
                evidence=first.evidence if first else "",
            )
            continue

        if source_tier in {"official_portal"} and field in {"vacancies"}:
            results[field] = _heuristic(field, adj, "aggregator/portal tier: discovery only")
            continue

        if not available:
            results[field] = ValidationResult(
                field=field,
                verdict="not_validated",
                value=adj.chosen.value,
                provisional=adj.chosen.provisional,
                reason="Laya unavailable; candidate is unverified and must be reviewed by hand",
                is_ocr=adj.chosen.is_ocr,
                source_url=adj.chosen.source_url,
                evidence=adj.chosen.evidence,
            )
            continue

        try:
            results[field] = _validate_field(
                doc, field, adj, validator, settings, exam_name
            )
        except ModelUnavailable as exc:
            log.info("stopping validation for %s: %s", field, exc)
            results[field] = ValidationResult(
                field=field,
                verdict="not_validated",
                value=adj.chosen.value,
                reason=str(exc),
                is_ocr=adj.chosen.is_ocr,
                source_url=adj.chosen.source_url,
                evidence=adj.chosen.evidence,
            )
    return results


def _heuristic(field: str, adj: Adjudication, why: str) -> ValidationResult:
    chosen = adj.chosen
    return ValidationResult(
        field=field,
        verdict="heuristic",
        value=chosen.value if chosen else None,
        reason=why,
        is_ocr=bool(chosen and chosen.is_ocr),
        source_url=chosen.source_url if chosen else "",
        evidence=chosen.evidence if chosen else "",
    )


def _validate_field(
    doc: ExtractedDoc,
    field: str,
    adj: Adjudication,
    validator: LayaValidator,
    settings: Settings,
    exam_name: str,
) -> ValidationResult:
    """Verify one field against the document, in one batched pass per window."""
    chosen = adj.chosen
    assert chosen is not None
    value = chosen.value

    # The option list is the set of distinct candidate values for this field,
    # ordered so that the winning candidate is first. One option plus
    # "none of these" is still a two-way question, which is exactly what a
    # single-candidate field should be asked.
    options: list[str] = []
    for candidate in [chosen, *adj.rejected]:
        text = _claim_text(field, candidate.value, candidate.provisional)
        if text not in options:
            options.append(text)
    if not options:
        options = [_claim_text(field, value, chosen.provisional)]

    chunks = select_chunks(doc, field, value, limit=settings.max_chunks_per_candidate)
    windows = _ask_field(doc, chunks, field, options, validator, settings, exam_name)
    locations = [w.chunk.location for w in windows]

    if not windows:
        return ValidationResult(
            field=field,
            verdict="not_validated",
            value=value,
            reason="the model could not be run on any window of this document",
            is_ocr=chosen.is_ocr,
            source_url=chosen.source_url,
            evidence=chosen.evidence,
        )

    publish_p = _strongest_noul(windows)
    best = _best(windows)
    choice = best.choice if best else None
    confidence = best.choice_confidence if best else None
    margin = best.margin if best else None

    base = dict(
        field=field,
        value=value,
        provisional=chosen.provisional,
        model_choice=choice,
        model_choice_text=_choice_for(options, choice),
        choice_confidence=None if confidence is None else round(confidence, 4),
        choice_margin=margin,
        publish_probability=None if publish_p is None else round(publish_p, 4),
        absence_probability=None if publish_p is None else round(1.0 - publish_p, 4),
        chunk_locations=locations,
        is_ocr=chosen.is_ocr,
        source_url=chosen.source_url,
        evidence=chosen.evidence,
    )

    if choice is None:
        return ValidationResult(
            verdict="not_validated",
            reason="the model returned no answer for the value question",
            **base,
        )

    if adj.ambiguous:
        # The regex layer could not attribute this clause's label to one of
        # the dates in it, so the question above was "does the document say
        # 2025-05-13 is the exam date?" about a date the pipeline had already
        # got wrong. A confident answer to a badly-posed question is still a
        # badly-posed question, so the model's verdict is discarded and the
        # value goes to a human. This is the case that produced
        # `exam_date = 2025-05-08` for an exam held on 25 June 2025, verified
        # at 0.61 confidence.
        return ValidationResult(
            verdict="undecided",
            reason=(
                "AMBIGUOUS candidate: the clause carries several full dates, so the "
                "label was never paired with one of them. The model's answer about "
                "it is not meaningful and the value was NOT written."
            ),
            **base,
        )

    picked = _choice_for(options, choice)

    # A low presence probability alongside a found candidate is a genuine
    # tripwire, and it is the one place the noul answer earns its keep. The
    # deterministic layer found something and the model does not see it in
    # the document: often a date attached to the wrong label, or a page the
    # chunker never showed the model. It escalates; it never drops the value.
    confident = confidence is not None and confidence >= settings.choice_confidence_threshold
    if publish_p is not None and publish_p <= settings.absence_threshold and confident:
        return ValidationResult(
            verdict="undecided",
            reason=(
                f"a candidate was found but the model does not see this field in the "
                f"document (noul P(true)={publish_p:.2f} <= {settings.absence_threshold:.2f}). "
                "Usually a mislabelled date; a human decides."
            ),
            **base,
        )

    if choice == "none_of_these":
        return ValidationResult(
            verdict="disputed",
            reason=(
                "the document appears to give a different value for this field; "
                f"the model matched none of our candidates (top probability "
                f"{confidence:.2f}). Our value was NOT written."
                if confidence
                else "the model matched none of our candidates; our value was NOT written"
            ),
            **base,
        )

    if picked is not None and _same_value(picked, value):
        if confidence is not None and confidence < settings.choice_confidence_threshold:
            return ValidationResult(
                verdict="undecided",
                reason=(
                    f"the model picked our value but only at {confidence:.2f}, below the "
                    f"{settings.choice_confidence_threshold:.2f} gate. Confirm by hand."
                ),
                **base,
            )
        return ValidationResult(
            verdict="verified",
            reason=(
                f"the model picked our value at {confidence:.2f}"
                + (f" on {best.chunk.location}" if best else "")
                + (
                    "; the page is OCR output, so the value itself is only as good "
                    "as the OCR"
                    if chosen.is_ocr
                    else ""
                )
            ),
            **base,
        )

    if confidence is not None and confidence < settings.choice_confidence_threshold:
        return ValidationResult(
            verdict="undecided",
            reason=(
                f"the model leaned towards {picked!r} at only {confidence:.2f}, which is "
                "not enough to call our value wrong. A human decides."
            ),
            **base,
        )
    return ValidationResult(
        verdict="disputed",
        reason=f"the document appears to say {picked!r} instead, at {confidence:.2f}",
        **base,
    )


def _choice_for(options: Sequence[str], key: str | None) -> str | None:
    if not key:
        return None
    if key == "none_of_these":
        return "none of these"
    try:
        return options[int(key.split("_", 1)[1]) - 1]
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return None


def _questions(
    field: str, options: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Both questions for one field, for a single forward pass.

    Laya evaluates every question in one pass, and on this CPU box a pass
    costs roughly what two passes cost jointly, so asking the existence
    question and the value question together is close to free. It is also
    one call per window instead of two, which is the difference between a
    60-second run and a 120-second run on a chunked document.
    """
    label = FIELD_BY_KEY[field].label if field in FIELD_BY_KEY else field
    return {
        "publishes_field": {
            "type": "noul",
            "instructions": f"Does this notice state {label}?",
            # The true/false keys on a noul *are* the option text the model
            # reads. Spelling both out stops the checkpoint answering from
            # the labels rather than from the state, which is a documented
            # failure mode on the English checkpoint.
            "criteria": {
                "true": f"yes, this notice states {label}",
                "false": f"no, this notice does not state {label}",
            },
        },
        "field_value": {
            "type": "choice",
            "instructions": f"According to this notice, what is {label}?",
            "criteria": _choice_criteria(field, options),
        },
    }


@dataclass(slots=True)
class _Window:
    """One model's answer about one window of the document."""

    chunk: Chunk
    noul_p: float | None
    choice: str | None
    choice_confidence: float | None
    margin: float | None


def _ask_field(
    doc: ExtractedDoc,
    chunks: Sequence[Chunk],
    field: str,
    options: Sequence[str],
    validator: LayaValidator,
    settings: Settings,
    exam_name: str = "this examination",
) -> list[_Window]:
    """Ask both questions of each selected window, one call per window.

    Stops at the first window that confirms our own candidate (option 1) above
    the confidence gate: later windows only cost time.
    """
    questions = _questions(field, options)
    out: list[_Window] = []
    for chunk in chunks:
        if not chunk.text.strip():
            continue
        state = {
            "document": chunk.text,
            "document_page": chunk.location,
            "examination": exam_name,
        }
        try:
            result = validator._predict(state, questions, "noul+choice", field)
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad window must not stop a run
            log.info("predict failed on %s: %s", chunk.location, exc)
            continue
        answers = result.get("answers") or {}
        choice_answer = answers.get("field_value") or {}
        probabilities = choice_answer.get("probabilities") or {}
        confidence = _choice_confidence(choice_answer, probabilities)
        margin = _margin(probabilities)
        out.append(
            _Window(
                chunk=chunk,
                noul_p=_read_noul(result, "publishes_field"),
                choice=choice_answer.get("choice"),
                choice_confidence=confidence,
                margin=margin,
            )
        )
        last = out[-1]
        if (last.choice == "option_1" and confidence is not None
                and confidence >= settings.choice_confidence_threshold
                and (last.noul_p is None or last.noul_p > settings.absence_threshold)):
            break
    return out


def _choice_confidence(answer: Mapping[str, Any], probabilities: Mapping[str, Any]) -> float | None:
    """The confidence to gate on.

    The library's own ``confidence`` key is not the top probability and is
    badly scaled: on a four-way choice with probabilities 0.41/0.24/0.35 it
    reported 0.02. ``answer_confidence`` equals the top probability, and
    ``max(probabilities)`` equals it too, so the top probability is what this
    pipeline gates on. Measured on the dev set, gating on the library's
    ``confidence`` would have marked every single field ``undecided``.
    """
    values = [_as_float(v) for v in probabilities.values()]
    values = [v for v in values if v is not None]
    if values:
        return max(values)
    for key in ("answer_confidence", "confidence"):
        value = _as_float(answer.get(key))
        if value is not None:
            return value
    return None


def _margin(probabilities: Mapping[str, Any]) -> float | None:
    values = sorted(
        v for v in (_as_float(x) for x in probabilities.values()) if v is not None
    )
    if len(values) < 2:
        return None
    return round(values[-1] - values[-2], 4)


def _best(windows: Sequence[_Window]) -> _Window | None:
    """The most informative window.

    Existence first (the highest P(true)), then the value answer. A window
    that answers the value question confidently is more useful than a window
    that merely mentions the field, because the value question is the one
    that gates a write.
    """
    if not windows:
        return None
    return max(
        windows,
        key=lambda w: (
            w.choice_confidence if w.choice_confidence is not None else 0.0,
            w.noul_p if w.noul_p is not None else 0.0,
        ),
    )


def _strongest_noul(windows: Sequence[_Window]) -> float | None:
    values = [w.noul_p for w in windows if w.noul_p is not None]
    return max(values) if values else None


def _same_value(picked: str, wanted: str) -> bool:
    """Compare a model-picked claim against our value.

    The claim is prose ("Last date to apply: 2027-02-22") and the value is
    bare, so the comparison is a substring test after normalisation. For
    dates this is exact; for prose fields it is a containment test, which is
    why prose fields are not adjudicated on a model choice alone.
    """
    a = normalise(picked).lower()
    b = normalise(wanted).lower()
    if b in a:
        return True
    # Date fields: 22.02.2026 and 2026-02-22 are the same day, and a notice
    # prints one while the model answers with the other. Compare the digit
    # groups as a set, which is order-independent, so both spellings match.
    #
    # Three groups is a full date. The earlier version of this test required
    # six, which no date has, so a correct answer in the other format was
    # always read as a disagreement -- the exact failure the review gate is
    # supposed to prevent, caused by the gate itself.
    digits_a = set(re_digits(a))
    digits_b = set(re_digits(b))
    if len(digits_b) >= 3 and digits_b <= digits_a:
        return True
    return False


def re_digits(text: str) -> list[str]:
    import re

    return re.findall(r"\d+", text)


def _read_noul(result: Mapping[str, Any], key: str) -> float | None:
    answer = (result.get("answers") or {}).get(key)
    if not isinstance(answer, Mapping):
        return None
    for field in ("noul", "probability", "score", "value"):
        if field in answer:
            value = _as_float(answer[field])
            if value is not None:
                return value
    return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Everything untested / degraded
# --------------------------------------------------------------------------


def unvalidated_results(
    adjudications: Mapping[str, Adjudication], reason: str
) -> dict[str, ValidationResult]:
    """The whole-pipeline fallback when Laya cannot be used at all."""
    out: dict[str, ValidationResult] = {}
    for field, adj in adjudications.items():
        chosen = adj.chosen
        if chosen is None:
            out[field] = ValidationResult(
                field=field, verdict="absent", value=None, reason=reason
            )
        else:
            out[field] = ValidationResult(
                field=field,
                verdict="not_validated",
                value=chosen.value,
                provisional=chosen.provisional,
                reason=reason,
                is_ocr=chosen.is_ocr,
                source_url=chosen.source_url,
                evidence=chosen.evidence,
            )
    return out


# --------------------------------------------------------------------------
# Dev-set evaluation
# --------------------------------------------------------------------------


@dataclass(slots=True)
class DevExample:
    """One labelled question: this chunk, this field, this is the answer."""

    id: str
    document: str
    field: str
    #: 'published' | 'absent' | value-level: the correct stored value
    expect: str
    expect_value: str | None = None
    note: str = ""
    page: int | None = None
    is_ocr: bool = False


def load_devset(path: Any) -> list[DevExample]:
    """Read the labelled dev set from a JSONL file."""
    import json as _json
    from pathlib import Path

    p = Path(path)
    if p.is_dir():
        p = p / "devset.jsonl"
    out: list[DevExample] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = _json.loads(line)
        out.append(
            DevExample(
                id=str(row.get("id") or f"ex{len(out) + 1}"),
                document=row.get("document", ""),
                field=row.get("field", ""),
                expect=row.get("expect", ""),
                expect_value=row.get("expect_value"),
                note=row.get("note", ""),
                page=row.get("page"),
                is_ocr=bool(row.get("is_ocr", False)),
            )
        )
    return out


def evaluate(
    examples: Sequence[DevExample],
    validator: LayaValidator,
    settings: Settings,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Measure whether validation is actually working.

    Two separate numbers, because they answer different questions and the
    measurements came out very differently:

    * **existence** -- does the model decide whether the document publishes
      the field at all? This is what the ``noul`` question was supposed to
      do. Reported with the confusion matrix, the best achievable accuracy
      over a threshold sweep, and AUC -- not just accuracy at the configured
      threshold, because with a probability that barely moves, "the best
      threshold" is the only honest summary.
    * **value** -- given that a candidate exists, does the ``choice``
      question pick the labelled value rather than a distractor? This is the
      part that gates a write, so it is the number that matters.

    Calibration is reported as a binned reliability table plus ECE, because
    the argument for Laya over a fixed-label classifier is that its
    probabilities are calibrated. If the bins are flat, that argument does
    not hold on this data and the threshold is a guess.
    """
    if not validator.available:
        return {"error": "Laya unavailable; nothing evaluated"}

    presence: list[tuple[str, float]] = []
    values: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []

    for example in examples:
        doc = _dev_doc(example)
        chunks = select_chunks(doc, example.field, example.expect_value or "", limit=2)
        options = list(_dev_options(example))
        windows = _ask_field(
            doc, chunks, example.field, options, validator, settings, "this examination"
        )
        if not windows:
            continue
        publish_p = _strongest_noul(windows)
        if publish_p is not None:
            presence.append(("present" if example.expect != "absent" else "absent", publish_p))

        truth_present = example.expect != "absent"
        best = _best(windows)
        choice = best.choice if best else None
        confidence = best.choice_confidence if best else None
        picked = _choice_for(options, choice) if choice else None
        correct = bool(
            truth_present and picked and _same_value(picked, example.expect_value or "")
        )
        row = {
            "id": example.id,
            "field": example.field,
            "expect": example.expect,
            "expect_value": example.expect_value,
            "picked": picked,
            "confidence": confidence,
            "noul": publish_p,
            "ocr": example.is_ocr,
        }
        values.append({**row, "correct": correct})
        if verbose or (truth_present and not correct):
            misses.append(row)
            print(
                f"  {example.id:24} {example.field:22} want={str(example.expect_value):11} "
                f"picked={str(picked)[:34]:36} conf={confidence} noul={publish_p}"
            )

    return {
        "n": len(values),
        "checkpoint": settings.laya_model,
        "existence": _score(presence, settings),
        "value": _score_values(values),
        "calibration": _calibration(presence),
        "latency": validator.latency_stats(),
        "misses": misses,
    }


def _dev_options(example: DevExample) -> list[str]:
    """The option list for a dev example: the truth, a distractor, and the
    two ways of saying no."""
    options: list[str] = []
    if example.expect_value:
        options.append(_claim_text(example.field, example.expect_value, False))
    if example.expect and example.expect != example.expect_value and example.expect not in (
        "present",
        "absent",
    ):
        options.append(_claim_text(example.field, example.expect, False))
    if not options:
        options.append(f"{example.field}: a value")
    return options


def _dev_doc(example: DevExample) -> ExtractedDoc:
    chunk = Chunk(index=0, text=example.document, page=example.page, is_ocr=example.is_ocr)
    return ExtractedDoc(
        url=example.id,
        text=example.document,
        chunks=[chunk],
        media_type="text/plain",
        is_ocr=example.is_ocr,
        char_count=len(example.document),
    )


def _score(
    rows: Sequence[tuple[str, float]], settings: Settings
) -> dict[str, Any]:
    """Confusion matrix at the configured threshold, plus AUC and best-threshold.

    AUC is the number to read first. With a probability that sits at 1.0 for
    every example, accuracy at any threshold is a coin flip dressed up as a
    result, and AUC says so immediately.
    """
    if not rows:
        return {"n": 0}
    positives = [p for truth, p in rows if truth == "present"]
    negatives = [p for truth, p in rows if truth == "absent"]
    threshold = settings.publish_threshold
    tp = sum(1 for p in positives if p >= threshold)
    fn = len(positives) - tp
    fp = sum(1 for p in negatives if p >= threshold)
    tn = len(negatives) - fp
    total = len(rows)

    sweep = []
    for step in range(1, 20):
        cut = step / 20
        correct = sum(1 for truth, p in rows if (p >= cut) == (truth == "present"))
        sweep.append((cut, correct / total))
    best_cut, best_acc = max(sweep, key=lambda t: t[1])

    if positives and negatives:
        wins = sum(1 for p in positives for q in negatives if p > q)
        ties = sum(1 for p in positives for q in negatives if p == q)
        auc = (wins + 0.5 * ties) / (len(positives) * len(negatives))
    else:
        auc = None

    return {
        "n": total,
        "n_present": len(positives),
        "n_absent": len(negatives),
        "accuracy": round((tp + tn) / total, 4) if total else None,
        "best_accuracy": round(best_acc, 4),
        "best_threshold": best_cut,
        "auc": None if auc is None else round(auc, 4),
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "threshold": threshold,
        "mean_present": round(sum(positives) / len(positives), 4) if positives else None,
        "mean_absent": round(sum(negatives) / len(negatives), 4) if negatives else None,
    }


def _score_values(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy of the choice question, with the misses listed.

    Only rows where a value was expected are counted. An ``absent`` example
    has no value to pick, so counting it here would measure a different
    question through the same number.
    """
    scored = [r for r in rows if r["expect_value"]]
    if not scored:
        return {"n": 0}
    right = sum(1 for r in scored if r["correct"])
    confidences = [r["confidence"] for r in scored if r["confidence"] is not None]
    return {
        "n": len(scored),
        "accuracy": round(right / len(scored), 4),
        "correct": right,
        "wrong": len(scored) - right,
        "mean_confidence_when_right": (
            round(
                sum(r["confidence"] for r in scored if r["correct"] and r["confidence"] is not None)
                / max(1, sum(1 for r in scored if r["correct"])),
                4,
            )
            if any(r["correct"] for r in scored)
            else None
        ),
        "mean_confidence_when_wrong": (
            round(
                sum(r["confidence"] for r in scored if not r["correct"] and r["confidence"] is not None)
                / max(1, sum(1 for r in scored if not r["correct"])),
                4,
            )
            if any(not r["correct"] for r in scored)
            else None
        ),
        "confidences": [round(c, 4) for c in confidences],
    }


def _calibration(
    rows: Sequence[tuple[str, float]], bins: int = 5
) -> dict[str, Any]:
    """Binned reliability table plus ECE.

    Reported because the whole argument for Laya is that its probabilities
    are calibrated (RLCD, strictly proper scoring rules). If the bins are flat
    the claim does not hold on *this* data and the threshold should be set by
    eye instead.
    """
    if not rows:
        return {"bins": []}
    buckets: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        inside = [
            (truth, p)
            for truth, p in rows
            # The top bin is closed so p == 1.0 lands in it.
            if (low <= p < high) or (index == bins - 1 and p == 1.0)
        ]
        if not inside:
            buckets.append(
                {
                    "range": f"{low:.1f}-{high:.1f}",
                    "n": 0,
                    "mean_p": None,
                    "fraction_present": None,
                }
            )
            continue
        mean_p = sum(p for _, p in inside) / len(inside)
        frac = sum(1 for truth, _ in inside if truth == "present") / len(inside)
        buckets.append(
            {
                "range": f"{low:.1f}-{high:.1f}",
                "n": len(inside),
                "mean_p": round(mean_p, 3),
                "fraction_present": round(frac, 3),
            }
        )
        ece += (len(inside) / len(rows)) * abs(mean_p - frac)
    return {"bins": buckets, "ece": round(ece, 4)}
