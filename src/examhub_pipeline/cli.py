"""Command line interface.

    python -m examhub_pipeline <subcommand>

Subcommands, in the order a run uses them:

    discover   walk source index pages, list the notices worth fetching
    fetch      retrieve notices politely, extract text, cache everything
    extract    re-run extraction over what is already cached (no network)
    validate   find candidates, verify them with Laya, print the verdicts
    review     write the review bundle and print the one-screen diff
    propose    write the reviewed changes to a git branch
    run        all of the above, in order

Plus three that need no run in front of them:

    lint       check every exam record against the schema. Offline, read-only.
    bench      measure model latency on this machine
    eval       score the validator against the labelled dev set

Exit codes matter for the scheduled job:

    0  ran, and there is something (or nothing) to look at
    1  an error the operator has to fix
    2  ran fine, nothing changed           <- what the cron job tests for
    3  ran, but some documents failed      <- partial results, review anyway
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from . import record, template
from .candidates import adjudicate, find_candidates
from .config import Settings
from .extract import ExtractionError
from .fetch import FetchedDoc, Pipeline, resolve_sources
from .http import BudgetExhausted, FetchError, RobotsDenied
from .propose import ProposeError, write_proposal_json
from .propose import propose as make_proposal
from .review import build_bundle, load_baseline
from .sources import SEED_SOURCES, get_source_by_url
from .validate import (
    LayaValidator,
    ModelUnavailable,
    ValidationResult,
    evaluate,
    load_devset,
    unvalidated_results,
    validate_record,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_CHANGE = 2
EXIT_PARTIAL = 3


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)-7s %(name)-28s %(message)s",
        stream=sys.stderr,
    )
    # httpx logs every request at INFO, which drowns out everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _settings(args: argparse.Namespace) -> Settings:
    # Only the flags the user actually passed. Passing an explicit None would
    # override the default with None, and every derived path property would
    # then fail on `None / "docs"`.
    # argparse dest -> Settings field. Not the same names: the flag is
    # `--repo` and the field is `repo_dir`.
    paths = {
        "repo_dir": getattr(args, "repo", None),
        "work_dir": getattr(args, "work_dir", None),
        "cache_dir": getattr(args, "cache_dir", None),
    }
    settings = Settings.from_env(
        **{k: Path(v) for k, v in paths.items() if v}
    )
    overrides: dict[str, Any] = {}
    if getattr(args, "host_delay", None) is not None:
        overrides["host_delay_seconds"] = args.host_delay
    if getattr(args, "max_per_host", None) is not None:
        overrides["max_per_host"] = args.max_per_host
    if getattr(args, "max_requests", None) is not None:
        overrides["max_requests"] = args.max_requests
    if getattr(args, "ignore_robots", False):
        overrides["respect_robots"] = False
    if getattr(args, "no_cache", False):
        overrides["cache_ttl_seconds"] = 0
        overrides["cache_ttl_document_seconds"] = 0
    if getattr(args, "refresh", False):
        overrides["cache_ttl_seconds"] = -1
        overrides["cache_ttl_document_seconds"] = -1
    if getattr(args, "no_ocr", False):
        overrides["enable_ocr"] = False
    if getattr(args, "no_model", False):
        overrides["enable_model"] = False
    if getattr(args, "model", None):
        overrides["laya_model"] = args.model
    if getattr(args, "max_len", None):
        overrides["laya_max_len"] = args.max_len
    if getattr(args, "max_model_calls", None):
        overrides["max_model_calls"] = args.max_model_calls
    if getattr(args, "publish_threshold", None) is not None:
        overrides["publish_threshold"] = args.publish_threshold
    if getattr(args, "choice_threshold", None) is not None:
        overrides["choice_confidence_threshold"] = args.choice_threshold
    if getattr(args, "ocr_langs", None):
        overrides["ocr_langs"] = args.ocr_langs
    if overrides:
        settings = Settings.from_env(
            repo_dir=settings.repo_dir,
            work_dir=settings.work_dir,
            cache_dir=settings.cache_dir,
            **overrides,
        )
    settings.ensure_dirs()
    return settings


def _echo(message: str = "") -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------
# discover
# --------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace) -> int:
    settings = _settings(args)
    sources = resolve_sources(args.source)
    with Pipeline(settings) as pipeline:
        total = 0
        for source in sources:
            refs, outcome = pipeline.discover(source)
            total += len(refs)
            _echo(
                f"{source.key:12} {source.host:34} {len(refs):4} notice(s)"
                + ("" if outcome.ok else f"   [FETCH FAILED: {outcome.reason[:60]}]")
            )
            for ref in refs[: args.limit]:
                _echo(f"    [{ref.tier:16}] {(ref.name_date or '-'):10} {ref.title[:58]:60} {ref.url}")
            if len(refs) > args.limit:
                _echo(f"    ... {len(refs) - args.limit} more (raise --limit to see them)")
        _echo("")
        _echo(f"{total} notice reference(s) from {len(sources)} source(s).")
        _echo(
            "Discovery is a lead, not a value. Nothing here is stored; it is a "
            "list of documents worth fetching."
        )
        failures = [o for o in pipeline.outcomes if not o.ok]
        if failures:
            _echo(f"{len(failures)} index page(s) could not be fetched (robots.txt or network).")
    return EXIT_PARTIAL if failures and total == 0 else EXIT_OK


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = _settings(args)
    sources = resolve_sources(args.source)
    docs: list[FetchedDoc] = []
    with Pipeline(settings) as pipeline:
        for source in sources:
            refs, outcome = pipeline.discover(source)
            if not outcome.ok:
                _echo(f"{source.key:12} SKIP  {outcome.reason[:70]}")
                continue
            if args.direct_url:
                # An explicit URL skips discovery: useful when a maintainer
                # has found a corrigendum and just wants that one document.
                from .sources import NoticeRef

                refs = [
                    NoticeRef(
                        body=source.name,
                        title=source.name,
                        url=url,
                        tier="notification_pdf",
                        from_page=source.notices_url,
                    )
                    for url in args.direct_url
                ]
            _echo(f"{source.key:12} {len(refs):4} notice(s) found, fetching up to {args.limit}")
            for doc in pipeline.fetch_many(refs, limit=args.limit, force=args.force):
                flags = []
                if doc.doc.is_ocr:
                    flags.append(f"OCR/{doc.doc.ocr_engine}")
                if doc.doc.warnings:
                    flags.append(f"{len(doc.doc.warnings)} warning(s)")
                _echo(
                    f"   ok  {doc.tier:16} p={doc.doc.pages:<3} "
                    f"{doc.doc.char_count:>7}ch  {doc.title[:44]:46} "
                    f"{('[' + ' '.join(flags) + ']') if flags else ''}"
                )
                for warning in doc.doc.warnings:
                    _echo(f"       ! {warning[:110]}")
                docs.append(doc)
        state = pipeline.write_state()
        summary = pipeline.summary()
    _echo("")
    _echo(f"{len(docs)} document(s) extracted into {settings.docs_dir}")
    _echo(
        f"requests: {summary['requests_used']} network, "
        f"{summary['cache']['cache_hit']} from cache, "
        f"{summary['cache']['retries']} retried, {summary['cache']['denied']} robots-denied"
    )
    _echo(f"ledger: {state}")
    failed = summary["failed"]
    if failed and not docs:
        return EXIT_ERROR
    return EXIT_PARTIAL if failed else EXIT_OK


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------


def cmd_extract(args: argparse.Namespace) -> int:
    settings = _settings(args)
    with Pipeline(settings) as pipeline:
        docs = list(pipeline.iter_saved())
        if args.url:
            wanted = set(args.url)
            docs = [d for d in docs if d.url in wanted or any(u in d.url for u in wanted)]
        _echo(f"{len(docs)} cached document(s) in {settings.docs_dir}")
        for doc in docs:
            n_chunks = len(doc.doc.chunks)
            _echo(
                f"   {doc.url.split('/')[-1][:52]:54} {doc.doc.media_type:16} "
                f"p={doc.doc.pages:<3} chunks={n_chunks:<4} ocr={doc.doc.is_ocr!s:5} "
                f"tier={doc.tier}"
            )
        if args.json:
            _echo(json.dumps([d.to_meta() for d in docs], indent=1, default=str))
    return EXIT_OK


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def _candidates_for(doc: FetchedDoc) -> Any:
    pages = [(c.page, c.text, c.is_ocr) for c in doc.doc.chunks] or None
    return adjudicate(find_candidates(doc.doc.text, doc.url, pages=pages))


def cmd_validate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    validator = LayaValidator(settings)
    model_available = False
    with Pipeline(settings) as pipeline:
        docs = list(pipeline.iter_saved())
        if args.url:
            wanted = set(args.url)
            docs = [d for d in docs if any(u in d.url for u in wanted)]
        if args.limit:
            docs = docs[: args.limit]
        _echo(f"validating {len(docs)} document(s); checkpoint={settings.laya_model}")
        try:
            model_available = validator.available
        except ModelUnavailable as exc:
            _echo(f"! Laya unavailable: {exc}")
        _echo(f"  Laya available: {model_available}")
        _echo("")
        for doc in docs:
            adjudications = _candidates_for(doc)
            if model_available:
                results = validate_record(
                    doc.doc,
                    adjudications,
                    validator,
                    settings,
                    exam_name=doc.title or "this examination",
                    source_tier=doc.tier,
                )
            else:
                results = unvalidated_results(
                    adjudications, "Laya unavailable; nothing was checked"
                )
            _echo(f"{doc.url}")
            _echo(f"   {doc.title[:80]}" + ("  [OCR]" if doc.doc.is_ocr else ""))
            for field in sorted(results):
                r = results[field]
                _echo(
                    f"   {r.symbol} {field:22} {str(r.value)[:38]:40} "
                    f"p={_fmt(r.publish_probability)} conf={_fmt(r.choice_confidence)} "
                    f"{r.reason[:60]}"
                )
            _echo("")
        stats = validator.latency_stats()
        _echo(
            f"model calls: {stats.get('calls', 0)}  "
            f"median {stats.get('median_ms', 0)} ms  max {stats.get('max_ms', 0)} ms  "
            f"mean {stats.get('mean_chars', 0)} chars"
        )
    return EXIT_OK if model_available else EXIT_PARTIAL


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


# --------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------


def _collect_pairs(
    settings: Settings,
    docs: Sequence[FetchedDoc],
    validator: LayaValidator,
    *,
    model_available: bool,
) -> tuple[list[tuple], dict[str, Any]]:
    """Build ``(path, before, after, validations, extra)`` for every document.

    The "after" record is assembled from the adjudicated, validated
    candidates. **Only values the validator verified are written.** A
    ``disputed``, ``undecided`` or ``not_validated`` value is left at
    whatever the committed record already says, and the reviewer sees it as
    a flag. That is the point of the whole exercise: a wrong parse must be
    able to reach a review bundle but not a commit.
    """
    pairs: list[tuple] = []
    ocr_documents = 0

    # Group first. Five notices about one exam must update one record, not
    # create five of them, and the grouping is the only place that can be
    # decided: it is the record map's job, not the document's.
    grouped: dict[str, list[FetchedDoc]] = {}
    for doc in docs:
        grouped.setdefault(_target_path(doc), []).append(doc)

    for path, group in grouped.items():
        if len(group) > 1:
            _echo(
                f"   (merging {len(group)} notices into one record) {path}"
            )

        # Validate every document in the group before touching the record, so
        # a merge cannot be half-applied.
        per_doc: list[tuple[FetchedDoc, dict]] = []
        for doc in group:
            adjudications = _candidates_for(doc)
            if model_available:
                results = validate_record(
                    doc.doc,
                    adjudications,
                    validator,
                    settings,
                    exam_name=doc.title or "this examination",
                    source_tier=doc.tier,
                )
            else:
                results = unvalidated_results(
                    adjudications, "Laya unavailable; nothing was checked"
                )
            per_doc.append((doc, results))

        # Supersession order: a corrigendum replaces a notification, then a
        # press release, then a portal page. Within a tier the most recently
        # fetched document wins. This is the tier rule from the data model
        # applied to a merge, and it is deterministic.
        per_doc.sort(key=lambda pair: (_TIER_ORDER.get(pair[0].tier, 0), pair[0].fetched_at))

        # Primary documents may write; others may only cross-check.
        #
        # Without this, a merge quietly moved a fact between events: the UGC
        # NET June 2025 record picked up `registration_deadline = 2025-07-08`,
        # which is the answer-key *challenge* window from a different notice,
        # and rendered it as the last date to apply. Both values are true --
        # for different things. Which document speaks for which field is not
        # something a regex can know, so the record map says it.
        entry = record_map(settings).entry_for(group[0])
        primary = entry.get("primary", "")
        primaries = [
            (doc, results)
            for doc, results in per_doc
            if not primary or primary in (doc.url or "") or primary in (doc.title or "")
        ]
        if not primaries:
            primaries = [per_doc[-1]]
        primary_docs = [doc for doc, _ in primaries]
        secondary = [pair for pair in per_doc if pair[0] not in primary_docs]
        for doc, results in secondary:
            for key, value in list(results.items()):
                if value.verdict == "verified":
                    results[key] = replace(
                        value,
                        verdict="undecided",
                        reason=(
                            "found in another notice about a different event "
                            f"({doc.tier}: {doc.url}). Not written: which document "
                            "speaks for which field is declared in "
                            "data/record-map.toml, not guessed here."
                        ),
                    )

        loaded = load_baseline(settings, path)
        is_new = loaded is None
        if loaded is None:
            # a new exam starts as the template with every fact 'unknown'
            source = get_source_by_url(group[0].source_url or group[0].url)
            entry = record_map(settings).entry_for(group[0])
            body_name = source.body_name if source else _body_name(group[0])
            title = entry.get("title") or group[0].title or group[0].url
            _echo(f"   (new record proposed) {path}  body={body_name}")
            baseline, page = record.skeleton(title=title, slug=Path(path).stem, body=body_name), ""
        else:
            baseline, page = loaded

        after = record.copy_of(baseline)
        # Per field keep the result of the document that supplied the value, so a
        # date one notice gave is not shown as "absent" because another lacked it.
        merged_results: dict[str, Any] = {}
        contributors: list[FetchedDoc] = []
        for doc, results in list(primaries) + list(secondary):
            contributed = False
            for key, value in results.items():
                where = _apply(after, key, value, doc)
                if where:
                    merged_results[where] = value
                    contributed = True
                else:
                    # unwritten verdicts still show, keyed where they would have gone
                    at = record.path_of(after, key) or key
                    held = merged_results.get(at)
                    if held is None or _RANK.get(value.verdict, 0) > _RANK.get(held.verdict, 0):
                        merged_results[at] = value
            if contributed:
                contributors.append(doc)
        record.touch(after)
        winner = (contributors or [per_doc[-1][0]])[-1]
        ocr = any(doc.doc.is_ocr for doc, _ in per_doc)
        if ocr:
            ocr_documents += 1
        pairs.append((path, baseline, after, merged_results,
                      {"ocr": ocr, "is_new": is_new, "body": page, "source_url": winner.url}))

    meta = {
        "model_available": model_available,
        "checkpoint": settings.laya_model,
        "ocr_documents": ocr_documents,
        "documents": len(docs),
    }
    return pairs, meta


#: Which verdict to show when several notices speak to one unwritten field.
_RANK = {"absent": 0, "not_validated": 1, "undecided": 2, "disputed": 3, "verified": 4}


#: Human-maintained notice -> record mapping.
#:
#: Whether two notices describe the same exam is a judgement call, and regex
#: cannot make it: NTA published five UGC-NET notices in a fortnight (the
#: schedule, an admit-card release, a city-allotment intimation, an extension
#: of the last date, and a provisional answer key) and a title-derived slug
#: turned that into five records for one exam. So the mapping is declared once,
#: in version control, next to the schema it has to agree with, and everything
#: downstream -- the path, the baseline lookup, the merge order -- follows it.
#:
#: Format (``data/record-map.toml``, parsed with tomllib)::

#:     [[record]]
#:     match  = "ugcnet.nta.ac.in"        # substring of the notice URL
#:     slug   = "ugc-ugc-net-june-2025"
#:     title  = "UGC NET, June 2025"
#:     exam_kind = "job"
#:
#: Longest ``match`` wins, so a specific corrigendum can be redirected to a
#: different record from the notification it corrects.
RECORD_MAP_PATH = "data/record-map.toml"

_cache_record_map: "RecordMap | None" = None


class RecordMap:
    """Notice URL -> record slug, declared by a human."""

    def __init__(self, entries: list[dict[str, str]], path: Path | None = None) -> None:
        self.entries = entries
        self.path = path

    def lookup(self, doc: FetchedDoc) -> str | None:
        haystacks = (doc.url or "", doc.source_url or "", doc.title or "")
        best: tuple[int, dict[str, str]] | None = None
        for entry in self.entries:
            match = entry.get("match", "")
            if not match:
                continue
            if any(match in h for h in haystacks):
                if best is None or len(match) > len(best[1].get("match", "")):
                    best = (len(match), entry)
        return best[1].get("slug") if best else None

    def entry_for(self, doc: FetchedDoc) -> dict[str, str]:
        slug = self.lookup(doc)
        for entry in self.entries:
            if entry.get("slug") == slug:
                return entry
        return {}


def record_map(settings: Settings | None = None) -> RecordMap:
    """Load the mapping, once per process."""
    global _cache_record_map
    if _cache_record_map is not None:
        return _cache_record_map
    root = (settings.root if settings else Path(__file__).resolve().parents[2])
    path = root / RECORD_MAP_PATH
    entries: list[dict[str, str]] = []
    if path.exists():
        import tomllib

        try:
            entries = [dict(e) for e in (tomllib.loads(path.read_text(encoding="utf-8")).get("record") or [])]
        except Exception as exc:  # noqa: BLE001
            _echo(f"! could not read {path}: {exc}. Every notice will get its own record.")
    _cache_record_map = RecordMap(entries, path)
    return _cache_record_map


#: Supersession order for a merge. A corrigendum replaces a notification
#: rather than sitting beside it -- that is what `source_tier` is for, and
#: when a date moves twice it is the tier that says which document won.
_TIER_ORDER = {
    "other": 0,
    "official_portal": 1,
    "notification_pdf": 2,
    "press_release": 3,
    "corrigendum": 4,
}


def _body_name(doc: FetchedDoc) -> str:
    """Last-resort body name when the URL is not in the registry.

    Deliberately loud rather than clever: a record with a placeholder body is
    obviously wrong, and one with a plausible invented name is not.
    """
    return doc.body or "UNKNOWN"


#: Filename dates are stripped from a slug: a notice dated 2025-06-15 and a
#: corrigendum dated 2025-07-01 are the same exam.
_SLUG_DATE = re.compile(r"-\d{4}-?\d{2}-?\d{2}")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _target_path(doc: FetchedDoc) -> str:
    """Where a record for this document would live, repo-relative.

    A human-maintained mapping wins when there is one, because whether two
    notices describe the same exam is not something a regex can decide -- NTA
    published five UGC-NET notices in a fortnight, all about one exam, and a
    title-derived slug made five records for it.

    Otherwise: ``<taxonomy-body>-<slugified title>``. The body is the taxonomy
    name so the filename and the ``bodies`` key agree; they used to disagree
    (``nta-ugc-net-...`` for ``bodies = ['UGC']``), which is the kind of thing
    nobody notices until they look for the file by hand.
    """
    mapped = record_map().lookup(doc)
    if mapped:
        return f"content/exams/{mapped}.md"
    source = get_source_by_url(doc.source_url or doc.url)
    body = _slugify(source.body_name if source else (doc.body or "unknown")) or "unknown"
    title = _SLUG_DATE.sub("", _slugify(doc.title or ""))
    slug = "-".join(part for part in (body, title[:80]) if part) or body
    return f"content/exams/{slug}.md"


def _apply(rec: dict, field: str, result: ValidationResult, doc: FetchedDoc) -> str | None:
    """Write one verified value into the record, with its evidence.

    Returns the record path written, or None. A value the source hedges is
    stored tentative whatever the verifier said; only a human confirms it.
    """
    if result.verdict != "verified" or not result.value:
        return None
    where = record.set_value(rec, field, result.value, provisional=result.provisional)
    if where:
        record.add_evidence(rec, field=where, url=doc.url, tier=doc.tier,
                            words=result.evidence or result.model_choice_text or result.value)
    return where


def dt_date(value: str) -> Any:
    import datetime as _dt

    return _dt.date.fromisoformat(value)


def cmd_review(args: argparse.Namespace) -> int:
    settings = _settings(args)
    validator = LayaValidator(settings)
    with Pipeline(settings) as pipeline:
        docs = list(pipeline.iter_saved())
        if args.url:
            docs = [d for d in docs if any(u in d.url for u in args.url)]
        if args.limit:
            docs = docs[: args.limit]
        try:
            model_available = validator.available
        except ModelUnavailable as exc:
            _echo(f"! {exc}")
            model_available = False

        pairs, meta = _collect_pairs(
            settings, docs, validator, model_available=model_available
        )
        meta["latency"] = validator.latency_stats()
        bundle = build_bundle(settings, pairs, meta=meta)
        root = bundle.write(settings)
        _echo(bundle.render_summary())
        _echo(f"bundle: {root}")
        material = bundle.material
    if not material:
        return EXIT_NO_CHANGE
    return EXIT_OK


# --------------------------------------------------------------------------
# propose
# --------------------------------------------------------------------------


def cmd_propose(args: argparse.Namespace) -> int:
    settings = _settings(args)
    validator = LayaValidator(settings)
    with Pipeline(settings) as pipeline:
        docs = list(pipeline.iter_saved())
        try:
            model_available = validator.available
        except ModelUnavailable:
            model_available = False
        pairs, meta = _collect_pairs(
            settings, docs, validator, model_available=model_available
        )
        bundle = build_bundle(settings, pairs, meta=meta)
        bundle.write(settings)
        _echo(bundle.render_summary())
        try:
            proposal = make_proposal(
                settings,
                bundle,
                branch=args.branch,
                repo=Path(args.repo) if args.repo else None,
                commit=args.commit,
                base=args.base,
                use_worktree=not args.no_worktree,
            )
        except ProposeError as exc:
            _echo(f"propose failed: {exc}")
            return EXIT_ERROR
        write_proposal_json(proposal, bundle)
        _echo("")
        _echo(proposal.render())
    return EXIT_OK


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    settings = _settings(args)

    # 1. discover + fetch
    args.limit = args.run_limit
    rc = cmd_fetch(args)
    if rc == EXIT_ERROR:
        return rc

    # 2..4 are review, which internally re-derives candidates and validation
    # from the cache. Re-fetching would be free but pointless.
    fetch_args = argparse.Namespace(**vars(args))
    fetch_args.repo = settings.repo_dir
    fetch_args.work_dir = settings.work_dir
    fetch_args.cache_dir = settings.cache_dir
    review_rc = cmd_review(fetch_args)
    _echo("")
    _echo(f"total {time.perf_counter() - started:.1f}s")
    if review_rc == EXIT_NO_CHANGE:
        _echo("nothing changed; the scheduled job should not open a pull request")
    return review_rc


# --------------------------------------------------------------------------
# bench / eval
# --------------------------------------------------------------------------


def cmd_bench(args: argparse.Namespace) -> int:
    settings = _settings(args)
    validator = LayaValidator(settings)
    _echo(f"checkpoint: {settings.laya_model}  max_len: {settings.laya_max_len}")
    try:
        validator.load()
    except ModelUnavailable as exc:
        _echo(f"Laya unavailable: {exc}")
        return EXIT_PARTIAL
    import torch

    _echo(f"torch {torch.__version__}  threads {torch.get_num_threads()}  cuda {torch.cuda.is_available()}")
    from .extract import Chunk, ExtractedDoc
    from .validate import _ask_field

    sizes = [512, 1024, 2048, 4096, 8192]
    print(f"{'chars':>7} {'questions':>10} {'median ms':>10} {'ms/char':>9}")
    for size in sizes:
        text = ("The National Testing Agency will conduct the examination on "
                "15.06.2027. " * 200)[:size]
        doc = ExtractedDoc(
            url="bench",
            text=text,
            chunks=[Chunk(index=0, text=text, page=1)],
            char_count=len(text),
        )
        times: list[float] = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            _ask_field(doc, doc.chunks, "exam_date", ["exam_date: 2027-06-15"], validator, settings)
            times.append(time.perf_counter() - start)
        times.sort()
        median = times[len(times) // 2] * 1000
        _echo(f"{len(text):7} {2:10} {median:10.0f} {median / max(1, len(text)):9.3f}")
    _echo("")
    _echo(json.dumps(validator.latency_stats(), indent=1))
    return EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    settings = _settings(args)
    path = Path(args.devset) if args.devset else settings.devset_dir / "devset.jsonl"
    if not path.exists():
        _echo(f"no dev set at {path}")
        return EXIT_ERROR
    examples = load_devset(path)
    _echo(f"{len(examples)} labelled example(s) from {path}")
    _echo(f"checkpoint: {settings.laya_model}  max_len: {settings.laya_max_len}")
    validator = LayaValidator(settings)
    try:
        validator.load()
    except ModelUnavailable as exc:
        _echo(f"Laya unavailable: {exc}")
        return EXIT_PARTIAL
    report = evaluate(examples, validator, settings, verbose=args.verbose)
    if "error" in report:
        _echo(report["error"])
        return EXIT_PARTIAL
    _echo("")
    _echo("EXISTENCE  (noul: does the document publish this field?)")
    _echo(json.dumps(report["existence"], indent=1))
    _echo("VALUE      (choice: is our value the one the document gives?)")
    _echo(json.dumps(report["value"], indent=1))
    _echo("CALIBRATION")
    _echo(json.dumps(report["calibration"], indent=1))
    _echo("LATENCY")
    _echo(json.dumps(report["latency"], indent=1))
    if report["misses"]:
        _echo("MISSES")
        for miss in report["misses"]:
            _echo(f"  {miss['id']:26} {miss['field']:22} want={miss['expect_value']} got={miss['picked']}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        _echo(f"report: {args.out}")
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    """Check every exam record against the schema, and nothing else.

    This is the pull-request gate, and it is deliberately read-only: it opens
    no file for writing, contacts no host, and loads no model. A maintainer can
    run it on a working tree with unsaved intentions and get an answer about
    the files on disk, nothing more.

    `--strict` turns warnings into errors, which is what CI wants: a record
    that will render with a missing status is not a warning, it is a bug that
    happens to be survivable.
    """
    settings = _settings(args)
    content = settings.content_dir
    if not content.is_dir():
        _echo(f"no content/exams/ under {settings.repo_dir}")
        return EXIT_ERROR

    paths = sorted(content.glob("*.md"))
    if args.path:
        wanted = set(args.path)
        paths = [p for p in paths if p.name in wanted or str(p) in wanted]
    if not paths:
        _echo("no records to check")
        return EXIT_OK

    # Records follow docs/exam-template.md; the checker is derived from it.
    try:
        shape = template.shape()
    except (OSError, ValueError) as exc:
        _echo(f"cannot read the exam template: {exc}")
        return EXIT_ERROR

    errors = 0
    warnings = 0
    for path in paths:
        try:
            rec, _ = record.load(path)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            _echo(f"X {path.name}: cannot be parsed: {exc}")
            errors += 1
            continue
        for problem in template.check(rec, shape):
            if problem.level == "error" or args.strict:
                _echo(f"X {path.name}: {problem}")
                errors += 1
            else:
                _echo(f"~ {path.name}: {problem}")
                warnings += 1

    _echo("")
    _echo(
        f"{len(paths)} record(s): {errors} error(s), {warnings} warning(s)"
        + ("  [strict: warnings counted as errors]" if args.strict else "")
    )
    if errors:
        return EXIT_ERROR
    if warnings and args.strict:
        return EXIT_ERROR
    return EXIT_OK


def cmd_sources(args: argparse.Namespace) -> int:
    _echo(f"{len(SEED_SOURCES)} seed source(s)\n")
    for source in SEED_SOURCES:
        _echo(f"{source.key:12} {source.name[:44]:46} {source.host}")
        _echo(f"{'':12} {source.notices_url}")
        if source.notes:
            _echo(f"{'':12} note: {source.notes}")
    return EXIT_OK


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", help="Hugo site to write into (default site/)")
    parser.add_argument("--work-dir", help="where caches, docs and reviews go")
    parser.add_argument("--cache-dir", help="HTTP cache (delete it to force a refetch)")
    parser.add_argument("--host-delay", type=float, help="seconds between requests per host")
    parser.add_argument("--max-per-host", type=int, help="concurrent requests per host")
    parser.add_argument("--max-requests", type=int, help="per-run network request budget")
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="do not consult robots.txt. Off by default and there for a debugging "
        "session on a host you own. Nothing in this project sets it.",
    )
    parser.add_argument("--no-cache", action="store_true", help="ignore the cache entirely")
    parser.add_argument(
        "--refresh", action="store_true",
        help="revalidate cached URLs with a conditional GET (cheap) rather than "
        "serving from cache",
    )
    parser.add_argument("--no-ocr", action="store_true", help="do not OCR image-only PDFs")
    parser.add_argument("--ocr-langs", help="tesseract language codes, e.g. eng+hin")
    parser.add_argument("--no-model", action="store_true", help="skip Laya entirely")
    parser.add_argument("--model", help="laya checkpoint (default typed-decisions)")
    parser.add_argument("--max-len", type=int, help="model context window")
    parser.add_argument("--max-model-calls", type=int, help="per-run model call cap")
    parser.add_argument("--publish-threshold", type=float)
    parser.add_argument("--choice-threshold", type=float)
    parser.add_argument("-v", "--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examhub_pipeline",
        description=(
            "Crawl official exam notices, extract deterministically, verify with "
            "Laya, and propose a reviewable diff for the ExamHub Hugo site. "
            "Never publishes."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="list the notices on each source's index page")
    p.add_argument("--source", action="append", help="source key (repeatable); default all")
    p.add_argument("--limit", type=int, default=10, help="notices to print per source")
    _add_common(p)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("fetch", help="fetch notices and extract their text")
    p.add_argument("--source", action="append")
    p.add_argument("--limit", type=int, default=6, help="documents per source")
    p.add_argument("--direct-url", action="append", help="fetch this exact URL (repeatable)")
    p.add_argument("--force", action="store_true", help="ignore the cache for documents")
    _add_common(p)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("extract", help="re-list what is already cached (no network)")
    p.add_argument("--url", action="append", help="filter by URL substring")
    p.add_argument("--limit", type=int)
    p.add_argument("--json", action="store_true", help="print the metadata as JSON")
    _add_common(p)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("validate", help="find candidates and verify them with Laya")
    p.add_argument("--url", action="append", help="filter by URL substring")
    p.add_argument("--limit", type=int)
    _add_common(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("review", help="write the review bundle and print the diff")
    p.add_argument("--url", action="append", help="filter by URL substring")
    p.add_argument("--limit", type=int)
    _add_common(p)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("propose", help="write reviewed changes to a git branch")
    p.add_argument("--branch", help="branch name (default pipeline/<date>-review)")
    p.add_argument("--base", help="base ref for the new branch")
    p.add_argument(
        "--commit", action="store_true",
        help="commit on the new branch. Off by default: the files are written to a "
        "branch worktree and left uncommitted for inspection.",
    )
    p.add_argument(
        "--no-worktree", action="store_true",
        help="check the branch out in the target repo instead of a separate worktree",
    )
    _add_common(p)
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("run", help="fetch, extract, validate and review in one go")
    p.add_argument("--source", action="append")
    p.add_argument("--run-limit", type=int, default=4, help="documents per source")
    p.add_argument("--direct-url", action="append")
    p.add_argument("--force", action="store_true")
    p.add_argument("--url", action="append")
    p.add_argument("--limit", type=int)
    p.add_argument("--branch")
    p.add_argument("--base")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--no-worktree", action="store_true")
    _add_common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("bench", help="measure model latency on this machine")
    p.add_argument("--repeat", type=int, default=3)
    _add_common(p)
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("eval", help="score the validator on the labelled dev set")
    p.add_argument("--devset", help="path to devset.jsonl")
    p.add_argument("--out", help="write the JSON report here")
    _add_common(p)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser(
        "lint",
        help="check every exam record against the schema (offline, read-only)",
    )
    p.add_argument("--path", action="append", help="only these files")
    p.add_argument(
        "--strict", action="store_true", help="count warnings as errors"
    )
    _add_common(p)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("catalogue", help="lint / stats / coverage / fmt / add / discover / adopt")
    p.add_argument("action", choices=["lint", "stats", "coverage", "fmt", "add", "discover", "adopt"])
    p.add_argument("targets", nargs="*",
                   help="add: TOML files of new [[bodies]]/[[feeds]]/[[exams]]; adopt: proposal ids")
    p.add_argument("--dry-run", action="store_true", help="add/adopt: check, do not write")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_catalogue)

    p = sub.add_parser("documents", help="structure fetched notification PDFs / show one / render")
    p.add_argument("action", choices=["build", "show", "file", "select"])
    p.add_argument("targets", nargs="*", help="show: notice ids; file: PDF paths")
    p.add_argument("--json", action="store_true", help="show/file: print the record, not Markdown")
    p.add_argument("--limit", type=int, default=40, help="select: how many")
    p.add_argument("--jobs", type=int, default=None, help="build: worker processes")
    p.set_defaults(func=cmd_documents)

    p = sub.add_parser("names", help="give records still titled with their official name a short title")
    p.add_argument("--exams", default=str(Path(__file__).resolve().parents[2] / "site" / "content" / "exams"),
                   help="the exam records folder (default: site/content/exams)")
    p.add_argument("--apply", action="store_true", help="write the titles (default: print them)")
    p.set_defaults(func=cmd_names)

    p = sub.add_parser("convert", help="rebuild the records from the old ExamHub data, then merge and tidy them")
    p.add_argument("--force", action="store_true", help="also overwrite records the recheck updated since")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("aliases", help="drop other names that belong to a different kind of exam")
    p.add_argument("--exams", default=str(Path(__file__).resolve().parents[2] / "site" / "content" / "exams"),
                   help="the exam records folder (default: site/content/exams)")
    p.add_argument("--apply", action="store_true", help="write the fixes (default: print them)")
    p.set_defaults(func=cmd_aliases)

    p = sub.add_parser("links", help="move a file given as a record's official page into its documents")
    p.add_argument("--exams", default=str(Path(__file__).resolve().parents[2] / "site" / "content" / "exams"),
                   help="the exam records folder (default: site/content/exams)")
    p.add_argument("--apply", action="store_true", help="write the fixes (default: print them)")
    p.set_defaults(func=cmd_links)

    p = sub.add_parser("dedupe", help="merge records that are one exam in two files, when nothing is lost")
    p.add_argument("--exams", default=str(Path(__file__).resolve().parents[2] / "site" / "content" / "exams"),
                   help="the exam records folder (default: site/content/exams)")
    p.add_argument("--apply", action="store_true", help="write the merges (default: print them)")
    p.set_defaults(func=cmd_dedupe)

    p = sub.add_parser("archive", help="save a Wayback Machine copy of each document read")
    p.add_argument("--limit", type=int, default=20, help="most documents to archive this run")
    p.add_argument("--dry-run", action="store_true", help="list what would be archived; send nothing")
    p.add_argument("--fill-records", action="store_true",
                   help="instead: write each snapshot into the records' document_archive (no network)")
    p.add_argument("--apply", action="store_true", help="with --fill-records: write the records")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("readme-stats", help="regenerate the README's stats table from the catalogue and site")
    p.add_argument("--apply", action="store_true", help="write README.md (default: print whether it changed)")
    p.set_defaults(func=cmd_readme_stats)

    p = sub.add_parser("sources", help="print the seed source registry")
    _add_common(p)
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("due-sources",
                        help="which seed sources are worth re-checking tonight (exams with a date coming up)")
    p.add_argument("--within-days", type=int, default=5,
                   help="a record counts as due if its soonest date is within this many days (default 5)")
    p.add_argument("--cap", type=int, default=5,
                   help="most sources to print, so the request budget stays bounded (default 5)")
    p.add_argument("--no-rotation", action="store_true",
                   help="print nothing when no source is due, instead of topping up with the day's rotation pick")
    p.set_defaults(func=cmd_due_sources)

    return parser


def cmd_names(args: argparse.Namespace) -> int:
    """Short titles, filled wherever a record still carries the notice's own name.
    Exit 0 when titles changed, 2 when nothing did, 1 on an error."""
    from . import names
    try:
        result = names.fill(Path(args.exams), apply=args.apply, log=_echo)
    except (OSError, ValueError) as exc:
        _echo(f"names failed: {exc}")
        return EXIT_ERROR
    for group in sorted(set(result.duplicates)):
        _echo("names: these look like one exam in several files: " + ", ".join(group))
    return EXIT_OK if result.renamed else EXIT_NO_CHANGE


def cmd_convert(args: argparse.Namespace) -> int:
    """Old ExamHub records -> site records, the whole way: convert each one, merge the
    duplicates the old batches made, then the same tidy steps the nightly run does.
    Running it twice gives the same files."""
    from . import aliases, dedupe, links, names
    from .convert import build
    exams = build.OUT
    logging.getLogger("examhub_pipeline.convert.build").setLevel(logging.INFO)
    try:
        build.run(force=args.force)
        dedupe.run(exams, apply=True, log=_echo)
        aliases.fill(exams, apply=True, log=_echo)
        links.fill(exams, apply=True, log=_echo)
        names.fill(exams, apply=True, log=_echo)
    except (OSError, ValueError) as exc:
        _echo(f"convert failed: {exc}")
        return EXIT_ERROR
    return EXIT_OK


def cmd_readme_stats(args: argparse.Namespace) -> int:
    """The README's stats table. Exit 0 when it changed, 2 when it didn't, 1 on an error."""
    from . import readme_stats
    try:
        return EXIT_OK if readme_stats.fill(apply=args.apply, log=_echo) else EXIT_NO_CHANGE
    except OSError as exc:
        _echo(f"readme-stats failed: {exc}")
        return EXIT_ERROR


def cmd_due_sources(args: argparse.Namespace) -> int:
    """Comma-separated seed source keys worth re-checking tonight: exams with
    a date due soon, plus the day's rotation pick for coverage."""
    from . import priority
    keys = priority.tonight_sources(within_days=args.within_days, cap=args.cap,
                                    rotation=not args.no_rotation)
    _echo(",".join(keys))
    return EXIT_OK


