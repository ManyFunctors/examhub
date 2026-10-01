"""The review bundle and the one-screen diff.

This is the deliverable a human actually looks at. Its job is to be honest
about three different things at once, and to be readable in one screen:

1. **What changed** -- a field-level diff between the record as committed and
   the record this run would write.
2. **How confident the source is** -- verified against the document, read off
   a scan, or not checked at all.
3. **What is not being changed** -- a value the model disbelieved is left
   exactly as it is, and saying so is more useful than a silent skip.

Nothing here writes to the site. It writes a bundle into the
work directory: a unified diff, a machine-readable JSON report, a one-screen
text summary, and before/after copies of every record that would change.
"""

from __future__ import annotations

import difflib
import json
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import record, template
from .config import Settings
from .validate import SYMBOL, ValidationResult

# --------------------------------------------------------------------------
# Field-level diff
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One field, before and after."""

    field: str
    before: str | None
    after: str | None
    kind: str  # added | removed | changed | unchanged | status-change
    verdict: str = "unchanged"
    reason: str = ""
    confidence: float | None = None
    publish_probability: float | None = None
    is_ocr: bool = False

    @property
    def symbol(self) -> str:
        return SYMBOL.get(self.verdict, "?")

    @property
    def is_material(self) -> bool:
        return self.kind != "unchanged"


#: Paths that move on every run and say nothing about the exam.
BOOKKEEPING = ("provenance.", "links.documents")

#: A field set together with another shares its verdict.
COMPANIONS = {"posts.vacancies_status": "posts.vacancies_total"}

#: A window's flattened text: "2026-10-01 – 2026-10-20 (confirmed)".
_STATUS = re.compile(r"^(.*?)\s*\((\w+)\)$")


@dataclass(frozen=True, slots=True)
class Lint:
    """The template check of one record, split by level."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def lint(rec: dict) -> Lint:
    problems = template.check(rec)
    return Lint(tuple(str(p) for p in problems if p.level == "error"),
                tuple(str(p) for p in problems if p.level != "error"))


def diff_records(
    before: dict,
    after: dict,
    validations: Mapping[str, ValidationResult] | None = None,
) -> list[FieldChange]:
    """Field-level differences in template order; validations are keyed by record path."""
    validations = validations or {}
    old = record.flatten(before)
    new = record.flatten(after)
    order = list(old) + [k for k in new if k not in old]

    changes: list[FieldChange] = []
    for key in order:
        was, now = old.get(key), new.get(key)
        # the verdict of a window also covers its ends (dates.application.to)
        result = validations.get(key) or validations.get(COMPANIONS.get(key, "")) or next(
            (v for k, v in validations.items() if k.startswith(key + ".")), None)
        if was == now:
            # every field is listed, so a caller can look any one up
            changes.append(FieldChange(
                field=key, before=was, after=now, kind="unchanged",
                verdict=result.verdict if result else "unchanged",
                reason=result.reason if result else "",
                confidence=result.choice_confidence if result else None,
                publish_probability=result.publish_probability if result else None,
                is_ocr=bool(result and result.is_ocr)))
            continue
        if was is None:
            kind = "added"
        elif now is None:
            kind = "removed"
        else:
            mw, mn = _STATUS.match(was), _STATUS.match(now)
            kind = "status-change" if mw and mn and mw.group(1) == mn.group(1) else "changed"
        # bookkeeping carries no model verdict, so "?" keeps its meaning
        bookkeeping = key.startswith(BOOKKEEPING)
        changes.append(FieldChange(
            field=key, before=was, after=now, kind=kind,
            verdict="bookkeeping" if bookkeeping else (result.verdict if result else "undecided"),
            reason=result.reason if result else "",
            confidence=result.choice_confidence if result else None,
            publish_probability=result.publish_probability if result else None,
            is_ocr=bool(result and result.is_ocr)))
    # verdicts for fields the record has no place for are still reported
    placed = set(order)
    for key, result in validations.items():
        if key in placed or any(key.startswith(p + ".") for p in placed):
            continue
        changes.append(FieldChange(
            field=key, before=None, after=None, kind="unchanged",
            verdict=result.verdict, reason=result.reason,
            confidence=result.choice_confidence, publish_probability=result.publish_probability,
            is_ocr=bool(result.is_ocr)))
    return changes


# --------------------------------------------------------------------------
# The bundle
# --------------------------------------------------------------------------


