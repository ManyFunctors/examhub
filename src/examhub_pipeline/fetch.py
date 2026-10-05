"""The orchestrator: turn a seed source into fetched, extracted documents.

Two jobs:

* **discover** -- walk a source's notice index and return the documents worth
  fetching. Pure link classification, no model, no writes.
* **fetch** -- retrieve those documents politely, honouring robots.txt,
  per-host rate limits, the disk cache and the request budget, and return
  :class:`~examhub_pipeline.extract.ExtractedDoc` objects with the media type,
  the tier and the OCR flag already attached.

Everything is written to the work directory, never to the site.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import Settings
from .crawl.adapters import looks_unrendered
from .extract import ExtractedDoc, ExtractionError, extract_bytes, html_to_text
from .http import BudgetExhausted, Fetcher, FetchError, RobotsDenied, canonical
from .render import BrowserRenderer
from .sources import (
    NoticeRef,
    Source,
    all_sources,
    classify_links,
    get_source,
)

log = logging.getLogger(__name__)

#: A government notice index page can carry several hundred links. A cap
#: keeps one host from monopolising a run.
DEFAULT_MAX_LINKS_PER_PAGE = 400
#: ...and a cap on how many documents one source may contribute.


@dataclass(slots=True)
class FetchOutcome:
    """What happened to one URL. Success or not, the reason is recorded."""

    url: str
    ok: bool
    reason: str = ""
    status: int | None = None
    from_cache: bool = False
    not_modified: bool = False
    content_hash: str = ""
    bytes: int = 0
    media_type: str = ""
    seconds: float = 0.0
    retries: int = 0
    doc_path: str | None = None


@dataclass(slots=True)
class FetchedDoc:
    """A document that made it to disk, with its text and its provenance."""

    url: str
    source_url: str
    body: str
    doc: ExtractedDoc
    title: str = ""
    tier: str = "other"
    body_name: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_meta(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "source_url": self.source_url,
            "title": self.title,
            "tier": self.tier,
            "body": self.body_name,
            "fetched_at": self.fetched_at.isoformat(),
            "content_hash": self.doc.source_hash,
            "media_type": self.doc.media_type,
            "is_ocr": self.doc.is_ocr,
            "ocr_engine": self.doc.ocr_engine,
            "pages": self.doc.pages,
            "char_count": self.doc.char_count,
            "chunks": len(self.doc.chunks),
            "warnings": self.doc.warnings,
        }


class Pipeline:
    """State for one run: where things are cached, which sources are in play."""

    def __init__(self, settings: Settings, fetcher: Fetcher | None = None) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.fetcher = fetcher or Fetcher(settings)
        self._owns_fetcher = fetcher is None
        self.outcomes: list[FetchOutcome] = []
        self._renderer: BrowserRenderer | None = None
        self._render_failed = False

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
        if self._owns_fetcher:
            self.fetcher.close()

    def _render(self, url: str) -> tuple[str, str] | None:
        """Render a page in Firefox; None when the page cannot be rendered.

        If Firefox will not start, rendering is switched off for the rest of
        the run, so a machine without it logs one warning. A page that fails
        only costs that page."""
        if self._render_failed:
            return None
        if self._renderer is None:
            self._renderer = BrowserRenderer(self.settings.user_agent)
        try:
            return self._renderer.render(url)
        except Exception as exc:  # noqa: BLE001 - a plain page is still usable
            log.warning("firefox could not render %s: %s", url, exc)
            if self._renderer._driver is None:
                self._render_failed = True
            return None

    def __enter__(self) -> "Pipeline":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- paths ------------------------------------------------------------

    def doc_path(self, url: str) -> Path:
        return self.settings.docs_dir / _safe_name(url)

    def state_path(self) -> Path:
        return self.settings.state_dir / "documents.jsonl"

    # -- discover ---------------------------------------------------------

    def discover(
        self, source: Source, *, max_links: int = DEFAULT_MAX_LINKS_PER_PAGE
    ) -> tuple[list[NoticeRef], FetchOutcome]:
        """Walk one source's index page and classify its links."""
        started = time.perf_counter()
        url = canonical(source.notices_url)
        try:
            response = self.fetcher.fetch(url)
        except RobotsDenied as exc:
            return [], self._record(FetchOutcome(url=url, ok=False, reason=str(exc)))
        except (FetchError, BudgetExhausted) as exc:
            return [], self._record(FetchOutcome(url=url, ok=False, reason=str(exc)))

        page_url, page_html = response.final_url, response.text()
        text, title, links = html_to_text(page_html, base_url=page_url)
        refs = list(classify_links(links[:max_links], source, page_url=page_url))
        if not refs and looks_unrendered(page_html):
            # Links drawn by script are invisible to a plain fetch; render the page.
            rendered = self._render(page_url)
            if rendered is not None:
                page_url, page_html = rendered
                text, title, links = html_to_text(page_html, base_url=page_url)
                refs = list(classify_links(links[:max_links], source, page_url=page_url))
                log.info("%s: rendered in Firefox, %d links", source.key, len(links))
        # Best-first, so a per-source cap spends the request budget on the
        # notices that name themselves rather than on whichever of 344
        # "Read More" links happened to come first in the HTML.
        refs.sort(key=lambda r: (-r.priority, r.title))
        outcome = self._record(
            FetchOutcome(
                url=url,
                ok=True,
                status=response.status,
                from_cache=response.from_cache,
                not_modified=response.not_modified,
                content_hash=response.content_hash,
                bytes=len(response.content),
                media_type=response.content_type,
                seconds=time.perf_counter() - started,
            ),
            retries=self.fetcher.stats["retries"],
        )
        log.info(
            "%s: %d links, %d look like notices", source.key, len(links), len(refs)
        )
        return refs, outcome


    # -- fetch ------------------------------------------------------------

    def fetch_notice(
        self, ref: NoticeRef, *, force: bool = False, ttl: int | None = None
    ) -> FetchedDoc | None:
        """Fetch and extract one notice. Returns None and records why on failure."""
        url = canonical(ref.url)
        started = time.perf_counter()
        document_ttl = (
            self.settings.cache_ttl_document_seconds if ttl is None else ttl
        )
        try:
            response = self.fetcher.fetch(
                url, ttl_seconds=document_ttl, force=force, referer=ref.from_page
            )
        except RobotsDenied as exc:
            self._record(FetchOutcome(url=url, ok=False, reason=str(exc)))
            return None
        except BudgetExhausted as exc:
            log.info("stopping: %s", exc)
            self._record(FetchOutcome(url=url, ok=False, reason=str(exc)))
            return None
        except FetchError as exc:
            self._record(FetchOutcome(url=url, ok=False, reason=str(exc)))
            return None

        title, links = ref.title, []
        try:
            doc = extract_bytes(
                response.content,
                response.final_url,
                self.settings,
                content_type=response.content_type,
            )
        except ExtractionError as exc:
            # An HTML notice page yields links too, and those are the next
            # round of discovery, so losing the whole document over a link
            # parse would be wasteful.
            try:
                html, html_title, links = html_to_text(
                    response.text(), base_url=response.final_url
                )
                title = html_title or title
                doc = ExtractedDoc(
                    url=response.final_url,
                    text=html,
                    chunks=[],
                    media_type="text/html",
                    title=html_title,
                    char_count=len(html),
                    source_hash=response.content_hash,
                    warnings=[f"structured extraction failed ({exc}); used the HTML fallback"],
                )
            except Exception as inner:  # noqa: BLE001
                self._record(
                    FetchOutcome(
                        url=url,
                        ok=False,
                        reason=f"extraction failed: {exc}; fallback failed: {inner}",
                        status=response.status,
                    )
                )
                return None
        else:
            if doc.media_type == "text/html":
                title = doc.title or title

        path = self.doc_path(url)
        path.write_text(
            json.dumps(
                {
                    "meta": {
                        "url": response.final_url,
                        "requested_url": url,
                        "title": title,
                        "tier": ref.tier,
                        "body": ref.body,
                        "from_page": ref.from_page,
                        "name_date_hint": ref.name_date,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "content_type": response.content_type,
                        "content_hash": response.content_hash,
                        "from_cache": response.from_cache,
                        "not_modified": response.not_modified,
                        "is_ocr": doc.is_ocr,
                        "ocr_engine": doc.ocr_engine,
                        "pages": doc.pages,
                        "chunks": len(doc.chunks),
                        "char_count": doc.char_count,
                        "warnings": doc.warnings,
                    },
                    "text": doc.text,
                    "chunks": [
                        {
                            "index": c.index,
                            "page": c.page,
                            "section": c.section,
                            "is_ocr": c.is_ocr,
                            "text": c.text,
                        }
                        for c in doc.chunks
                    ],
                    "links": links,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        self._record(
            FetchOutcome(
                url=url,
                ok=True,
                status=response.status,
                from_cache=response.from_cache,
                not_modified=response.not_modified,
                content_hash=response.content_hash,
                bytes=len(response.content),
                media_type=response.content_type,
                seconds=time.perf_counter() - started,
                doc_path=str(path),
            ),
            retries=self.fetcher.stats["retries"],
        )
        return FetchedDoc(
            url=response.final_url,
            source_url=ref.from_page or "",
            body=ref.body,
            doc=doc,
            title=title,
            tier=ref.tier,
            body_name=ref.body,
            links=links,
        )

    def fetch_many(
        self,
        refs: Iterable[NoticeRef],
        *,
        limit: int | None = None,
        force: bool = False,
    ) -> list[FetchedDoc]:
        """Fetch a batch, one host at a time, never exceeding the budget.

        Grouped by host first. That is not only politeness: a serial sweep
        over a mixed host list spends most of its time waiting on a 5 second
        per-host gate, whereas grouping means each host's gate is paid once
        and the wait overlaps with the previous host's transfer.
        """
        by_host: dict[str, list[NoticeRef]] = {}
        for ref in refs:
            host = re.sub(r"^www\.", "", (canonical(ref.url).split("/")[2] if "//" in ref.url else ""))
            by_host.setdefault(host, []).append(ref)

        docs: list[FetchedDoc] = []
        for host in sorted(by_host):
            if limit is not None and len(docs) >= limit:
                break
            for ref in by_host[host]:
                if limit is not None and len(docs) >= limit:
                    break
                doc = self.fetch_notice(ref, force=force)
                if doc is not None:
                    docs.append(doc)
                if self.fetcher.budget_used >= self.settings.max_requests:
                    log.info("request budget reached; stopping this batch")
                    return docs
        return docs

    # -- load -------------------------------------------------------------


    def iter_saved(self) -> Iterable[FetchedDoc]:
        for path in sorted(self.settings.docs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            meta = payload.get("meta") or {}
            from .extract import Chunk

            chunks = [
                Chunk(
                    index=int(c.get("index", i)),
                    text=c.get("text", ""),
                    page=c.get("page"),
                    section=c.get("section"),
                    is_ocr=bool(c.get("is_ocr", False)),
                )
                for i, c in enumerate(payload.get("chunks") or [])
            ]
            text = payload.get("text", "")
            doc = ExtractedDoc(
                url=meta.get("url", ""),
                text=text,
                chunks=chunks,
                media_type=meta.get("content_type", "text/html"),
                is_ocr=bool(meta.get("is_ocr", False)),
                ocr_engine=meta.get("ocr_engine"),
                title=meta.get("title"),
                pages=int(meta.get("pages", 0) or 0),
                char_count=len(text),
                warnings=list(meta.get("warnings") or []),
                source_hash=meta.get("content_hash", ""),
            )
            yield FetchedDoc(
                url=doc.url,
                source_url=meta.get("from_page", "") or "",
                body=meta.get("body", ""),
                doc=doc,
                title=meta.get("title", "") or "",
                tier=meta.get("tier", "other"),
                body_name=meta.get("body", ""),
                links=[tuple(link) for link in (payload.get("links") or [])],
            )

    # -- bookkeeping ------------------------------------------------------

    def _record(self, outcome: FetchOutcome, *, retries: int | None = None) -> FetchOutcome:
        """Append an outcome to this run's ledger.

        ``retries`` is attributed to this one outcome rather than to the run
        total, so the log says which host was flaky instead of just that
        something, somewhere, was.
        """
        if retries is not None:
            outcome.retries = retries
        self.outcomes.append(outcome)
        return outcome

    def write_state(self) -> Path:
        """Append this run's outcomes so a re-run can be audited."""
        path = self.state_path()
        with path.open("a", encoding="utf-8") as handle:
            for outcome in self.outcomes:
                handle.write(json.dumps(asdict(outcome), sort_keys=True) + "\n")
        return path

    def summary(self) -> dict[str, Any]:
        ok = sum(1 for o in self.outcomes if o.ok)
        return {
            "attempted": len(self.outcomes),
            "ok": ok,
            "failed": len(self.outcomes) - ok,
            "requests_used": self.fetcher.budget_used,
            "cache": self.fetcher.stats,
            "cache_files": self.fetcher.cache.stats(),
            "latency_note": "per-host delay "
            f"{self.settings.host_delay_seconds}s, max {self.settings.max_per_host} in flight",
        }


_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(url: str) -> str:
    """A stable, readable, collision-free filename for a URL."""
    import hashlib

    cleaned = _SAFE_RE.sub("_", url)[:120].strip("_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned}.{digest}.json"


def resolve_sources(keys: Sequence[str] | None) -> list[Source]:
    """Turn ``--source ssc --source upsc`` into Source objects."""
    if not keys:
        return list(all_sources())
    out: list[Source] = []
    for key in keys:
        source = get_source(key)
        if source is None:
            matches = [s for s in all_sources() if key.lower() in s.name.lower()]
            if not matches:
                raise SystemExit(f"unknown source {key!r}; try: "
                                 f"{', '.join(s.key for s in all_sources())}")
            out.extend(matches)
        else:
            out.append(source)
    return out