def cmd_aliases(args: argparse.Namespace) -> int:
    """Wrong other names. Exit 0 when records changed, 2 when none did, 1 on an error."""
    from . import aliases
    try:
        return EXIT_OK if aliases.fill(Path(args.exams), apply=args.apply, log=_echo) else EXIT_NO_CHANGE
    except (OSError, ValueError) as exc:
        _echo(f"aliases failed: {exc}")
        return EXIT_ERROR


def cmd_links(args: argparse.Namespace) -> int:
    """Official page links that point at a file. Exit 0 when records changed, 2 when none did."""
    from . import links
    try:
        return EXIT_OK if links.fill(Path(args.exams), apply=args.apply, log=_echo) else EXIT_NO_CHANGE
    except (OSError, ValueError) as exc:
        _echo(f"links failed: {exc}")
        return EXIT_ERROR


def cmd_dedupe(args: argparse.Namespace) -> int:
    """Duplicate records merged into one. Exit 0 when files merged, 2 when none did, 1 on an error."""
    from . import dedupe
    try:
        result = dedupe.run(Path(args.exams), apply=args.apply, log=_echo)
    except (OSError, ValueError) as exc:
        _echo(f"dedupe failed: {exc}")
        return EXIT_ERROR
    return EXIT_OK if result.merged else EXIT_NO_CHANGE


