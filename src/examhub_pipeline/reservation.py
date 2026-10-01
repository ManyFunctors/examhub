"""Reservation classes: ``data/catalogue/reservation.toml`` as a matcher.

    >>> v = load()
    >>> v.classes_in("Fee: Rs 500 for General/OBC, nil for SC/ST/PwBD")
    ['Unreserved', 'OBC', 'SC', 'ST', 'PwBD']
    >>> v.classes_in("OSC", "hr"), v.classes_in("OSC", "jk")
    (['hr:OSC'], ['jk:OSC'])

Spellings of one class map to it; different classes are never merged (see
the file's header and ``docs/vocabulary.md``). A class or alias scoped to a
jurisdiction is only recognised in that jurisdiction's notices.

When patterns overlap, the longest match wins, and at equal length a
jurisdiction's own class wins over a national one. Deterministic, no model.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .catalogue import CATALOGUE_DIR, URL_RE

AXES = ("vertical", "horizontal", "locality", "gender", "all")
_STATE_ID = re.compile(r"^([a-z]{2}):(\S(?:.*\S)?)$")


@dataclass(frozen=True)
class Class:
    id: str
    short: str
    name: str
    axis: str
    family: str | None
    jurisdictions: tuple[str, ...] | None
    verified: bool
    source: str | None


#: A sub-class suffix: "-A", "-I", "-2". "BC-X" is not BC; it is a class the
#: vocabulary does not know yet, and must reach the worklist rather than be
#: merged into its prefix.
_SUFFIX = r"\s*-\s*(?:[A-Za-z]|[IVX]{1,3}|\d)(?![A-Za-z0-9])"


def _wrap(pattern: str) -> str:
    # Whole words only: "SC" must not match inside "B.Sc" or "DISC".
    return rf"(?<![A-Za-z0-9])(?:{pattern})(?![A-Za-z0-9])(?!{_SUFFIX})"


class Vocabulary:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.classes: dict[str, Class] = {}
        self.order: list[str] = []
        #: (compiled, class id, jurisdictions or None)
        self._patterns: list[tuple[re.Pattern[str], str, tuple[str, ...] | None]] = []
        self.errors: list[str] = []
        for item in data.get("class", []):
            cid = item.get("id", "")
            j = tuple(item["jurisdictions"]) if item.get("jurisdictions") else None
            if cid in self.classes:
                self.errors.append(f"reservation.toml: duplicate class id {cid!r}")
            self.classes[cid] = Class(
                id=cid,
                short=item.get("short", cid),
                name=item.get("name", cid),
                axis=item.get("axis", ""),
                family=item.get("family"),
                jurisdictions=j,
                verified=item.get("verified", True),
                source=item.get("source"),
            )
            self.order.append(cid)
            self._add(cid, j, item.get("aliases", []), re.I)
            self._add(cid, j, item.get("codes", []), 0)
        for item in data.get("alias", []):
            j = tuple(item["jurisdictions"]) if item.get("jurisdictions") else None
            self._add(item.get("to", ""), j, item.get("aliases", []), re.I)
            self._add(item.get("to", ""), j, item.get("codes", []), 0)
        self._rank = {cid: i for i, cid in enumerate(self.order)}

    def _add(self, cid: str, j: tuple[str, ...] | None, patterns: list[str], flags: int) -> None:
        for p in patterns:
            try:
                self._patterns.append((re.compile(_wrap(p), flags), cid, j))
            except re.error as exc:
                self.errors.append(f"reservation.toml: {cid!r}: bad pattern {p!r}: {exc}")

    # ------------------------------------------------------------------ matching

    @lru_cache(maxsize=64)
    def _for(self, jurisdiction: str | None) -> tuple[tuple[re.Pattern[str], str, bool], ...]:
        return tuple(
            (pat, cid, j is not None)
            for pat, cid, j in self._patterns
            if j is None or (jurisdiction is not None and jurisdiction in j)
        )

    def find(self, text: str, jurisdiction: str | None = None) -> list[tuple[int, int, str]]:
        """Non-overlapping (start, end, class id) spans, left to right."""
        hits: list[tuple[int, int, bool, str]] = []
        for pat, cid, scoped in self._for(jurisdiction):
            for m in pat.finditer(text or ""):
                if m.end() > m.start():
                    hits.append((m.start(), m.end(), scoped, cid))
        # Longest first at each start; a jurisdiction's own class breaks a tie.
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0]), not h[2], self._rank.get(h[3], 0)))
        out: list[tuple[int, int, str]] = []
        end = -1
        for start, stop, _, cid in hits:
            if start >= end:
                out.append((start, stop, cid))
                end = stop
        return out

    def classes_in(self, text: str, jurisdiction: str | None = None) -> list[str]:
        """Every class named in ``text``, in first-seen order, each once.

        "All candidates" only stands alone: in "women of all categories" it
        qualifies the class beside it and is dropped.
        """
        found = list(dict.fromkeys(cid for _, _, cid in self.find(text, jurisdiction)))
        if len(found) > 1:
            found = [c for c in found if self.axis(c) != "all"]
        return found

    def one(self, label: str, jurisdiction: str | None = None) -> str | None:
        """The single class a table header names, or None."""
        found = self.classes_in(label, jurisdiction)
        return found[0] if len(found) == 1 else None

    def unmatched(self, text: str, jurisdiction: str | None = None) -> str:
        """``text`` with every recognised class blanked out, for the worklist."""
        chars = list(text)
        for start, stop, _ in self.find(text, jurisdiction):
            chars[start:stop] = " " * (stop - start)
        return re.sub(r"\s+", " ", "".join(chars)).strip()

    # ------------------------------------------------------------------ queries

    def axis(self, cid: str) -> str | None:
        c = self.classes.get(cid)
        return c.axis if c else None

    def is_vertical(self, cid: str) -> bool:
        return self.axis(cid) == "vertical"

    def short(self, cid: str) -> str:
        c = self.classes.get(cid)
        return c.short if c else cid

    def rank(self, cid: str) -> int:
        """Display order: the file's order."""
        return self._rank.get(cid, len(self._rank))

    # ------------------------------------------------------------------ lint

    def lint(self, jurisdictions: set[str]) -> list[str]:
        errs = list(self.errors)
        where = "reservation.toml"
        literal: dict[tuple[str, str], str] = {}
        for item in self.data.get("class", []):
            cid = item.get("id", "")
            j = item.get("jurisdictions")
            if not item.get("aliases") and not item.get("codes"):
                errs.append(f"{where}: class {cid!r} has no aliases or codes")
            if item.get("axis") not in AXES:
                errs.append(f"{where}: class {cid!r}: axis={item.get('axis')!r} not one of {AXES}")
            m = _STATE_ID.match(cid)
            if j:
                for x in j:
                    if x not in jurisdictions:
                        errs.append(f"{where}: class {cid!r}: unknown jurisdiction {x!r}")
                if not m or m.group(1) not in j:
                    errs.append(f"{where}: class {cid!r}: a state class id is '<jurisdiction>:<short>'")
                if item.get("verified", True) and not item.get("source"):
                    errs.append(f"{where}: class {cid!r}: needs a `source`, or `verified = false`")
            elif m:
                errs.append(f"{where}: class {cid!r}: a national class id has no jurisdiction prefix")
            fam = item.get("family")
            if fam is not None:
                target = self.classes.get(fam)
                if target is None or target.jurisdictions is not None:
                    errs.append(f"{where}: class {cid!r}: family {fam!r} is not a national class")
            src = item.get("source")
            if src is not None and not URL_RE.match(src):
                errs.append(f"{where}: class {cid!r}: source is not an http(s) URL")
            # The same spelling claimed twice in one scope is a defect: which
            # class a notice meant would depend on file order.
            for p in item.get("aliases", []) + item.get("codes", []):
                for scope in j or ["*"]:
                    key = (scope, p.lower())
                    if key in literal and literal[key] != cid:
                        errs.append(f"{where}: pattern {p!r} is claimed by both {literal[key]!r} and {cid!r}")
                    literal[key] = cid
        for item in self.data.get("alias", []):
            to = item.get("to")
            if to not in self.classes:
                errs.append(f"{where}: alias for unknown class {to!r}")
            for x in item.get("jurisdictions", []):
                if x not in jurisdictions:
                    errs.append(f"{where}: alias for {to!r}: unknown jurisdiction {x!r}")
        for dep in self.data.get("deprecated", {}):
            if dep in self.classes:
                errs.append(f"{where}: {dep!r} is both a class and deprecated")
        return errs


@lru_cache(maxsize=4)
def load(directory: Path = CATALOGUE_DIR) -> Vocabulary:
    return Vocabulary(tomllib.loads((directory / "reservation.toml").read_text("utf-8")))