@dataclass(slots=True)
class RecordChange:
    """A record this run would rewrite."""

    path: str  # repo-relative, e.g. content/exams/ssc-ssc-cgl-2026.md
    slug: str
    before: str
    after: str
    changes: list[FieldChange] = field(default_factory=list)
    lint_before: Lint | None = None
    lint_after: Lint | None = None
    provenance_source: str = ""
    ocr: bool = False
    #: True when there is no committed record at this path yet.
    is_new: bool = False

    @property
    def material(self) -> list[FieldChange]:
        return [c for c in self.changes if c.is_material]

    @property
    def wrote_a_fact(self) -> bool:
        """Did this run put a verified value into the record?"""
        return any(c.is_material and not c.field.startswith(BOOKKEEPING) for c in self.changes)

    @property
    def is_noop(self) -> bool:
        """True when nothing material changed, so the file is not rewritten.

        Provenance ``last_checked`` is excluded deliberately: a run that only
        moves ``last_checked`` has not learned anything, and opening a pull
        request for it every night is how an automated job gets ignored.

        A *new* record with no verified field is also a no-op. Proposing a stub
        that says only "last checked on the 27th" is not a fact anyone needs,
        and it is a record the next run will not recognise as its own.
        """
        substantive = [c for c in self.changes if c.is_material and not c.field.startswith(BOOKKEEPING)]
        if not substantive:
            return True
        if self.is_new and not self.wrote_a_fact:
            return True
        return False


@dataclass(slots=True)
class ReviewBundle:
    """Everything a reviewer needs, in one directory."""

    root: Path
    changes: list[RecordChange] = field(default_factory=list)
    created: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def material(self) -> list[RecordChange]:
        return [c for c in self.changes if not c.is_noop]

    @property
    def unverified(self) -> list[FieldChange]:
        out: list[FieldChange] = []
        for change in self.material:
            out.extend(
                c
                for c in change.changes
                if c.is_material and c.verdict in {"not_validated", "undecided", "disputed", "heuristic"}
            )
        return out

    def counts(self) -> dict[str, int]:
        counts = {"verified": 0, "absent": 0, "disputed": 0, "undecided": 0,
                  "not_validated": 0, "heuristic": 0}
        for change in self.changes:
            for fc in change.changes:
                counts[fc.verdict] = counts.get(fc.verdict, 0) + 1
        return counts

    # -- writing ----------------------------------------------------------

    def write(self, settings: Settings) -> Path:
        root = self.root
        (root / "before").mkdir(parents=True, exist_ok=True)
        (root / "after").mkdir(parents=True, exist_ok=True)

        for change in self.changes:
            if not change.is_noop:
                name = Path(change.path).name
                (root / "before" / name).write_text(change.before, encoding="utf-8")
                (root / "after" / name).write_text(change.after, encoding="utf-8")

        patch = self.unified_patch()
        (root / "review.patch").write_text(patch, encoding="utf-8")
        (root / "report.json").write_text(
            json.dumps(self.to_json(), indent=2, sort_keys=False, default=str),
            encoding="utf-8",
        )
        summary = self.render_summary()
        (root / "summary.txt").write_text(summary, encoding="utf-8")
        (root / "propose.patch").write_text(patch, encoding="utf-8")
        return root

    def unified_patch(self) -> str:
        chunks: list[str] = []
        for change in self.material:
            # a new record is a new file, so git apply creates it
            diff = difflib.unified_diff(
                [] if change.is_new else change.before.splitlines(keepends=True),
                change.after.splitlines(keepends=True),
                fromfile="/dev/null" if change.is_new else f"a/{change.path}",
                tofile=f"b/{change.path}",
                n=3,
            )
            text = "".join(diff)
            if text:
                chunks.append(text)
        return "".join(chunks)

    # -- reporting --------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "created": self.created.isoformat(),
            "meta": self.meta,
            "counts": self.counts(),
            "records": [
                {
                    "path": change.path,
                    "slug": change.slug,
                    "no_op": change.is_noop,
                    "ocr": change.ocr,
                    "provenance_source": change.provenance_source,
                    "lint_after": (
                        {"errors": list(change.lint_after.errors),
                         "warnings": list(change.lint_after.warnings)}
                        if change.lint_after
                        else None
                    ),
                    "changes": [
                        {
                            "field": c.field,
                            "kind": c.kind,
                            "before": c.before,
                            "after": c.after,
                            "verdict": c.verdict,
                            "confidence": c.confidence,
                            "publish_probability": c.publish_probability,
                            "is_ocr": c.is_ocr,
                            "reason": c.reason,
                        }
                        for c in change.changes
                    ],
                }
                for change in self.changes
            ],
        }

    def render_summary(self) -> str:
        """The one screen. Every line is a decision the reviewer has to make."""
        lines: list[str] = []
        counts = self.counts()
        material = self.material

        header = (
            f"examhub-pipeline review  {self.created.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"{len(material)} record(s) would change of {len(self.changes)} checked  |  "
            f"verified {counts['verified']}  "
            f"undecided {counts['undecided']}  "
            f"disputed {counts['disputed']}  "
            f"unvalidated {counts['not_validated']}  "
            f"absent(omitted) {counts['absent']}"
        )
        lines.append(header)
        if self.meta.get("model_available") is False:
            lines.append(
                "! Laya was NOT available. Nothing below is model-verified; every "
                "value is a regex candidate."
            )
        if self.meta.get("ocr_documents"):
            lines.append(
                f"! {self.meta['ocr_documents']} document(s) had no text layer and were "
                "OCR'd. Every value from those pages can be wrong."
            )
        lines.append("")

        if not material:
            lines.append("No material changes. Nothing to review.")
            return "\n".join(lines) + "\n"

        for change in material:
            lines.append(change.path)
            for fc in change.changes:
                if not fc.is_material:
                    continue
                lines.append("  " + _render_change(fc))
            flags = [
                f"unverified - {fc.field}"
                for fc in change.changes
                if fc.is_material and fc.verdict in {"not_validated", "heuristic"}
            ]
            if flags:
                lines.append("  ! " + ", ".join(flags) + "  unverified - needs a human read")
            if change.lint_after and change.lint_after.errors:
                for error in change.lint_after.errors:
                    lines.append(f"  X LINT {error}")
            if change.lint_after and change.lint_after.warnings:
                for warning in change.lint_after.warnings:
                    lines.append(f"  ~ LINT {warning}")
            lines.append("")

        lines.append(_footer(self))
        return "\n".join(lines) + "\n"

    def render(self, width: int = 100) -> str:
        return textwrap.fill(self.render_summary(), width=width) if width else self.render_summary()


