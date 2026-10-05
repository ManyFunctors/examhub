"""The catalogue: jurisdictions, bodies, feeds and exam series.

See ``docs/data-model.md``. This module loads ``data/catalogue/*.toml``,
checks every rule the JSON Schema cannot (referential integrity, id shape,
uniqueness, successor rules) and builds the deterministic notice -> exam
matcher. It has no network code and no model.

Readers ignore keys they do not know; that is what lets a minor schema
version add a key without a migration.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE_DIR = PROJECT_ROOT / "data" / "catalogue"

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FEED_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://[^\s/]+(/\S*)?$")
QID_RE = re.compile(r"^Q\d+$")


@dataclass
class Catalogue:
    vocab: dict[str, Any]
    jurisdictions: dict[str, dict]
    bodies: dict[str, dict]
    feeds: dict[str, dict]
    exams: dict[str, dict]
    #: id -> the file it was declared in, for error messages.
    origin: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ queries

    def exams_of(self, body_id: str) -> list[dict]:
        """Exams a notice from ``body_id`` may be matched against."""
        return [
            e for e in self.exams.values()
            if body_id in (e.get("conducted_by"), e.get("owned_by"))
            or body_id in e.get("allocated_by", ())
        ]


    def stats(self) -> dict[str, Any]:
        def count(items: Iterable[dict], key: str) -> dict[str, int]:
            out: dict[str, int] = {}
            for it in items:
                v = it.get(key, "-")
                out[v] = out.get(v, 0) + 1
            return dict(sorted(out.items(), key=lambda kv: -kv[1]))

        return {
            "jurisdictions": len(self.jurisdictions),
            "bodies": len(self.bodies),
            "feeds": len(self.feeds),
            "exams": len(self.exams),
            "bodies_by_kind": count(self.bodies.values(), "kind"),
            "exams_by_purpose": count(self.exams.values(), "purpose"),
            "exams_by_jurisdiction": count(self.exams.values(), "jurisdiction"),
            "feeds_by_status": count(self.feeds.values(), "status"),
        }


def load(directory: Path = CATALOGUE_DIR) -> Catalogue:
    """Load every TOML file in ``directory``. Duplicate ids are reported by
    :func:`lint`, not raised here, so a broken catalogue can still be
    inspected."""
    vocab = tomllib.loads((directory / "vocab.toml").read_text("utf-8"))
    cat = Catalogue(vocab=vocab, jurisdictions={}, bodies={}, feeds={}, exams={})
    cat._dupes = []  # type: ignore[attr-defined]
    for path in sorted(directory.glob("*.toml")):
        if path.name in ("vocab.toml", "reservation.toml"):
            continue
        data = tomllib.loads(path.read_text("utf-8"))
        for key, bucket in (
            ("jurisdictions", cat.jurisdictions),
            ("bodies", cat.bodies),
            ("feeds", cat.feeds),
            ("exams", cat.exams),
        ):
            for item in data.get(key, []):
                iid = item.get("id", "")
                if iid in bucket:
                    cat._dupes.append((key, iid, path.name, cat.origin.get(f"{key}:{iid}")))  # type: ignore[attr-defined]
                bucket[iid] = item
                cat.origin[f"{key}:{iid}"] = path.name
    return cat


# --------------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------------

_BODY_REQUIRED = ("id", "name", "short_name", "jurisdiction", "kind", "website", "status")
_FEED_REQUIRED = ("id", "body", "url", "adapter", "yields", "status")
_EXAM_REQUIRED = ("id", "name", "jurisdiction", "purpose", "conducted_by", "status")


def lint(cat: Catalogue) -> list[str]:
    """Every problem, as one human-readable line each. Empty means clean."""
    v = cat.vocab
    errs: list[str] = []

    def where(kind: str, iid: str) -> str:
        return f"{cat.origin.get(f'{kind}:{iid}', '?')}: {kind[:-1] if kind != 'bodies' else 'body'} {iid!r}"

    def enum(kind: str, iid: str, item: dict, key: str, vocab_key: str, required: bool = True) -> None:
        val = item.get(key)
        if val is None:
            if required:
                errs.append(f"{where(kind, iid)}: missing {key}")
            return
        vals = val if isinstance(val, list) else [val]
        for x in vals:
            if x not in v[vocab_key]:
                errs.append(f"{where(kind, iid)}: {key}={x!r} not in vocab.{vocab_key}")

    def url(kind: str, iid: str, item: dict, key: str) -> None:
        val = item.get(key)
        if val is not None and not URL_RE.match(val):
            errs.append(f"{where(kind, iid)}: {key} is not an absolute http(s) URL: {val!r}")

    def ref(kind: str, iid: str, item: dict, key: str, target: dict, label: str) -> None:
        val = item.get(key)
        if val is None:
            return
        for x in val if isinstance(val, list) else [val]:
            if x not in target:
                errs.append(f"{where(kind, iid)}: {key}={x!r} is not a known {label}")

    for kind, iid, f1, f2 in getattr(cat, "_dupes", []):
        errs.append(f"{f1}: duplicate {kind} id {iid!r} (also in {f2})")

    for jid, j in cat.jurisdictions.items():
        enum("jurisdictions", jid, j, "kind", "jurisdiction_kind")

    for bid, b in cat.bodies.items():
        for k in _BODY_REQUIRED:
            if not b.get(k):
                errs.append(f"{where('bodies', bid)}: missing {k}")
        if not ID_RE.match(bid):
            errs.append(f"{where('bodies', bid)}: id is not lowercase kebab-case")
        jur = b.get("jurisdiction", "")
        if not bid.startswith(f"{jur}-"):
            errs.append(f"{where('bodies', bid)}: id must start with its jurisdiction {jur!r}-")
        ref("bodies", bid, b, "jurisdiction", cat.jurisdictions, "jurisdiction")
        enum("bodies", bid, b, "kind", "body_kind")
        enum("bodies", bid, b, "status", "body_status")
        url("bodies", bid, b, "website")
        ref("bodies", bid, b, "parent", cat.bodies, "body")
        ref("bodies", bid, b, "successor", cat.bodies, "body")
        if b.get("status") not in (None, "active") and not b.get("successor") and b.get("status") != "defunct":
            errs.append(f"{where('bodies', bid)}: status={b['status']!r} needs a successor")
        if b.get("wikidata") and not QID_RE.match(b["wikidata"]):
            errs.append(f"{where('bodies', bid)}: wikidata must look like Q123")

    for fid, f in cat.feeds.items():
        for k in _FEED_REQUIRED:
            if not f.get(k):
                errs.append(f"{where('feeds', fid)}: missing {k}")
        if not FEED_ID_RE.match(fid) or not fid.startswith(f"{f.get('body')}/"):
            errs.append(f"{where('feeds', fid)}: id must be '<body id>/<name>'")
        ref("feeds", fid, f, "body", cat.bodies, "body")
        enum("feeds", fid, f, "adapter", "feed_adapter")
        enum("feeds", fid, f, "render", "feed_render", required=False)
        enum("feeds", fid, f, "yields", "feed_yields")
        enum("feeds", fid, f, "status", "feed_status")
        url("feeds", fid, f, "url")
        for rk in ("include", "exclude"):
            if f.get(rk):
                try:
                    re.compile(f[rk])
                except re.error as exc:
                    errs.append(f"{where('feeds', fid)}: {rk} is not a valid regex: {exc}")
        if f.get("match_scope", "body") not in ("body", "all"):
            errs.append(f"{where('feeds', fid)}: match_scope must be 'body' or 'all'")
        if f.get("identity", "url") not in ("url", "url_title"):
            errs.append(f"{where('feeds', fid)}: identity must be 'url' or 'url_title'")
        if f.get("notify", "matched") not in ("matched", "all"):
            errs.append(f"{where('feeds', fid)}: notify must be 'matched' or 'all'")
        if f.get("tier") is not None and f["tier"] not in ("hot", "warm", "cold"):
            errs.append(f"{where('feeds', fid)}: tier must be hot, warm or cold")
        if f.get("adapter") == "json_api" and not f.get("fields"):
            errs.append(f"{where('feeds', fid)}: json_api needs fields")

    for eid, e in cat.exams.items():
        for k in _EXAM_REQUIRED:
            if not e.get(k):
                errs.append(f"{where('exams', eid)}: missing {k}")
        if not ID_RE.match(eid):
            errs.append(f"{where('exams', eid)}: id is not lowercase kebab-case")
        jur = e.get("jurisdiction", "")
        if not eid.startswith(f"{jur}-"):
            errs.append(f"{where('exams', eid)}: id must start with its jurisdiction {jur!r}-")
        if jur and eid.startswith(f"{jur}-{jur}-"):
            errs.append(f"{where('exams', eid)}: jurisdiction prefix is doubled")
        if re.search(r"(?:^|-)(19|20)\d{2}(?:-|$)", eid):
            errs.append(f"{where('exams', eid)}: id contains a year; the year belongs to a cycle")
        ref("exams", eid, e, "jurisdiction", cat.jurisdictions, "jurisdiction")
        ref("exams", eid, e, "conducted_by", cat.bodies, "body")
        ref("exams", eid, e, "owned_by", cat.bodies, "body")
        ref("exams", eid, e, "allocated_by", cat.bodies, "body")
        ref("exams", eid, e, "successor", cat.exams, "exam")
        enum("exams", eid, e, "purpose", "exam_purpose")
        enum("exams", eid, e, "status", "exam_status")
        enum("exams", eid, e, "frequency", "frequency", required=False)
        enum("exams", eid, e, "qualification", "qualification", required=False)
        enum("exams", eid, e, "streams", "stream", required=False)
        url("exams", eid, e, "official_url")
        if e.get("status") == "merged" and not e.get("successor"):
            errs.append(f"{where('exams', eid)}: status='merged' needs a successor")
        for pat in (e.get("match") or {}).get("any", []) + (e.get("match") or {}).get("none", []):
            try:
                re.compile(pat)
            except re.error as exc:
                errs.append(f"{where('exams', eid)}: match pattern {pat!r} invalid: {exc}")
        if e.get("wikidata") and not QID_RE.match(e["wikidata"]):
            errs.append(f"{where('exams', eid)}: wikidata must look like Q123")

    if (CATALOGUE_DIR / "reservation.toml").exists():
        from . import reservation

        errs.extend(reservation.load().lint(set(cat.jurisdictions)))
    return errs


# --------------------------------------------------------------------------
# Matching a notice to an exam
# --------------------------------------------------------------------------

_SEP = r"[\s\-_./()]*"


def _phrase(text: str) -> str:
    """A whole-word, separator-tolerant regex for a name or acronym.

    "SSC CGL" matches "SSC-CGL", "ssc_cgl" and "SSC  CGL", but not "SSCCGLX".
    Words are allowed to run together in URLs ("cgl2026"), so the right
    boundary is "not a letter" rather than ``\\b``.
    """
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return r"(?!x)x"
    return r"(?<![A-Za-z])" + _SEP.join(re.escape(w) for w in words) + r"(?![A-Za-z])"


@dataclass(frozen=True)
class _Compiled:
    exam_id: str
    any: tuple[re.Pattern[str], ...]
    none: tuple[re.Pattern[str], ...]
    #: Specificity: the longest pattern source that matched wins a tie.
    weight: int


class Matcher:
    """Deterministic notice -> exam classification, scoped by body."""

    def __init__(self, cat: Catalogue) -> None:
        self.cat = cat
        self._by_body: dict[str, list[_Compiled]] = {}
        for e in cat.exams.values():
            m = e.get("match") or {}
            srcs = list(m.get("any") or [])
            if not srcs:
                names = [e["name"], e.get("short_name") or "", *e.get("known_as", [])]
                srcs = [_phrase(n) for n in names if n and len(re.sub(r"\W", "", n)) >= 3]
            comp = _Compiled(
                exam_id=e["id"],
                any=tuple(re.compile(p, re.I) for p in srcs),
                none=tuple(re.compile(p, re.I) for p in m.get("none") or []),
                weight=0,
            )
            for b in {e.get("conducted_by"), e.get("owned_by"), *e.get("allocated_by", [])}:
                if b:
                    self._by_body.setdefault(b, []).append(comp)

    def match(self, body_id: str, title: str, url: str = "") -> list[str]:
        """Every exam id whose patterns hit. Ties are resolved by the
        longest matched span; a genuine two-way tie returns both, which the
        caller reports as a pattern defect."""
        hay = f"{title}\n{url}"
        best: dict[str, int] = {}
        for c in self._by_body.get(body_id, []):
            if any(n.search(hay) for n in c.none):
                continue
            span = 0
            for p in c.any:
                for m in p.finditer(hay):
                    span = max(span, m.end() - m.start())
            if span:
                best[c.exam_id] = span
        if not best:
            return []
        top = max(best.values())
        return sorted(k for k, v in best.items() if v == top)

    def bodies_named(self, text: str) -> list[str]:
        """Bodies whose short name, name or known-as appears in the text.

        For aggregator feeds (PIB, Employment News, gazettes), which publish
        for every body: a notice there is matched only against the exams of
        the bodies it names, so "UPSC declares CSE result" reaches
        ``in-upsc`` and a stray "Recruitment" reaches nobody."""
        if not hasattr(self, "_body_names"):
            self._body_names = []
            for b in self.cat.bodies.values():
                if b["id"] not in self._by_body:
                    continue
                names = [b.get("short_name") or "", b["name"], *b.get("known_as", [])]
                pats = [re.compile(_phrase(n), re.I) for n in names
                        if n and len(re.sub(r"\W", "", n)) >= 3]
                if pats:
                    self._body_names.append((b["id"], tuple(pats)))
        return [bid for bid, pats in self._body_names if any(p.search(text) for p in pats)]

    def match_any_body(self, title: str, url: str = "") -> list[str]:
        """``match`` across every body the text names; see ``bodies_named``."""
        hits: set[str] = set()
        for bid in self.bodies_named(f"{title}\n{url}"):
            hits.update(self.match(bid, title, url))
        return sorted(hits)


_CYCLE_PATTERNS = (
    # "2026-27", "2026-2027"
    re.compile(r"(?<!\d)(20\d{2})\s*[-–/]\s*(?:20)?(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})(?!\d)"),
)
_SESSION = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I)


def cycle_label(title: str) -> str | None:
    """The cycle a notice title names, e.g. ``2026`` or ``2026-dec``.

    Only what the title states. No year is guessed from a filename or a
    fetch date, because a 2027 notification published in 2026 is common.
    """
    years = []
    for pat in _CYCLE_PATTERNS:
        for m in pat.finditer(title):
            years.append(m.group(1))
        if years:
            break
    if not years:
        return None
    year = max(years)
    sess = _SESSION.search(title)
    if sess:
        return f"{year}-{sess.group(1)[:3].lower()}"
    return year


# --------------------------------------------------------------------------
# Canonical TOML writer
# --------------------------------------------------------------------------

_KEY_ORDER = {
    "bodies": ["id", "name", "short_name", "known_as", "jurisdiction", "kind", "parent",
               "website", "hosts", "wikidata", "status", "successor", "notes"],
    "feeds": ["id", "body", "url", "adapter", "render", "yields", "item_selector",
              "link_selector", "title_selector", "date_selector", "include", "exclude",
              "items_path", "fields", "url_template", "keep_chrome", "identity", "match_scope", "notify", "tier", "cadence_days", "status", "notes"],
    "exams": ["id", "name", "short_name", "known_as", "jurisdiction", "purpose",
              "conducted_by", "owned_by", "allocated_by", "frequency", "qualification",
              "streams", "official_url", "match", "wikidata", "status", "successor", "notes"],
}


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        if "\\" in v and "'" not in v and "\n" not in v:
            return f"'{v}'"  # literal string: regexes stay readable
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(type(v))


def dump_items(kind: str, items: Iterable[dict]) -> Iterator[str]:
    order = _KEY_ORDER[kind]
    for it in items:
        yield f"\n[[{kind}]]"
        keys = [k for k in order if k in it] + sorted(k for k in it if k not in order)
        for k in keys:
            yield f"{k} = {_toml_value(it[k])}"


_KINDS = ("bodies", "feeds", "exams")


def _file_header(text: str) -> list[str]:
    head = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        head.append(line)
    return head


def render_file(header: list[str], data: dict[str, list[dict]]) -> str:
    out = list(header)
    for kind in _KINDS:
        items = data.get(kind) or []
        if items:
            out.append(f"\n# ---- {kind} " + "-" * (60 - len(kind)))
            out.extend(dump_items(kind, items))
    return "\n".join(out) + "\n"


#: Catalogue files that are not a jurisdiction's bodies, feeds and exams.
_NOT_JURISDICTION_FILES = ("vocab.toml", "jurisdictions.toml", "discovery-ignore.toml", "reservation.toml")


def fmt(directory: Path = CATALOGUE_DIR) -> list[str]:
    """Rewrite every jurisdiction file in canonical form. Returns the files
    that changed. Item order within a file is kept: it is the author's."""
    changed = []
    for path in sorted(directory.glob("*.toml")):
        if path.name in _NOT_JURISDICTION_FILES:
            continue
        text = path.read_text("utf-8")
        new = render_file(_file_header(text), tomllib.loads(text))
        if new != text:
            path.write_text(new, "utf-8")
            changed.append(path.name)
    return changed


