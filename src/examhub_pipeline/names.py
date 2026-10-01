"""Short titles for exam records (decision 3: ``title`` is the short name + cycle).

A record whose ``title`` is still the notice's own name (``title == title_official``)
gets a short one on every run, from the best source it has:

1. the catalogue's short name for the exam, when it names this exam and not an umbrella;
2. the record's first curated alias (``title_aliases``);
3. the body's short name and the post, with the notice's filler taken out.

The cycle goes on the end. A title set by hand (anything other than the official
name) is never touched. What can't be made short enough is left as it is and reported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import catalogue as catalogue_mod
from . import record as record_mod

# a short title longer than this is no better than the official name
MAX_LEN = 48
# a catalogue short name or alias this long is a description, not a name
MAX_SOURCE_LEN = 32

# words that mark an umbrella entry or a description rather than one exam's name
_GENERIC = re.compile(r"\b(recruitment|umbrella|other|others|staff|conducted)\b|\s/\s", re.I)
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?:-\d{2,4})?(?!\d)")

# notice filler, removed in this order (fallback 3 only)
_FILLER = [
    r"\bAdvertisement No\.?.*$",
    r"\(Notification No\.?[^)]*\)",
    r"\b(?:Cycle-\d+\s+)?Rolling Advertisement\b",
    r"\bDirect Recruitment to (?:the )?Posts? of\b",
    r"\bRecruitment to (?:the )?Posts? of\b",
    r"\bDirect Recruitment to\b",
    r"\bRecruitment of\b",
    r"\b(?:the )?Posts? of\b",
    r"\bEngagement of\b",
    r"\bOnline Engagement\b",
    r"\bDirect\b",
    r"\bWritten\b",
    r"\bon Contract Basis\b",
    r"\b(?:Written )?Recruitment Examination\b",
    r"\bCompetitive Examination\b",
    r"\bExamination\b",
    r"\bRecruitment\b",
    r"\b(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)[- ]?(?:(?:19|20)\d{2})?\s*(?:Term|Session|Cycle)?\b",
    r"\b(?:Term|Session)\b",
]
_SMALL = {"and", "of", "the", "for", "in", "to", "on", "at", "&"}


@dataclass
class Result:
    """What one run did: new titles, and what it couldn't name."""
    renamed: dict[str, tuple[str, str, str]] = field(default_factory=dict)  # file -> (old, new, source)
    skipped: dict[str, str] = field(default_factory=dict)                   # file -> reason
    kept: int = 0                                                           # already named by hand
    duplicates: list[tuple[str, ...]] = field(default_factory=list)          # files that look like one exam


def _generic(name: str) -> bool:
    return not name or len(name) > MAX_SOURCE_LEN or bool(_GENERIC.search(name))


def _collapse_acronyms(text: str) -> str:
    """'Cost and Management Accountant (CMA) Final' -> 'CMA Final'."""
    def repl(m: re.Match) -> str:
        acr = m.group(2)
        letters = re.sub(r"[^A-Z]", "", acr)
        if len(letters) < 2:
            return m.group(0)
        words = m.group(1).split()
        # the shortest run of words just before the bracket whose initials spell the acronym
        for i in range(len(words)):
            run = [w for w in words[i:] if w.lower() not in _SMALL]
            if "".join(w[0] for w in run if w[:1].isalpha()).upper() == letters:
                return " ".join(words[:i] + [acr])
        return m.group(0)
    return re.sub(r"((?:[\w’'-]+\s+){1,8}?)\(([A-Z][A-Za-z0-9-]{1,11})\)", repl, text)


