"""One exam in two files: merge them when nothing is lost.

Two records are the same exam when they get the same short name (names.py)
and nothing in their slugs tells them apart, in the same cycle year. They
were harvested under two groups (``d5-cat-2026`` and ``mgt-cat-2026``).

The merge keeps every fact:

* a value one side knows and the other marks ``unknown`` / ``not_announced`` is kept;
* evidence and documents are unioned; a list one side extends is taken whole;
* the other file's official name joins ``title_aliases``;
* the other file's URL redirects to the kept one (Hugo ``aliases``).

When the two disagree on a fact (two different closing dates, say) nothing is
merged and the conflict is reported: the pipeline can't tell which is right.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from . import catalogue as catalogue_mod
from . import names as names_mod
from . import record as record_mod

#: stands for "not known yet", so a known value replaces it
_FILLABLE = {"unknown", "not_announced", ""}
#: lists whose items only add to each other (sources, files)
_ADDITIVE = {"provenance.evidence", "links.documents"}
#: lists of items with an identity key, merged item by item
_KEYED = {"dates.stages": "stage_number", "bodies": "body"}
#: an item that only holds the template's placeholder, given way to real items
_PLACEHOLDER = {"fee.rows": lambda x: x.get("fee_rupees") in _FILLABLE}  # True: placeholder
#: a value and the narrower one it includes: OMR is a pen-and-paper test
_NARROWER = {("pen_paper", "omr")}
_LATEST = {"provenance.provenance_retrieved", "provenance.provenance_last_checked"}


class Conflict(ValueError):
    pass


@dataclass
class Result:
    merged: dict[str, str] = field(default_factory=dict)          # removed file -> kept file
    conflicts: dict[tuple[str, ...], list[str]] = field(default_factory=dict)


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v in _FILLABLE) or v == [] or v == {}


def _merge(a: Any, b: Any, where: str) -> Any:
    if a == b:
        return a
    if _blank(b):
        return a
    if _blank(a):
        return b
    if where in _LATEST:
        return max(str(a), str(b))
    if isinstance(a, str) and isinstance(b, str):
        if (a, b) in _NARROWER or (b, a) in _NARROWER:
            return b if (a, b) in _NARROWER else a
        if a.startswith("http") and b.startswith("http") and (inner := _deeper_url(a, b)):
            return inner
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: _merge(a.get(k), b.get(k), f"{where}.{k}" if where else k)
                for k in [*a, *(k for k in b if k not in a)]}
    if isinstance(a, list) and isinstance(b, list):
        if where in _PLACEHOLDER:
            empty = _PLACEHOLDER[where]
            if all(empty(x) for x in a):
                return b
            if all(empty(x) for x in b):
                return a
        if where in _ADDITIVE:
            return a + [x for x in b if x not in a]
        if where in _KEYED:
            key = _KEYED[where]
            by = {x.get(key): x for x in a}
            for x in b:
                by[x.get(key)] = _merge(by[x.get(key)], x, where) if x.get(key) in by else x
            return list(by.values())
        if all(x in a for x in b):
            return a
        if all(x in b for x in a):
            return b
    if isinstance(a, list) and b == "none" or a == "none" and isinstance(b, list):
        return a if isinstance(a, list) else b
    raise Conflict(f"{where}: {_short(a)} / {_short(b)}")


def _deeper_url(a: str, b: str) -> str | None:
    """Of two links on one site, the one inside the other's folder (the site root and its
    register page): it says all the other does, and more."""
    pa, pb = urlsplit(a), urlsplit(b)
    if pa.hostname != pb.hostname:
        return None
    ra, rb = pa.path or "/", pb.path or "/"
    if ra.endswith("/") and rb.startswith(ra) and rb != ra:
        return b
    if rb.endswith("/") and ra.startswith(rb) and ra != rb:
        return a
    return None


def _short(v: Any) -> str:
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


def merge(keep: dict, other: dict) -> dict:
    """``keep`` with every fact of ``other``; raises Conflict on a disagreement."""
    a, b = dict(keep), dict(other)
    # names: the kept file's stay; the other's official name becomes an alias
    for k in ("slug", "title", "title_official", "aliases"):
        b.pop(k, None)
    names = [n for n in (a.get("title_aliases"), other.get("title_aliases")) if isinstance(n, list)]
    aliases = [x for n in names for x in n]
    for name in (other.get("title_official"), other.get("title")):
        if name and name not in (keep.get("title_official"), keep.get("title")):
            aliases.append(name)
    a.pop("title_aliases", None); b.pop("title_aliases", None)
    merged = _merge(a, b, "")
    # the removed page's URL, and any it already redirected from
    moved = [f"/exams/{other['slug']}/"] + [x for x in (other.get("aliases") or []) if isinstance(x, str)]
    extra = {"title_aliases": list(dict.fromkeys(aliases)) or keep.get("title_aliases", "none"),
             "aliases": list(dict.fromkeys([*(keep.get("aliases") or []), *moved]))}
    # the kept file's key order, the redirects just after the aliases
    out = {}
    for k in [*keep, *(k for k in merged if k not in keep)]:
        if k in extra:
            out[k] = extra.pop(k)
            if k == "title_aliases":
                out["aliases"] = extra.pop("aliases")
        elif k in merged:
            out[k] = merged[k]
    out.update(extra)
    return out


def _leaves(v: Any, where: str = "") -> list[tuple[str, str]]:
    """Every single value with its path; list items one by one."""
    if isinstance(v, dict):
        return [x for k, item in v.items() for x in _leaves(item, f"{where}.{k}" if where else k)]
    if isinstance(v, list):
        return [x for item in v for x in _leaves(item, where)]
    return [(where, v.isoformat() if hasattr(v, "isoformat") else str(v))]


def lost(merged: dict, source: dict) -> list[str]:
    """Facts in ``source`` the merge doesn't carry; empty when the merge lost nothing.
    Compared as values, since a fact may move (the official name into the aliases)."""
    have = {v for _, v in _leaves(merged)}
    gone = []
    for where, v in _leaves(source):
        if v in _FILLABLE or v in have or where == "slug":
            continue
        # a narrower value or a deeper link on the same site says the same and more
        if any((v, h) in _NARROWER for h in have):
            continue
        if v.startswith("http") and any(h.startswith("http") and _deeper_url(v, h) == h for h in have):
            continue
        # a placeholder fee row given way to real ones
        if where.startswith("fee.rows.") and all(
                _PLACEHOLDER["fee.rows"](x) for x in (source.get("fee") or {}).get("rows", [])):
            continue
        gone.append(f"{where} = {v!r}")
    return gone


def _year(cycle: Any) -> str:
    m = re.match(r"\d{4}", str(cycle))
    return m.group(0) if m else str(cycle)


def _known(rec: dict) -> int:
    """How many facts a record states; the fuller file is kept."""
    return sum(1 for v in record_mod.flatten(rec).values() if v not in _FILLABLE and v != "none")


def groups(recs: dict[str, dict], cat) -> list[list[str]]:
    """Files that are one exam: the same short name, nothing in their slugs that tells them
    apart ("Session 1" / "Session 2" do), the same cycle year, and no two catalogue exams."""
    by: dict[str, list[str]] = {}
    for name, r in recs.items():
        short, _ = names_mod.short_title(r, cat)
        if short:
            by.setdefault(short.lower(), []).append(name)
    out = []
    for group in (g for g in by.values() if len(g) > 1):
        words = {n: names_mod._slug_words(recs[n].get("slug") or n[:-3], names_mod.short_title(recs[n], cat)[0], cat)
                 for n in group}
        plain = [n for n in group if not names_mod._distinct(words[n], [set(words[o]) for o in group if o != n])]
        for year in {_year(recs[n].get("cycle")) for n in plain}:
            same = [n for n in plain if _year(recs[n].get("cycle")) == year]
            exams = {recs[n].get("exam_id") for n in same} - {"unknown", None, ""}
            if len(same) > 1 and len(exams) <= 1:
                out.append(sorted(same))
    return sorted(out)


#: words that name one part of an exam; a record whose name is a family's name plus only
#: these is one of its parts ("CLAT 2027 — Undergraduate Programme")
_VARIANT = {"ug", "pg", "undergraduate", "postgraduate", "programme", "program", "programmes", "course",
            "courses", "session", "paper", "prelims", "preliminary", "mains", "main", "phase", "stage",
            "part", "tier", "i", "ii", "iii", "iv", "1", "2", "3", "4", "exam", "examination"}


def _name_words(rec: dict) -> list[str]:
    text = re.sub(r"(?<!\d)(19|20)\d{2}(-\d{2,4})?(?!\d)", " ", str(rec.get("title_official", "")).lower())
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


def _conductor(rec: dict) -> str | None:
    return next((b.get("body") for b in rec.get("bodies") or [] if isinstance(b, dict) and b.get("body_role") == "conducts"), None)


def families(recs: dict[str, dict]) -> list[tuple[str, list[str]]]:
    """(combined record, its parts): a record named only for the family, and two or more
    records of the same body and year named for the family plus a part (UG, PG, Session 1)."""
    out = []
    for name, rec in recs.items():
        family = _name_words(rec)
        if len(family) < 2 or set(family) & _VARIANT - {"exam", "examination"}:
            continue
        initials = "".join(w[0] for w in family)
        parts = []
        for other, r in recs.items():
            if other == name or _year(r.get("cycle")) != _year(rec.get("cycle")):
                continue
            if _conductor(rec) and _conductor(r) != _conductor(rec):
                continue
            words = _name_words(r)
            if words[: len(family)] != family:
                continue
            extra = [w for w in words[len(family):] if w != initials]
            if extra and all(w in _VARIANT for w in extra):
                parts.append((other, tuple(extra)))
        if len(parts) >= 2 and len({e for _, e in parts}) == len(parts):
            out.append((name, sorted(p for p, _ in parts)))
    return out


def run(exams_dir: Path, *, apply: bool = False, log: Callable[[str], None] = print) -> Result:
    out = Result()
    loaded = {p.name: record_mod.load(p) for p in sorted(exams_dir.glob("*.md"))}
    recs = {k: v[0] for k, v in loaded.items()}
    for group in groups(recs, catalogue_mod.load()):
        # the fullest file is kept; a tie keeps the first name
        order = sorted(group, key=lambda n: (-_known(recs[n]), n))
        keep, rest = order[0], order[1:]
        merged = recs[keep]
        try:
            for other in rest:
                merged = merge(merged, recs[other])
            missing = [x for n in group for x in lost(merged, recs[n])]
            if missing:
                raise Conflict(f"a merge would lose {missing[0]}" + (f" and {len(missing) - 1} more" if len(missing) > 1 else ""))
        except Conflict as exc:
            out.conflicts[tuple(group)] = [str(exc)]
            log(f"dedupe: {', '.join(group)}: left apart, they disagree on {exc}")
            continue
        for other in rest:
            out.merged[other] = keep
            log(f"dedupe: {other} merged into {keep}")
        if apply:
            body = loaded[keep][1] or next((loaded[o][1] for o in rest if loaded[o][1]), "")
            (exams_dir / keep).write_text(record_mod.dumps(merged, body), encoding="utf-8")
            for other in rest:
                (exams_dir / other).unlink()
    # a combined record folded into each of its parts, when each takes every fact
    live = {n: r for n, r in recs.items() if n not in out.merged}
    for whole, parts in families(live):
        try:
            folded = {}
            for part in parts:
                folded[part] = merge(live[part], live[whole])
                missing = lost(folded[part], live[whole]) + lost(folded[part], live[part])
                if missing:
                    raise Conflict(f"a merge would lose {missing[0]}")
        except Conflict as exc:
            out.conflicts[(whole, *parts)] = [str(exc)]
            log(f"dedupe: {whole} left apart from its parts {', '.join(parts)}: {exc}")
            continue
        out.merged[whole] = parts[0]
        log(f"dedupe: {whole} folded into its parts {', '.join(parts)} (its URL redirects to {parts[0]})")
        if apply:
            for i, part in enumerate(parts):
                rec = folded[part]
                if i:  # one page can take the old URL's redirect
                    rec["aliases"] = [a for a in rec["aliases"] if a != f"/exams/{live[whole]['slug']}/"] or live[part].get("aliases", [])
                    if not rec["aliases"]:
                        rec.pop("aliases")
                (exams_dir / part).write_text(record_mod.dumps(rec, loaded[part][1]), encoding="utf-8")
            (exams_dir / whole).unlink()
    log(f"dedupe: {len(out.merged)} merged, {len(out.conflicts)} group(s) left apart"
        + ("" if apply else " (dry run)"))
    return out