def cmd_archive(args: argparse.Namespace) -> int:
    """Wayback copies of the documents read. Exit 0 when any snapshot was recorded,
    2 when there was nothing to do, 1 when every attempt failed."""
    from . import archive
    if args.fill_records:
        try:
            return EXIT_OK if archive.fill_records(apply=args.apply, log=_echo) else EXIT_NO_CHANGE
        except (OSError, ValueError) as exc:
            _echo(f"archive failed: {exc}")
            return EXIT_ERROR
    try:
        result = archive.run(limit=args.limit, dry_run=args.dry_run, log=_echo)
    except OSError as exc:
        _echo(f"archive failed: {exc}")
        return EXIT_ERROR
    if result.archived or result.found:
        return EXIT_OK
    return EXIT_ERROR if result.failed else EXIT_NO_CHANGE


def cmd_documents(args: argparse.Namespace) -> int:
    """Structure notification PDFs into readable records.

    ``build`` reads what ``scrapy crawl documents`` fetched; ``show`` prints
    a stored record; ``file`` structures local PDFs (for checking a reader
    change against a real notice); ``select`` lists what the next fetch
    would take.
    """
    from . import documents
    from .crawl import harvest, ingest

    if args.action == "build":
        counts = ingest.build(jobs=args.jobs)
        print(json.dumps(counts))
        return 0
    if args.action == "select":
        notices = harvest.read_jsonl(harvest.HARVEST_DIR / "notices.jsonl")
        for n in ingest.select(notices, ingest.load_index(), limit=args.limit, gaps=ingest.load_gaps()):
            print(n["id"][:12], n["body"], n["exam"], "|", n["title"][:90])
        return 0
    if args.action == "show":
        for target in args.targets:
            matches = [k for k in ingest.load_index() if k.startswith(target)]
            if len(matches) != 1:
                print(f"{target}: {len(matches)} matching notices", file=sys.stderr)
                return 1
            path = ingest.record_path(matches[0], ".json" if args.json else ".md")
            if not path.exists():
                print(f"{target}: no record ({ingest.load_index()[matches[0]].get('status')})", file=sys.stderr)
                return 1
            print(path.read_text(encoding="utf-8"))
        return 0
    settings = Settings.from_env(ocr_max_pages=ingest.OCR_MAX_PAGES)
    for target in args.targets:
        notice = {"id": Path(target).stem, "url": str(target), "title": Path(target).name}
        record = documents.structure(Path(target).read_bytes(), notice, settings)
        print(json.dumps(record, ensure_ascii=False, indent=1) if args.json else documents.render_markdown(record))
    return 0