def _render_change(fc: FieldChange) -> str:
    """One field, in the shape a reviewer can act on without a legend."""
    if fc.kind == "added":
        body = f"+ {fc.field}: {fc.after}"
    elif fc.kind == "removed":
        body = f"- {fc.field}: {fc.before}"
    elif fc.kind == "status-change":
        body = f"~ {fc.field}: {fc.after}"
    else:
        body = f"~ {fc.field}: {_trunc(fc.before, 46)} -> {_trunc(fc.after, 46)}"

    note = ""
    if fc.kind == "status-change":
        note = f"  (was {fc.before}, now {fc.after})"
    elif fc.verdict == "disputed":
        note = f"  ! {fc.reason}"
    elif fc.verdict == "undecided":
        note = f"  ? {fc.reason}"
    elif fc.verdict == "not_validated":
        note = "  — not model-checked"
    elif fc.verdict == "heuristic":
        note = f"  ! {fc.reason}"
    elif fc.confidence is not None:
        note = f"  (model {fc.confidence:.2f}"
        if fc.publish_probability is not None:
            note += f", publishes p={fc.publish_probability:.2f}"
        note += ")"
    if fc.is_ocr and "ocr" not in note.lower():
        note += "  [OCR page]"
    return f"{fc.symbol} {body}{note}"


def _footer(bundle: ReviewBundle) -> str:
    counts = bundle.counts()
    total = sum(counts.values()) or 1
    verified = counts["verified"]
    return (
        f"{verified}/{total} fields model-verified against the source. "
        "Nothing has been written to the site and nothing is "
        "published by this tool. Review, then `propose` to open a branch."
    )


def _trunc(value: str | None, width: int) -> str:
    if value is None:
        return "-"
    value = " ".join(str(value).split())
    return value if len(value) <= width else value[: width - 1] + "…"


# --------------------------------------------------------------------------
# Building a bundle
# --------------------------------------------------------------------------


def build_bundle(
    settings: Settings,
    pairs: Iterable[tuple[str, dict, dict, Mapping[str, ValidationResult] | None, dict[str, Any]]],
    *,
    meta: dict[str, Any] | None = None,
    stamp: str | None = None,
) -> ReviewBundle:
    """Assemble a bundle from ``(path, before, after, validations, extra)``.

    ``extra`` may carry ``body`` (the page text after the front matter),
    ``is_new``, ``ocr`` and ``source_url``.
    """
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = ReviewBundle(root=settings.reviews_dir / stamp, meta=dict(meta or {}))
    for path, before, after, validations, extra in pairs:
        body = extra.get("body", "")
        bundle.changes.append(RecordChange(
            path=path,
            slug=str(after.get("slug") or Path(path).stem),
            before=record.dumps(before, body),
            after=record.dumps(after, body),
            changes=diff_records(before, after, validations),
            lint_before=lint(before),
            lint_after=lint(after),
            provenance_source=extra.get("source_url", ""),
            ocr=bool(extra.get("ocr", False)),
            is_new=bool(extra.get("is_new", False)),
        ))
    return bundle


def load_baseline(settings: Settings, path: str) -> tuple[dict, str] | None:
    """The committed record and its page body, or None when there is none yet.

    A missing record makes the run a proposal to add one, reported as such.
    """
    try:
        target = settings.content_rel(path)
    except ValueError:
        return None
    if not target.exists():
        return None
    try:
        return record.load(target)
    except Exception:  # noqa: BLE001 - a broken baseline is reported, not fatal
        return None