def add(snippet: str, directory: Path = CATALOGUE_DIR, *, dry_run: bool = False) -> tuple[dict[str, int], list[str]]:
    """Merge new ``[[bodies]]`` / ``[[feeds]]`` / ``[[exams]]`` into the
    jurisdiction files they belong to.

    Each item goes to ``<jurisdiction>.toml`` (a feed follows its body). An
    id that already exists is refused: ids are never reused, and changing an
    entry is an edit, not an add. Nothing is written unless the catalogue
    *with* the additions lints clean, so a bad proposal cannot land half-way.
    Returns (counts, errors)."""
    new = tomllib.loads(snippet)
    cat = load(directory)
    errs: list[str] = []
    per_file: dict[str, dict[str, list[dict]]] = {}
    snippet_bodies = {b["id"]: b for b in new.get("bodies", [])}
    counts = {k: 0 for k in _KINDS}
    for kind in _KINDS:
        bucket = getattr(cat, kind)
        for it in new.get(kind, []):
            iid = it.get("id", "")
            if iid in bucket:
                errs.append(f"{kind[:-1] if kind != 'bodies' else 'body'} {iid!r} already exists")
                continue
            if kind == "feeds":
                body = snippet_bodies.get(it.get("body")) or cat.bodies.get(it.get("body"), {})
                jur = body.get("jurisdiction")
            else:
                jur = it.get("jurisdiction")
            if jur not in cat.jurisdictions:
                errs.append(f"{iid!r}: cannot tell its jurisdiction")
                continue
            bucket[iid] = it
            cat.origin[f"{kind}:{iid}"] = f"{jur}.toml (new)"
            per_file.setdefault(f"{jur}.toml", {k: [] for k in _KINDS})[kind].append(it)
            counts[kind] += 1
    errs += [e for e in lint(cat) if "(new)" in e or any(
        f"'{it['id']}'" in e for items in new.values() for it in items if isinstance(it, dict) and "id" in it)]
    if errs or dry_run:
        return counts, errs
    for name, adds in per_file.items():
        path = directory / name
        if path.exists():
            text = path.read_text("utf-8")
            header, data = _file_header(text), tomllib.loads(text)
        else:
            header = [f"# Catalogue: {cat.jurisdictions[name[:-5]].get('name', name[:-5])}. Canonical form; edit freely, then",
                      "# `python -m examhub_pipeline catalogue fmt` to normalise. See docs/data-model.md."]
            data = {}
        for kind in _KINDS:
            data.setdefault(kind, []).extend(adds[kind])
        path.write_text(render_file(header, data), "utf-8")
    return counts, []