def _tidy(text: str) -> str:
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+([,:;)])", r"\1", text)
    text = re.sub(r"([,:;])(?=[,:;])", "", text)
    text = re.sub(r"\s*,\s*(?=,|$)", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    # a bracket the cutting left open goes, with what follows it
    if text.count("(") > text.count(")"):
        text = text[: text.rfind("(")]
    # "Punjab Police Police Constable": a word said twice in a row once
    text = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", text, flags=re.I)
    return text.strip(" ,;:-–/")


# ways to shorten a post name that is still too long, gentlest first
_SHORTER = [
    lambda t: re.sub(r"\([^)]*\)", "", t),        # the brackets
    lambda t: t.split(",")[0],                     # everything after the first comma
    lambda t: re.split(r"\s(?:in|for|under|through|at|of)\s(?:the\s)?(?=[A-Z])", t)[0],  # "... in Punjab Police"
    lambda t: re.split(r"\s(?:and|&)\s|\s/\s|/", t)[0],   # the first of several posts
]


def _from_notice(official: str, body_short: str, body_name: str, place: str = "") -> str:
    """Fallback 3: the body's short name and the post, the notice's filler taken out."""
    t = _YEAR.sub("", official)
    for name in sorted({body_short, body_name} - {""}, key=len, reverse=True):
        # the body named inside the title goes; its short name leads instead
        t = re.sub(r"[,(]?\s*" + re.escape(name) + r"\s*\)?", " ", t, flags=re.I)
    if body_short and place:
        # "TPSC Tripura Medical Officer": the body already says where
        t = re.sub(r"(?:,\s*)?\b" + re.escape(place) + r"\b", " ", t)
    for pat in _FILLER:
        t = re.sub(pat, " ", t, flags=re.I)
    t = _tidy(_collapse_acronyms(_tidy(t)))
    room = MAX_LEN - len(body_short) - 9          # the body, a space, and a cycle like " 2026-27"
    for cut in _SHORTER:
        if len(t) <= room:
            break
        t = _tidy(cut(t)) or t
    return _tidy(f"{body_short} {t}" if body_short else t)


_MONTHS = {m.lower() for m in "January February March April May June July August September October "
           "November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec".split()}


def _slug_words(slug: str, title: str, cat: catalogue_mod.Catalogue) -> list[str]:
    """Slug words that can tell sibling records apart: not the group code, a year, a month,
    a body's id, or a word already in the title."""
    have = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", title)}
    bodies = {p for b in cat.bodies for p in b.lower().split("-")}
    bodies |= {w.lower() for j in cat.jurisdictions.values() for w in re.findall(r"[A-Za-z]+", j.get("name") or "")}
    words = slug.split("-")[1:]
    return [w for w in words
            if w not in have and w not in _MONTHS and w not in bodies and not re.fullmatch(r"(19|20)\d{2}", w)]


_PLAIN = {"and", "of", "the", "for", "in", "to", "on", "at", "cum", "set", "new", "old", "law", "art", "arts"}


def _word(w: str) -> str:
    """A slug word as it should read: 'session' -> 'Session', 'jpa' -> 'JPA', '22nd' stays."""
    if w[:1].isdigit():
        return w
    if len(w) <= 3 and w not in _PLAIN:
        return w.upper()
    return w.capitalize()


def _distinct(mine: list[str], others: list[set[str]]) -> list[str]:
    """My slug words the others lack, each with the word before it when every record shares
    that one ('session 1' against 'session 2')."""
    shared = set.intersection(*others) if others else set()
    missing = set().union(*others) if others else set()
    out: list[str] = []
    for i, w in enumerate(mine):
        if w in missing:
            continue
        if i and mine[i - 1] in shared and mine[i - 1] not in out:
            out.append(mine[i - 1])
        out.append(w)
    return out


def _cycle_label(cycle: str, official: str) -> str:
    """'2026', or '2026-27' for a span of two years; odd labels ('2026-22') fall back to the year."""
    for text in (cycle, official):
        m = re.search(r"(?<!\d)((?:19|20)\d{2})(?:-(\d{2}|\d{4}))?(?!\d)", text or "")
        if m:
            y, nxt = m.group(1), m.group(2)
            if nxt and int(nxt[-2:]) == (int(y) + 1) % 100:
                return f"{y}-{nxt[-2:]}"
            return y
    return ""


def _with_cycle(base: str, cycle: str, official: str) -> str:
    if _YEAR.search(base):
        return base
    label = _cycle_label(cycle, official)
    return f"{base} {label}" if label else base


def short_title(rec: dict, cat: catalogue_mod.Catalogue) -> tuple[str, str]:
    """``(title, source)`` for one record; the title is '' when nothing short enough exists."""
    official = rec.get("title_official") or rec.get("title") or ""
    cycle = str(rec.get("cycle") or "")
    exam = cat.exams.get(rec.get("exam_id") or "", {})
    body_id = ((rec.get("bodies") or [{}])[0] or {}).get("body") or ""
    body = cat.bodies.get(body_id, {})
    aliases = rec.get("title_aliases") if isinstance(rec.get("title_aliases"), list) else []

    tries = [(exam.get("short_name") or "", "catalogue")]
    tries += [(a, "alias") for a in aliases[:1]]
    for base, source in tries:
        if not _generic(base):
            return _with_cycle(base, cycle, official), source
    place = cat.jurisdictions.get(body.get("jurisdiction") or "", {}).get("name") or ""
    base = _from_notice(official, body.get("short_name") or "", body.get("name") or "", place)
    title = _with_cycle(base, cycle, official)
    return (title, "notice") if 0 < len(title) <= MAX_LEN and _whole(title) else ("", "notice")


def _whole(title: str) -> bool:
    """False for a name the cutting broke: '( Batch)', a dangling comma or colon."""
    return not re.search(r"\(\s|\s\)|[,:;(]\s*(?:(?:19|20)\d{2}(?:-\d{2})?)?$", title)


def fill(exams_dir: Path, *, apply: bool = False, log=print) -> Result:
    """Give every record still titled with its official name a short title."""
    cat = catalogue_mod.load()
    out = Result()
    plans: dict[str, tuple[Path, dict, str, str, str]] = {}
    for path in sorted(Path(exams_dir).glob("*.md")):
        try:
            rec, body = record_mod.load(path)
        except (OSError, ValueError) as exc:
            out.skipped[path.name] = f"unreadable: {exc}"
            log(f"names: {path.name}: skipped, unreadable ({exc})")
            continue
        if rec.get("title") != rec.get("title_official"):
            out.kept += 1
            continue
        new, source = short_title(rec, cat)
        if not new:
            out.skipped[path.name] = f"no short title within {MAX_LEN} characters"
            log(f"names: {path.name}: left as is, nothing short enough ({rec.get('title')!r})")
            continue
        if new == rec.get("title"):
            continue
        plans[path.name] = (path, rec, body, new, source)

    # records sharing a short title: each takes the words its slug has and the others don't
    # ("JEE Main Session 1 2027"); records nothing tells apart are duplicates, reported
    seen: dict[str, list[str]] = {}
    for name, (_, _, _, new, _) in plans.items():
        seen.setdefault(new.lower(), []).append(name)
    for names in (n for n in seen.values() if len(n) > 1):
        words = {n: _slug_words(plans[n][1].get("slug") or n[:-3], plans[n][3], cat) for n in names}
        extras = {}
        for name in names:
            others = [set(words[o]) for o in names if o != name]
            extras[name] = _distinct(words[name], others)
        plain = [n for n in names if not extras[n]]
        # one record the slugs can't tell from the rest: the whole set may be one exam twice
        suspects = set(plain) | (set(names) if len(plain) == 1 else set())
        if len(suspects) > 1:
            out.duplicates.append(tuple(sorted(suspects)))
        for name in names:
            path, rec, body, new, source = plans[name]
            label = _cycle_label(str(rec.get("cycle") or ""), rec.get("title_official") or "")
            base = new[: -len(label)].strip() if label and new.endswith(label) else new
            better = _tidy(f"{base} {' '.join(_word(w) for w in extras[name])} {label}")
            if name not in suspects and len(better) <= MAX_LEN:
                plans[name] = (path, rec, body, better, source)
                continue
            why = (f"looks like the same exam as {', '.join(sorted(suspects - {name}))}" if name in suspects and len(suspects) > 1
                   else f"short title {new!r} clashes with {', '.join(x for x in names if x != name)}")
            out.skipped[name] = why
            log(f"names: {name}: left as is, {why}")
            del plans[name]

    for name, (path, rec, body, new, source) in plans.items():
        out.renamed[name] = (rec["title"], new, source)
        log(f"names: {name}: {rec['title']!r} -> {new!r} (from the {source})")
        if apply:
            rec["title"] = new
            path.write_text(record_mod.dumps(rec, body), encoding="utf-8")
    log(f"names: {len(out.renamed)} renamed, {out.kept} already named, {len(out.skipped)} left as is"
        + ("" if apply else " (dry run)"))
    return out