def cmd_catalogue(args: argparse.Namespace) -> int:
    """Lint the catalogue, print its size, or report which exams have evidence.

    Exit codes follow the rest of the CLI: 1 when lint finds a problem, 0
    otherwise.
    """
    import json

    from . import catalogue as C

    cat = C.load()
    if args.action == "lint":
        errs = C.lint(cat)
        for e in errs:
            print(e)
        s = cat.stats()
        print(f"{len(errs)} problem(s); {s['bodies']} bodies, {s['feeds']} feeds, {s['exams']} exams")
        return 1 if errs else 0
    if args.action == "stats":
        print(json.dumps(cat.stats(), indent=2))
        return 0
    if args.action == "coverage":
        # Evidence, not assertion: an exam series is "seen" when at least one
        # harvested notice matched it. The rest were entered from knowledge
        # and still need a feed that proves them.
        from .crawl.harvest import HARVEST_DIR, read_jsonl

        notices = read_jsonl(HARVEST_DIR / "notices.jsonl")
        seen: dict[str, int] = {}
        for n in notices:
            if "exam" in n and "gone_since" not in n:
                seen[n["exam"]] = seen.get(n["exam"], 0) + 1
        total = len(cat.exams)
        by_jur: dict[str, list[int]] = {}
        for e in cat.exams.values():
            row = by_jur.setdefault(e["jurisdiction"], [0, 0])
            row[1] += 1
            row[0] += e["id"] in seen
        print(f"{len(seen)}/{total} exam series have at least one live notice")
        for j, (a, b) in sorted(by_jur.items(), key=lambda kv: -kv[1][1]):
            print(f"  {j:3} {a:4}/{b:<4}")
        if args.verbose:
            for eid in sorted(set(cat.exams) - set(seen)):
                print("  unseen", eid)
        return 0
    if args.action == "fmt":
        for name in C.fmt():
            print("reformatted", name)
        return 0
    if args.action == "add":
        rc = 0
        for path in args.targets:
            counts, errs = C.add(Path(path).read_text("utf-8"), dry_run=args.dry_run)
            for e in errs:
                print(f"{path}: {e}")
            print(f"{path}: {'would add' if args.dry_run else 'added' if not errs else 'refused'} {counts}")
            rc |= bool(errs)
        return rc
    from . import discovery as D
    from .crawl.harvest import HARVEST_DIR, read_jsonl

    if args.action == "discover":
        exam_props, match_props = D.discover(cat, read_jsonl(HARVEST_DIR / "notices.jsonl"))
        source_props = D.source_proposals(cat, read_jsonl(HARVEST_DIR / "discovered-pages.jsonl"),
                                          read_jsonl(HARVEST_DIR / "discovered-feeds.jsonl"))
        counts = D.write_worklists(exam_props, match_props, source_props=source_props)
        print(json.dumps(counts, sort_keys=True))
        if args.verbose:
            for p in sorted(exam_props, key=lambda p: -p["score"])[:50]:
                print(f"  {p['score']:3}  {p['id']:55} {p['entry']['name']}")
        return 0
    if args.action == "adopt":
        exam_props = read_jsonl(HARVEST_DIR / "exam-proposals.jsonl")
        match_props = read_jsonl(HARVEST_DIR / "match-proposals.jsonl")
        exam_props += read_jsonl(HARVEST_DIR / "source-proposals.jsonl")
        snippet, edits, missing = D.adopt_snippet(cat, exam_props, match_props, args.targets)
        for m in missing:
            print(f"no such proposal: {m}")
        scope = [e for e in edits if "add_pattern" not in e]
        for e in scope:
            print(f"{e['id']}: not adoptable automatically -- {e['suggest']}")
        edits = [e for e in edits if "add_pattern" in e]
        rc = 1 if missing or scope else 0
        if snippet.strip():
            counts, errs = C.add(snippet, dry_run=args.dry_run)
            for e in errs:
                print(e)
            print(f"{'would add' if args.dry_run else 'added' if not errs else 'refused'}: "
                  f"{counts['exams']} exam(s), {counts['feeds']} feed(s)")
            rc |= bool(errs)
        if edits and not args.dry_run:
            for f in D.apply_match_edits(edits):
                print("patterns widened in", f)
        return rc
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _log(getattr(args, "verbose", False))
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _echo("\ninterrupted")
        return EXIT_ERROR
    except (FetchError, RobotsDenied, BudgetExhausted) as exc:
        _echo(f"fetch problem: {exc}")
        return EXIT_PARTIAL
    except ExtractionError as exc:
        _echo(f"extraction problem: {exc}")
        return EXIT_PARTIAL
    except ProposeError as exc:
        _echo(f"propose problem: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
