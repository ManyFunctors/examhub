"""New-exam discovery: what the harvest says the catalogue is missing.

    python -m examhub_pipeline catalogue discover      # writes the two worklists
    python -m examhub_pipeline catalogue adopt exam:in-nta:nittt

Offline and deterministic: it reads ``data/harvest/notices.jsonl`` and the
catalogue, and nothing else. Two kinds of proposal come out of it:

``match-proposals.jsonl``
    An unmatched notice whose title carries every distinctive word of an
    existing exam's name ("Common University Entrance Test" for CUET) means
    that exam's patterns are too narrow. The proposal is one more
    ``match.any`` pattern, with the notices it would claim.

``exam-proposals.jsonl``
    A series name that recurs in a body's unmatched notices ("NITTT
    Examination", "AEIAT-2026", "Recruitment to the post of Boiler
    Inspector") and that no exam of that body matches. The proposal is a
    complete catalogue entry -- id, name, purpose, match pattern -- plus the
    notices that are its evidence and a score. ``catalogue adopt <id>``
    merges it through the same lint-gated path as a hand edit.

A proposal is never adopted automatically. A person reads the evidence; a
pull request carries the change. Proposals a person has rejected are listed
in ``data/catalogue/discovery-ignore.toml`` and never come back.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .catalogue import CATALOGUE_DIR, Catalogue, Matcher, _phrase

IGNORE_FILE = CATALOGUE_DIR / "discovery-ignore.toml"

# --------------------------------------------------------------------------
# Series names in a title
# --------------------------------------------------------------------------

#: What makes a phrase a series: the word that ends it.
_HEAD = (r"(?:(?:competitive|combined|common|main|mains|preliminary|prelims?)\s+)?"
         r"(?:examinations?|exams?|entrance\s+(?:test|exam(?:ination)?)|eligibility\s+test|"
         r"admission\s+test|selection\s+test|aptitude\s+test|recruitment\s+test|cet)")
_BEFORE_HEAD = re.compile(
    rf"(?P<name>(?:[A-Za-z][A-Za-z.&'/\-]*\s+){{0,7}}[A-Za-z][A-Za-z.&'/\-]*)\s*(?:\([^)]{{0,30}}\)\s*)?[\s\-–]*(?P<head>{_HEAD})\b",
    re.I)
_POST_OF = re.compile(
    r"\b(?:recruitment|selection|appointment)\s+(?:to|for|of)\s+(?:the\s+)?posts?\s+of\s+"
    r"(?P<name>[A-Za-z][A-Za-z.&'/\- ]{2,80}?)(?=\s*(?:[,(:;\-–]|\bin\b|\bunder\b|\bfor\b|\bat\b|\badvt|\badvertisement|\b20\d\d\b|$))",
    re.I)
_ACRONYM_YEAR = re.compile(r"(?<![A-Za-z])(?P<name>[A-Z][A-Z0-9&]{2,11})[\s\-–_]*(?:\(?(?:20\d{2})\)?)(?![0-9])")

#: Words that start a title but are not part of the series name.
_LEAD = re.compile(
    r"^(?:(?:the|a|an|of|for|in|on|to|and|regarding|reg|re|about|notice|public|press|note|"
    r"notification|corrigendum|addendum|revised|modified|amended|final|provisional|tentative|"
    r"updated|result|results|marks|cut[\s-]*off|answer|model|keys?|admit|cards?|hall|tickets?|"
    r"schedule|programme|program|time[\s-]*table|date|dates|list|lists|candidates?|selected|"
    r"shortlisted|eligible|qualified|call|letters?|syllabus|scheme|pattern|declaration|release|"
    r"releasing|issue|issuance|extension|postponement|cancellation|advance|intimation|allotment|"
    r"city|information|instructions?|guidelines|application|apply|online|download|view|link|"
    r"new|latest|important|urgent|special|second|third|first|phase|stage|tier|paper|session|"
    r"round|batch|objection|challenge|re[\s-]*exam|re[\s-]*test|conduct|conducting|held|"
    r"proposed|written|document|verification|dv|interview|skill|typing|physical|medical|"
    r"departmental|half[\s-]*yearly|screening|mock|practice|modified|statement|marks|time[\s-]*slot|"
    r"slot|courses?|month|year|january|february|march|april|may|june|july|august|september|"
    r"october|november|december|in|by|with|from|under|score|scorecard|card|all|concerned|"
    r"officers|that|those|whose|who|which|these|its)\s+)+", re.I)

#: A name made only of these is not a series.
_GENERIC = set("""
written screening departmental proposed mock practice test exam examination examinations main
mains preliminary prelims competitive combined common special notice the entrance online offline
computer based cbt written-test re semester annual supplementary improvement compartment board
various posts post recruitment selection skill typing physical efficiency endurance medical
interview document verification half yearly the of for and new above said this following
january february march april may june july august september sept october november december
month year years session course courses statement marks slot time modified schedule result
""".split())

#: Acronyms that are never a series on their own.
_NOT_SERIES = set("""
JANUARY FEBRUARY MARCH APRIL JUNE JULY AUGUST SEPTEMBER SEPT OCTOBER NOVEMBER DECEMBER YEAR YEARS
SESSION COURSE COURSES CLASS STD MONTH ANNUAL NOTE DATED ONLY HINDI ENGLISH ACADEMIC WEEK
PDF THE AND FOR NOTICE PUBLIC PRESS NEW LIST RESULT RESULTS ANSWER KEY DATE ADMIT CARD FINAL
REVISED EXAM EXAMS TEST CBT OMR DV PET PST PMT UR OBC SC ST EWS PWD PWBD GEN IST JAN FEB MAR APR
MAY JUN JUL AUG SEP OCT NOV DEC FAQ FAQS RTI URL HTML ONLINE OFFLINE CEN ADVT SNO ITI NCC NSS
""".split())


_CONNECTOR = re.compile(r"^.*\b(?:for|in|regarding|reg\.?|about|towards|under|on)\s+", re.I)
_LEAD_PHRASE = re.compile(
    r"^(?:additions?/amendments?|form|responses?|score\s*card|inviting|tender|hiring|centre\s*change|"
    r"change|corrections?|correction\s*window|window|fee|payment|provisionally|pre[\s-]*employment)\b.*$", re.I)


def _norm(name: str) -> str:
    # "Inviting Online Applications for National Entrance Test" -> the
    # series is what follows the last connector. "of" is not a connector:
    # "Indian Institute of Technology" needs it.
    name = _CONNECTOR.sub("", name)
    if _LEAD_PHRASE.match(name.strip()):
        return ""
    name = re.sub(r"\b(?:19|20)\d{2}(?:\s*[-–/]\s*\d{2,4})?\b", " ", name)
    name = re.sub(r"[_]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .,-–:;/&'")
    prev = None
    while prev != name:
        prev = name
        name = _LEAD.sub("", name).strip(" .,-–:;/&'")
    return name


def _is_series(name: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z]+", name.lower())]
    if not words or all(w in _GENERIC for w in words):
        return False
    if len(words) == 1:
        return name.isupper() and len(name) >= 3 and name not in _NOT_SERIES
    return len(" ".join(words)) >= 6


def series_names(title: str) -> list[tuple[str, str]]:
    """``(name, head)`` pairs a title names, e.g. ``("NITTT", "examination")``.
    Latin script only: titles in Devanagari, Gujarati, Kannada ... are left
    to the maintainer (they are still in the worklist)."""
    t = re.sub(r"\s+", " ", title.replace("_", " "))
    out: list[tuple[str, str]] = []
    for m in _BEFORE_HEAD.finditer(t):
        head = re.sub(r"\s+", " ", m.group("head"))
        name = _norm(m.group("name"))
        if name and _is_series(name):
            out.append((name, head))
    for m in _POST_OF.finditer(t):
        name = _norm(m.group("name"))
        if name and _is_series(name):
            out.append((name, "recruitment"))
    for m in _ACRONYM_YEAR.finditer(t):
        name = m.group("name")
        if _is_series(name):
            out.append((name, "acronym"))
    seen, uniq = set(), []
    for n, h in out:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            uniq.append((n, h))
    return uniq


# --------------------------------------------------------------------------
# Proposals
# --------------------------------------------------------------------------

_WEAK = set("""assistant class officer clerk constable teacher engineer junior senior grade level post
posts 10 12 x xii i ii iii iv general""".split())

_STOP = set("of the and for in to a an at on by with (ug) (pg) ug pg".split()) | _GENERIC


def _distinctive(name: str, body_words: set[str]) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", name.lower())
            if w not in _STOP and w not in body_words and len(w) > 1]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return "-".join(s.split("-")[:6])


def _purpose(name: str, head: str, body_kind: str) -> str:
    n = f"{name} {head}".lower()
    if re.search(r"departmental|in[\s-]*service|promotion|ldce", n):
        return "departmental"
    if re.search(r"eligibility|\btet\b|\bset\b|\bnet\b|teacher\s*eligibility", n):
        return "eligibility"
    if re.search(r"entrance|admission|\bcet\b|\bjee\b|counsell?ing|olympiad", n):
        return "admission"
    if re.search(r"scholarship|talent\s*search|\bnmms\b", n):
        return "scholarship"
    if re.search(r"certificate|certification|diploma\s*exam", n):
        return "certification"
    if body_kind == "school_board":
        return "school_board"
    if body_kind in ("university", "institute", "testing_agency", "counselling_authority") and head.lower() in ("cet", "acronym"):
        return "admission"
    return "recruitment"


def _title(s: str) -> str:
    """Title case for an all-caps or all-lower phrase; acronyms stay."""
    words = s.split()
    return " ".join(w if (w.isupper() and len(w) <= 5) else w.capitalize()
                    if w.lower() not in ("of", "and", "for", "the", "in", "cum", "to") else w.lower()
                    for w in words)


def _pid(*parts: str) -> str:
    return ":".join(parts)


def _ignored() -> tuple[set[str], list[re.Pattern[str]]]:
    if not IGNORE_FILE.exists():
        return set(), []
    data = tomllib.loads(IGNORE_FILE.read_text("utf-8"))
    return set(data.get("ignore", [])), [re.compile(p, re.I) for p in data.get("ignore_names", [])]


def discover(cat: Catalogue, notices: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Return ``(exam_proposals, match_proposals)``, both sorted by id."""
    matcher = Matcher(cat)
    ignore_ids, ignore_names = _ignored()
    live = [n for n in notices if "gone_since" not in n]
    unmatched = [n for n in live if not n.get("exam") and not n.get("ambiguous")]

    # ---- pattern gaps in existing exams
    gaps: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for n in unmatched:
        body = cat.bodies.get(n["body"])
        if not body:
            continue
        bwords = set(re.findall(r"[a-z0-9]+", f"{body['name']} {body.get('short_name', '')}".lower()))
        title = n["title"].lower()
        for e in cat.exams_of(n["body"]):
            words = _distinctive(e["name"], bwords)
            if len(words) >= 2 and all(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", title) for w in words):
                gaps[(e["id"], " ".join(words))].append(n)
    match_props = []
    for (eid, words), ns in gaps.items():
        pattern = r"(?<![A-Za-z])" + r"\W+(?:\w+\W+){0,3}".join(re.escape(w) for w in words.split()) + r"(?![A-Za-z])"
        pid = _pid("match", eid, hashlib.sha256(pattern.encode()).hexdigest()[:8])
        if pid in ignore_ids:
            continue
        # A pattern that would claim notices for two exams is not a fix.
        rival = {x for n in ns for x in matcher.match(n["body"], n["title"]) if x != eid}
        match_props.append({
            "id": pid, "exam": eid, "add_pattern": pattern, "claims": len(ns),
            "conflicts_with": sorted(rival),
            "evidence": [{"title": n["title"][:200], "url": n["url"]} for n in sorted(ns, key=lambda n: n["id"])[:5]],
        })

    # ---- new series
    # Distinctive words of every exam's names, for "is this a partial name of
    # something we have?" (CUET without its UG/PG) and "is this someone
    # else's exam?" (NIFT's entrance test, run and published by NTA).
    exam_words: dict[str, list[set[str]]] = {}
    owner_words: dict[str, set[str]] = {}
    for e in cat.exams.values():
        owner = cat.bodies.get(e["conducted_by"], {})
        bw = set(re.findall(r"[a-z0-9]+", f"{owner.get('name', '')} {owner.get('short_name', '')}".lower()))
        owner_words[e["id"]] = bw
        sets = []
        for n in [e["name"], e.get("short_name") or "", *e.get("known_as", [])]:
            w = set(_distinctive(n, bw))
            if w:
                sets.append(w)
        exam_words[e["id"]] = sets
    scope: dict[tuple[str, str], list[dict]] = defaultdict(list)
    groups: dict[tuple[str, str], dict] = {}
    for n in unmatched:
        body = cat.bodies.get(n["body"])
        if not body:
            continue
        for name, head in series_names(n["title"]):
            if any(p.search(name) for p in ignore_names):
                continue
            # Something this body already has? Then it is a match gap, not a series.
            if matcher.match(n["body"], name):
                continue
            words = set(_distinctive(name, set()))
            if not words:
                continue
            own = {e["id"] for e in cat.exams_of(n["body"])}
            if any((words - owner_words[eid]) <= w for eid in own for w in exam_words.get(eid, ())):
                continue  # a partial name of this body's exam
            # Someone else's exam: all of its distinctive words, and at
            # least two that mean something ("assistant" alone is every
            # insurer's clerk exam).
            elsewhere = [eid for eid, sets in exam_words.items() if eid not in own
                         and any(len(w - _WEAK) >= 2 and w <= words - owner_words[eid] | words for w in sets)]
            elsewhere = [eid for eid in elsewhere if Matcher.match(matcher, cat.exams[eid]["conducted_by"], name)]
            if elsewhere:
                for eid in elsewhere:
                    scope[(eid, n["body"])].append(n)
                continue
            key = (n["body"], name.lower())
            g = groups.setdefault(key, {"names": defaultdict(int), "heads": defaultdict(int), "notices": []})
            g["names"][name] += 1
            g["heads"][head] += 1
            g["notices"].append(n)
    exam_props = []
    for (bid, _name), g in groups.items():
        ns = g["notices"]
        years = {y for n in ns for y in re.findall(r"\b20\d{2}\b", n["title"])}
        notif = sum(1 for n in ns if n.get("doc_type") in ("notification", "calendar"))
        score = len(ns) + 2 * notif + len(years)
        if len(ns) < 2 and not notif:
            continue
        body = cat.bodies[bid]
        name = max(g["names"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        if " " in name and name.isupper():
            name = _title(name.lower())
        head = max(g["heads"].items(), key=lambda kv: kv[1])[0]
        display = name if head in ("acronym", "recruitment") else f"{name} {_title(head.lower() if head.isupper() else head)}"
        if head == "recruitment":
            display = f"{body.get('short_name') or body['name']} {name} Recruitment"
        slug = _slug(name)
        eid = f"{bid}-{slug}"
        pid = _pid("exam", bid, slug)
        if pid in ignore_ids or eid in cat.exams:
            continue
        # The pattern is the whole series name, head included: "Delhi
        # University" alone would claim every DU notice.
        pattern = _phrase(display if head not in ("acronym", "recruitment") else name)
        exam_props.append({
            "id": pid, "body": bid, "score": score, "notices": len(ns), "years": sorted(years),
            "entry": {
                "id": eid, "name": display, "jurisdiction": body["jurisdiction"],
                "purpose": _purpose(name, head, body["kind"]), "conducted_by": bid,
                "frequency": "irregular", "match": {"any": [pattern]}, "status": "active",
                "notes": "Proposed by discovery from harvested notices; check name, purpose and pattern.",
            },
            "evidence": [{"title": n["title"][:200], "url": n["url"], "doc_type": n.get("doc_type")}
                         for n in sorted(ns, key=lambda n: (n.get("doc_type") != "notification", n["id"]))[:6]],
        })
    # "DUET" and "Delhi University Entrance Test" are one series: when an
    # acronym proposal is the initials of a full-name proposal of the same
    # body, the full name absorbs it (known_as, a second pattern, evidence).
    by_body: dict[str, list[dict]] = defaultdict(list)
    for p in exam_props:
        by_body[p["body"]].append(p)
    drop = set()
    for bid, props in by_body.items():
        for full in props:
            words = re.findall(r"[A-Za-z]+", full["entry"]["name"])
            initials = "".join(w[0] for w in words if w.lower() not in ("of", "and", "the", "for", "cum", "in")).upper()
            for acr in props:
                a = acr["entry"]["name"]
                if acr is full or id(acr) in drop or not a.isupper() or " " in a or len(a) < 3 or a != initials:
                    continue
                full["entry"]["known_as"] = [a]
                full["entry"]["id"] = f"{bid}-{a.lower()}"
                full["id"] = _pid("exam", bid, a.lower())
                full["entry"]["match"]["any"].append(_phrase(a))
                full["notices"] += acr["notices"]
                full["score"] += acr["score"]
                full["evidence"] = (full["evidence"] + acr["evidence"])[:8]
                drop.add(id(acr))
    exam_props = [p for p in exam_props if id(p) not in drop]

    # A proposal whose name or acronym is already an exam's name anywhere is
    # that exam, seen from another body (GPAT, which NTA ran until NBEMS
    # took it over): a scope note, not a new series.
    known: dict[str, str] = {}
    for e in cat.exams.values():
        for n in [e["name"], e.get("short_name") or "", *e.get("known_as", [])]:
            if n:
                known.setdefault(n.lower(), e["id"])
    kept = []
    for p in exam_props:
        names = [p["entry"]["name"], *p["entry"].get("known_as", [])]
        hit = next((known[n.lower()] for n in names if n.lower() in known), None)
        if hit:
            scope[(hit, p["body"])].extend({"title": ev["title"], "url": ev["url"], "id": ev["url"]} for ev in p["evidence"])
        else:
            kept.append(p)
    exam_props = kept

    for (eid, bid), ns in scope.items():
        pid = _pid("scope", eid, bid)
        if pid in ignore_ids or len(ns) < 2:
            continue
        e = cat.exams[eid]
        match_props.append({
            "id": pid, "exam": eid, "published_by": bid, "claims": len(ns),
            "suggest": (f"{bid} publishes notices for {eid} (conducted_by {e['conducted_by']}). "
                        f"If {bid} runs the exam, set conducted_by = {bid!r} and owned_by = {e['conducted_by']!r}; "
                        f"if it only allocates seats, add it to allocated_by."),
            "evidence": [{"title": n["title"][:200], "url": n["url"]} for n in sorted(ns, key=lambda n: n["id"])[:5]],
        })
    exam_props.sort(key=lambda p: p["id"])
    match_props.sort(key=lambda p: p["id"])
    return exam_props, match_props


def adopt_snippet(cat: Catalogue, exam_props: list[dict], match_props: list[dict], ids: list[str]) -> tuple[str, list[dict], list[str]]:
    """TOML for the adopted exam proposals, and the pattern edits for the
    adopted match proposals (applied to existing entries in place)."""
    from .catalogue import dump_items

    by_id = {p["id"]: p for p in exam_props + match_props}
    missing = [i for i in ids if i not in by_id]
    exams = [by_id[i]["entry"] for i in ids if i.startswith("exam:") and i in by_id]
    feeds = [by_id[i]["entry"] for i in ids if i.startswith("feed:") and i in by_id]
    edits = [by_id[i] for i in ids if i.startswith(("match:", "scope:")) and i in by_id]
    return "\n".join([*dump_items("feeds", feeds), *dump_items("exams", exams)]), edits, missing


def apply_match_edits(edits: list[dict], directory: Path = CATALOGUE_DIR) -> list[str]:
    """Append each proposal's pattern to its exam's ``match.any``."""
    from .catalogue import _file_header, load, render_file

    cat = load(directory)
    touched = []
    for ed in edits:
        fname = cat.origin[f"exams:{ed['exam']}"]
        path = directory / fname
        text = path.read_text("utf-8")
        data = tomllib.loads(text)
        for e in data["exams"]:
            if e["id"] == ed["exam"]:
                m = e.setdefault("match", {})
                anys = m.get("any")
                if not anys:
                    # The exam matched by its names; keep those as patterns.
                    names = [e["name"], e.get("short_name") or "", *e.get("known_as", [])]
                    anys = [_phrase(n) for n in names if n and len(re.sub(r"\W", "", n)) >= 3]
                if ed["add_pattern"] not in anys:
                    m["any"] = [*anys, ed["add_pattern"]]
        path.write_text(render_file(_file_header(text), data), "utf-8")
        touched.append(fname)
    return sorted(set(touched))


def write_worklists(exam_props: list[dict], match_props: list[dict], directory: Path | None = None,
                    source_props: list[dict] | None = None) -> dict[str, int]:
    """Write both worklists; a proposal keeps its ``first_seen`` across runs,
    so an unchanged harvest is an unchanged file."""
    from .crawl.harvest import HARVEST_DIR, now, read_jsonl, write_jsonl

    directory = directory or HARVEST_DIR
    counts = {}
    for name, props in (("exam-proposals", exam_props), ("match-proposals", match_props),
                        ("source-proposals", source_props or [])):
        path = directory / f"{name}.jsonl"
        old = {r["id"]: r for r in read_jsonl(path)}
        ts = now()
        for p in props:
            p["first_seen"] = old.get(p["id"], {}).get("first_seen", ts)
        write_jsonl(path, props)
        counts[name] = len(props)
        counts[f"{name}.new"] = sum(1 for p in props if p["id"] not in old)
    return counts


def _url_key(url: str) -> str:
    """Scheme, ``www.`` and trailing slash do not make a different page."""
    url = re.sub(r"^https?://(?:www\.)?", "", url.strip(), flags=re.I)
    host, _, rest = url.partition("/")
    return f"{host.lower()}/{rest}".rstrip("/")


def source_proposals(cat: Catalogue, pages: Iterable[dict], feeds: Iterable[dict]) -> list[dict]:
    """New feeds, from what the discover spider fetched *and tried*: a
    candidate page is proposed when the real adapter got notices off it that
    match this body's exams (two, or one for an RSS/Atom feed)."""
    ignore_ids, _ = _ignored()
    taken = set(cat.feeds)
    # A page adopted since the spider saw it is a feed now, not a proposal.
    known = {_url_key(f["url"]) for f in cat.feeds.values()}
    out = []
    for rec, adapter, need in [*((p, "html_links", 2) for p in pages), *((f, "rss", 1) for f in feeds if f.get("kind") != "sitemap")]:
        if rec.get("matched", 0) < need or rec["body"] not in cat.bodies:
            continue
        if _url_key(rec["id"]) in known:
            continue
        label = _slug(rec.get("text") or rec.get("title") or ("rss" if adapter == "rss" else "page")) or "page"
        fid, n = f"{rec['body']}/{label}", 2
        while fid in taken:
            fid, n = f"{rec['body']}/{label}-{n}", n + 1
        taken.add(fid)
        pid = _pid("feed", rec["body"], hashlib.sha256(rec["id"].encode()).hexdigest()[:8])
        if pid in ignore_ids:
            continue
        out.append({"id": pid, "body": rec["body"], "score": rec["matched"], "notices": rec.get("notices", 0),
                    "sample": rec.get("sample", []),
                    "entry": {"id": fid, "body": rec["body"], "url": rec["id"], "adapter": adapter,
                              "yields": "notices", "status": "active",
                              "notes": f"Found by the discover spider ({rec.get('text') or rec.get('title') or adapter})."}})
    return sorted(out, key=lambda p: p["id"])
