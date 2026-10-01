"""The exam record template (docs/exam-template.md) as a checkable shape.

The template's TOML block is the one source of truth. From it this module
derives, per table path:
  * required keys: present in every instance of that table in the template
  * allowed keys: present in any instance
  * value kinds: the types each key takes in the template
  * allowed words: the 'a' | 'b' lists in the template's comments
and checks a record against them.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TEMPLATE_DOC = Path(__file__).resolve().parents[2] / "docs" / "exam-template.md"

#: Hugo's own front-matter keys a record may carry: `aliases` are the old URLs of
#: records merged into this one (dedupe.py), served as redirects.
HUGO_KEYS = frozenset({"aliases"})

#: Words any field may take in place of a value (the template's sentinels).
SENTINELS = frozenset({"none", "unknown", "not_announced", "all"})

#: Keys of a date window; a window's dates are present only once known.
WINDOW_KEYS = ("from", "to", "status", "change", "changed_from")
WINDOW_REQUIRED = frozenset({"status", "change", "changed_from"})

# Scalar kinds, for comparing a record value with the template's.
def kind(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, (dt.date, dt.datetime)):
        return "date"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "rows" if v and all(isinstance(x, dict) for x in v) else "list"
    if isinstance(v, dict):
        return "table"
    return type(v).__name__


def is_window(d: dict) -> bool:
    return WINDOW_REQUIRED <= d.keys() and set(d) <= set(WINDOW_KEYS)


def is_open_map(d: dict) -> bool:
    """A table keyed by data, not by field names (by_category: Unreserved, OBC-NCL...)."""
    return bool(d) and all(not re.fullmatch(r"[a-z][a-z0-9_]*", k) for k in d)


@dataclass
class Shape:
    required: dict[str, set[str]] = field(default_factory=dict)   # path -> keys
    allowed: dict[str, set[str]] = field(default_factory=dict)    # path -> keys
    kinds: dict[str, set[str]] = field(default_factory=dict)      # path.key -> kinds
    words: dict[str, set[str]] = field(default_factory=dict)      # key -> allowed words
    alts: dict[str, set[str]] = field(default_factory=dict)       # key -> words allowed in place of a value
    lists: set[str] = field(default_factory=set)                  # keys whose comment allows a list


def template_text(doc: Path = TEMPLATE_DOC) -> str:
    text = doc.read_text(encoding="utf-8")
    m = re.search(r"## Template\n.*?```toml\n\+\+\+\n(.*?)\+\+\+\n```", text, re.S)
    if not m:
        raise ValueError(f"no ```toml template block under '## Template' in {doc}")
    return m.group(1)


@lru_cache(maxsize=1)
def shape(doc: Path = TEMPLATE_DOC) -> Shape:
    src = template_text(doc)
    data = tomllib.loads(src)
    sh = Shape()

    def walk(d: dict, path: str) -> None:
        if is_window(d) or is_open_map(d):
            return
        keys = set(d)
        sh.required[path] = sh.required[path] & keys if path in sh.required else keys
        sh.allowed.setdefault(path, set()).update(keys)
        for k, v in d.items():
            sub = f"{path}.{k}" if path else k
            sh.kinds.setdefault(sub, set()).add("sentinel" if isinstance(v, str) and v in SENTINELS else kind(v))
            if isinstance(v, dict):
                walk(v, sub)
            elif kind(v) == "rows":
                for row in v:
                    walk(row, sub)

    walk(data, "")
    # 'a' | 'b' lists, including continuation lines that start with "# |"
    joined = re.sub(r"\n\s*#\s*(?=\|)", " ", src)
    for key, alts in re.findall(r"^\s*([A-Za-z_]+)\s*=.*?#\s*('[^']+'(?:\s*\|\s*'[^']+')+)", joined, re.M):
        words = re.findall(r"'([^']+)'", alts)
        # a format such as '+N, max M' describes values rather than listing them
        if any(re.search(r"\b[NM]\b|<", w) for w in words):
            continue
        sh.words.setdefault(key, set()).update(words)
    # comments also name words that may replace a value ("or 'as_evaluated'")
    # and say when a list may replace one ("or ['City', ...]")
    for key, com in re.findall(r"^\s*\[?([A-Za-z_.]+)\]?\s*(?:=[^#\n]*)?#([^\n]*)", joined, re.M):
        key = key.rsplit(".", 1)[-1]
        sh.alts.setdefault(key, set()).update(re.findall(r"'([a-z_]+)'", com))
        if "[" in com:
            sh.lists.add(key)
    # window words come from the comment above [dates], not a key line
    for key in ("status", "change"):
        m = re.search(rf"^# {key}:\s*(.+)$", src, re.M)
        if m:
            sh.words[key] = set(re.findall(r"'([^']+)'", m.group(1).split(";")[0]))
    return sh


@dataclass
class Problem:
    level: str   # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def check(record: dict, sh: Shape | None = None) -> list[Problem]:
    """Every way a record departs from the template."""
    sh = sh or shape()
    out: list[Problem] = []

    def word_ok(key: str, v: Any) -> bool:
        allowed = sh.words.get(key)
        if not allowed or not isinstance(v, str):
            return True
        return v in allowed or v in SENTINELS

    def value(key: str, path: str, v: Any, where: str) -> None:
        want = sh.kinds.get(path)
        got = kind(v)
        # a key the template shows only as a sentinel may take any value
        if want == {"sentinel"} or (isinstance(v, str) and (v in SENTINELS or v in sh.alts.get(key, ()))):
            want = None
        elif got == "list" and key in sh.lists:
            want = None
        elif want:
            want = want - {"sentinel"}
        if want and got not in want:
            # a list may stand where rows are expected when empty; 'rows' may replace a sentinel
            if not ({got, *want} <= {"list", "rows"}) and not (got == "rows" and "text" in want):
                out.append(Problem("error", where, f"{got} where the template has {'/'.join(sorted(want))}"))
        if isinstance(v, list) and not isinstance(v, dict):
            for x in v:
                if isinstance(x, str) and not word_ok(key, x):
                    out.append(Problem("error", where, f"{x!r} is not one of {sorted(sh.words[key])}"))
        elif not word_ok(key, v):
            out.append(Problem("error", where, f"{v!r} is not one of {sorted(sh.words[key])}"))

    def window(d: dict, where: str) -> None:
        for k in WINDOW_REQUIRED - d.keys():
            out.append(Problem("error", where, f"missing {k}"))
        for k in set(d) - set(WINDOW_KEYS):
            out.append(Problem("warning", where, f"extra key {k}"))
        if ("from" in d) != ("to" in d):
            out.append(Problem("error", where, "has only one of from/to"))
        for k in ("from", "to"):
            if k in d and not isinstance(d[k], (dt.date, str)):
                out.append(Problem("error", f"{where}.{k}", f"{kind(d[k])} is not a date"))
        for k in ("status", "change"):
            if k in d and not word_ok(k, d[k]):
                out.append(Problem("error", f"{where}.{k}", f"{d[k]!r} is not one of {sorted(sh.words[k])}"))

    def walk(d: dict, path: str, where: str) -> None:
        if path not in sh.allowed:
            # rows the template shows only as a comment have no shape to check
            if not is_window(d) and not is_open_map(d) and sh.kinds.get(path) != {"sentinel"}:
                out.append(Problem("warning", where or "record", "table not in the template"))
            return
        for k in sorted(sh.required[path] - d.keys()):
            out.append(Problem("error", where or "record", f"missing {k}"))
        for k in sorted(set(d) - sh.allowed[path] - (HUGO_KEYS if not path else set())):
            out.append(Problem("warning", where or "record", f"extra key {k}"))
        for k, v in d.items():
            sub = f"{path}.{k}" if path else k
            loc = f"{where}.{k}" if where else k
            if isinstance(v, dict):
                if "window" in sh.kinds.get(sub, set()) or is_window(v) or WINDOW_REQUIRED & v.keys():
                    window(v, loc)
                elif not is_open_map(v):
                    walk(v, sub, loc)
            elif isinstance(v, str) and "table" in sh.kinds.get(sub, set()):
                if v not in SENTINELS and v not in sh.alts.get(k, ()):
                    out.append(Problem("error", loc, f"{v!r} where the template has a table"))
            elif kind(v) == "rows":
                value(k, sub, v, loc)
                for i, row in enumerate(v):
                    walk(row, sub, f"{loc}[{i}]")
            else:
                value(k, sub, v, loc)

    walk(record, "", "")
    return out
