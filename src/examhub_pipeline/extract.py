"""HTML / PDF / scan -> plain text, with the provenance of how it got there.

The output of this module is the *state* the verification model is asked
questions about, so its shape matters. Three properties, in order of
importance:

1. **Chunk boundaries are meaningful.** A page boundary or a section heading
   is where a date table ends and a fee table begins. Chunking on those, not
   on a fixed character count alone, is why the model sees a coherent window.
2. **Every chunk knows where it came from** -- page number, and whether it is
   OCR output. A value read off an OCR chunk is a lower-quality value and the
   reviewer has to be told.
3. **The OCR flag is never lost.** Sikkim PSC, Mizoram PSC and MCC counselling
   schedules are image-only PDFs. Every field on such a page is OCR output
   and can be wrong, and that fact travels all the way to ``provenance.ocr``.

Extraction here is deterministic. There is no model in this file and there
must not be one.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)

# Tags whose text is chrome, not content.
_DROP_TAGS = ("script", "style", "noscript", "svg", "canvas", "iframe", "nav", "footer", "form")
_BLOCK_TAGS = (
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "section", "article", "ul", "ol", "dd", "dt",
)
_WS_RE = re.compile(r"[ \t ]+")
_MULTINL_RE = re.compile(r"\n{3,}")


class ExtractionError(RuntimeError):
    """The document could not be turned into text at all."""


@dataclass(slots=True)
class Chunk:
    """A window of text, with everything needed to reason about where it is."""

    index: int
    text: str
    #: 1-based page number, or None for HTML.
    page: int | None
    #: Name of the nearest preceding heading, when the document has one.
    section: str | None = None
    is_ocr: bool = False

    @property
    def location(self) -> str:
        if self.page:
            base = f"p.{self.page}"
            if self.is_ocr:
                base += " (ocr)"
            return f"{base}" + (f" {self.section}" if self.section else "")
        return self.section or f"chunk {self.index}"


@dataclass(slots=True)
class ExtractedDoc:
    """Plain text plus how it was obtained."""

    url: str
    text: str
    chunks: list[Chunk] = field(default_factory=list)
    media_type: str = "text/html"
    #: True when any part of the text came from OCR. One flag for the whole
    #: document, because a partial OCR means the reader must distrust the
    #: page as a unit.
    is_ocr: bool = False
    ocr_engine: str | None = None
    title: str | None = None
    pages: int = 0
    char_count: int = 0
    #: ``(anchor_text, absolute_url)`` pairs, when the caller asked for
    #: them. HTML only; a PDF has no links to give.
    links: list[tuple[str, str]] = field(default_factory=list)
    #: Non-fatal problems worth showing a reviewer: "only the first 3 of 90
    #: pages were OCR'd", "no text layer and tesseract is missing".
    warnings: list[str] = field(default_factory=list)
    source_hash: str = ""

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for c in self.chunks if c.is_ocr)

    def chunk_at(self, offset: int) -> Chunk | None:
        for chunk in self.chunks:
            if chunk.text and chunk.text_offset(offset) <= offset < chunk.text_offset(offset) + len(chunk.text):
                return chunk
        return None


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    # Drop runs of blank lines; keep single blank lines as paragraph marks.
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            out.append(line)
            blanks = 0
        else:
            blanks += 1
            if blanks <= 1:
                out.append("")
    return _MULTINL_RE.sub("\n\n", "\n".join(out)).strip()


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if not text:
        return []
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to break on a paragraph or line boundary; a chunk that
            # ends mid-table-row reads to the model as a truncated table.
            window = text.rfind("\n", start + size // 2, end)
            if window == -1:
                window = text.rfind(" ", start + size // 2, end)
            if window != -1:
                end = window + 1
        pieces.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def _selectolax():
    try:
        from selectolax.parser import HTMLParser  # noqa: F401

        return HTMLParser
    except Exception:  # pragma: no cover - optional at runtime
        return None


def html_to_text(html: str, base_url: str | None = None) -> tuple[str, str | None, list[tuple[str, str]]]:
    """Return ``(text, title, links)``.

    ``links`` is ``(anchor_text, absolute_url)`` and is what ``discover``
    walks. Dropping ``<nav>`` and ``<footer>`` first matters: a third of the
    links on a government notice board are navigation, and fetching them all
    would be both rude and useless.
    """
    HTMLParser = _selectolax()
    if HTMLParser is None:  # pragma: no cover - dependency is declared
        raise ExtractionError("selectolax is not installed; cannot parse HTML")

    from urllib.parse import urljoin

    tree = HTMLParser(html)
    for tag in _DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    title = None
    node = tree.css_first("title")
    if node:
        title = _clean_text(node.text()) or None

    links: list[tuple[str, str]] = []
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href:
            continue
        # Every kind of whitespace, not just runs of spaces: a multi-line
        # anchor in an HTML notice is line-wrapped markup, not two lines of
        # title, and a title with newlines in it sorts and displays badly.
        anchor = " ".join(node.text().split())[:200]
        links.append((anchor, urljoin(base_url, href) if base_url else href))

    # Tables are the densest part of a notice: a fee grid or a date table.
    # Render rows as " | "-joined cells so column membership survives.
    for table in tree.css("table"):
        rows: list[str] = []
        for tr in table.css("tr"):
            cells = [_clean_text(td.text()) for td in tr.css("th,td")]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        rendered = "\n".join(rows)
        if rendered:
            # Two newlines each side. A table is a block, and gluing it
            # onto the preceding paragraph makes "Fee | Amount" read as
            # prose, which is the difference between a stored fee and a
            # fee clause glued to a heading.
            table.replace_with("\n\n" + rendered + "\n\n")
        else:
            table.decompose()

    text = _clean_text(tree.body.text() if tree.body else tree.text())
    return text, title, links


def extract_html(
    response: Any, settings: Settings, *, collect_links: bool = True
) -> ExtractedDoc:
    html = response.text()
    text, title, links = html_to_text(html, base_url=getattr(response, "final_url", None))
    chunks = [
        Chunk(index=i, text=piece, page=None, section=None, is_ocr=False)
        for i, piece in enumerate(
            _chunk_text(text, settings.chunk_chars, settings.chunk_overlap_chars)
        )
    ]
    doc = ExtractedDoc(
        url=getattr(response, "final_url", "") or getattr(response, "url", ""),
        text=text,
        chunks=chunks,
        media_type="text/html",
        title=title,
        char_count=len(text),
        source_hash=hashlib.sha256(response.content).hexdigest(),
    )
    if collect_links:
        doc.links = links
    return doc


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


def _pymupdf():
    try:
        import pymupdf  # noqa: F401

        return pymupdf
    except Exception:
        try:
            import fitz  # type: ignore  # the older import name

            return fitz
        except Exception as exc:  # pragma: no cover
            raise ExtractionError(f"pymupdf is not importable: {exc}") from exc


def pdf_page_texts(content: bytes) -> list[str]:
    """Per-page text from a PDF's text layer, in page order."""
    pymupdf = _pymupdf()
    doc = pymupdf.open(stream=content, filetype="pdf")
    try:
        return [page.get_text("text") or "" for page in doc]
    finally:
        doc.close()


def _render_page_png(content: bytes, page_number: int, dpi: int = 300) -> bytes:
    pymupdf = _pymupdf()
    doc = pymupdf.open(stream=content, filetype="pdf")
    try:
        page = doc[page_number]
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return pix.tobytes("png")
    finally:
        doc.close()


def _ocr_image_bytes(png: bytes, settings: Settings) -> str:
    """OCR one rendered page.

    ``ocrmypdf`` first, because it produces a real text layer with word
    positions that survive re-extraction; ``pytesseract`` as the fallback for
    when the binary is missing. psm 6 ("a single uniform block of text") is
    the right guess for a scanned notice: notices are dense tables, and the
    default psm 3 hallucinates columns.
    """
    if shutil.which("ocrmypdf"):
        try:
            return _ocr_via_ocrmypdf(png, settings)
        except (ExtractionError, OSError, subprocess.TimeoutExpired):
            log.warning("ocrmypdf failed on a page; trying pytesseract")
    try:
        import pytesseract
    except Exception as exc:
        raise ExtractionError(
            f"no OCR path available: pytesseract not importable ({exc}) and "
            "ocrmypdf is not on PATH"
        ) from exc
    image = _open_png(png)
    return pytesseract.image_to_string(image, lang=settings.ocr_langs, config="--psm 6")


def _ocr_via_ocrmypdf(png: bytes, settings: Settings) -> str:
    """OCR a single page image by wrapping it in a one-page PDF."""
    with tempfile.TemporaryDirectory(prefix="examhub-ocr-") as tmp:
        src = Path(tmp) / "page.png"
        src.write_bytes(png)
        out = Path(tmp) / "out.pdf"
        cmd = [
            "ocrmypdf",
            "--force-ocr",   # the page is an image; --skip-text would conflict
            "-l",
            settings.ocr_langs,
            "--output-type",
            "pdf",
            "--optimize",
            "0",
            "--quiet",
            "--jobs",
            "4",
            str(src),
            str(out),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("ocrmypdf failed (%s); falling back to pytesseract", exc)
            raise
        if proc.returncode != 0 or not out.exists():
            log.warning("ocrmypdf exit %s: %s", proc.returncode, proc.stderr[:400])
            raise ExtractionError("ocrmypdf did not produce output")
        return "\n".join(pdf_page_texts(out.read_bytes()))


def _open_png(png: bytes):
    from PIL import Image

    return Image.open(io.BytesIO(png))


def ocr_pdf(content: bytes, settings: Settings, *, max_pages: int | None = None) -> tuple[list[str], str, list[str]]:
    """OCR a scanned PDF page by page.

    Returns ``(page_texts, engine, warnings)``. Page-by-page rather than
    whole-document because a 90-page scanned notice at 300 dpi is 90 renders
    and a lot of RAM, and because a page that fails must not lose the other
    89.
    """
    limit = settings.ocr_max_pages if max_pages is None else max_pages
    pymupdf = _pymupdf()
    doc = pymupdf.open(stream=content, filetype="pdf")
    total = doc.page_count
    doc.close()

    warnings: list[str] = []
    if total > limit:
        warnings.append(
            f"OCR stopped after {limit} of {total} pages: the rest of this "
            "document is un-extracted, so nothing from it can be stored"
        )
    engine = shutil.which("ocrmypdf") and "ocrmypdf+tesseract" or "pytesseract"
    pages: list[str] = []
    for number in range(min(total, limit)):
        try:
            png = _render_page_png(content, number)
            pages.append(_clean_text(_ocr_image_bytes(png, settings)))
        except Exception as exc:
            warnings.append(f"page {number + 1}: OCR failed ({exc})")
            pages.append("")
    return pages, engine, warnings


def pdf_pages(
    content: bytes, settings: Settings, *, force_ocr: bool = False
) -> tuple[list[str], bool, str | None, list[str]]:
    """Per-page text, OCR'd where the text layer is missing.

    Returns ``(pages, is_scan, ocr_engine, warnings)``. See :func:`extract_pdf`
    for when a document counts as a scan.
    """
    warnings: list[str] = []
    pages: list[str] = []
    try:
        pages = pdf_page_texts(content)
    except Exception as exc:
        if not force_ocr:
            raise ExtractionError(f"could not read PDF text layer: {exc}") from exc
        warnings.append(f"text layer unreadable ({exc}); went straight to OCR")

    total_chars = sum(len(p) for p in pages)
    per_page_low = bool(pages) and all(
        len(p) < settings.ocr_page_char_threshold for p in pages
    )
    # A scan is a document with *no* usable text, not a short one. A
    # one-page notice whose text layer is 150 characters is a real notice
    # with a real text layer, and sending it to OCR replaces a perfect
    # transcription with a guess. The whole-document threshold therefore
    # only applies when every page is already thin.
    essentially_empty = total_chars < 40
    is_scan = force_ocr or essentially_empty or (
        per_page_low and total_chars < settings.ocr_char_threshold
    )

    engine: str | None = None
    if is_scan:
        if not settings.enable_ocr:
            warnings.append(
                f"no usable text layer ({total_chars} chars) and OCR is disabled: "
                "nothing can be extracted from this document"
            )
            pages = pages or [""]
        else:
            ocr_pages, engine, ocr_warnings = ocr_pdf(content, settings)
            warnings.extend(ocr_warnings)
            # Prefer OCR wherever the text layer was thin; keep real text
            # where it existed so a mixed document does not get worse.
            pages = [
                (ocr if len(existing) < settings.ocr_page_char_threshold else existing)
                for existing, ocr in zip(
                    pages or [""] * len(ocr_pages), ocr_pages + [""] * max(0, len(pages) - len(ocr_pages))
                )
            ]
            if len(ocr_pages) < len(pages):
                pages = pages[: len(ocr_pages)]
    else:
        pages = [_clean_text(p) for p in pages]

    return pages, is_scan, engine, warnings


def extract_pdf(
    content: bytes,
    url: str,
    settings: Settings,
    *,
    force_ocr: bool = False,
) -> ExtractedDoc:
    """PDF -> text, falling back to OCR when there is no usable text layer.

    A PDF is treated as a scan when it yields fewer than
    ``settings.ocr_char_threshold`` characters in total, or when every page
    is under ``settings.ocr_page_char_threshold``. That catches the common
    case of a notice whose first page is a scanned cover letter and whose
    remaining pages are real text.
    """
    pages, is_scan, engine, warnings = pdf_pages(content, settings, force_ocr=force_ocr)

    text = _clean_text("\n\n".join(p for p in pages))
    chunks: list[Chunk] = []
    index = 0
    for number, page_text in enumerate(pages, start=1):
        for piece in _chunk_text(page_text, settings.chunk_chars, settings.chunk_overlap_chars):
            chunks.append(
                Chunk(
                    index=index,
                    text=piece,
                    page=number,
                    section=_nearest_heading(page_text, piece),
                    is_ocr=is_scan,
                )
            )
            index += 1

    return ExtractedDoc(
        url=url,
        text=text,
        chunks=chunks,
        media_type="application/pdf",
        is_ocr=is_scan,
        ocr_engine=engine,
        pages=len(pages),
        char_count=len(text),
        warnings=warnings,
        source_hash=hashlib.sha256(content).hexdigest(),
    )


def _nearest_heading(page_text: str, piece: str) -> str | None:
    """A short label for a chunk, from the nearest numbered clause or title.

    Government notices number everything ("1. VACANCIES", "5. FEE"). Picking
    that up gives the reviewer, and the model prompt, a handle on where in the
    document a claim lives.
    """
    if not page_text:
        return None
    head = page_text[:4000]
    # The numbered-clause pattern is case-insensitive; the ALLCAPS one is
    # not, and has to be. Case-insensitively it matched any run of five
    # letters and spaces, so every page reported a "heading" of its own
    # first paragraph and the reviewer learned nothing from the label.
    patterns = (
        r"(?im)^\s*(\d{1,2}(?:\.\d{1,2})*)[.)]?\s+([A-Z][A-Za-z/ &()-]{3,60})\s*$",
        r"(?m)^\s*([A-Z][A-Z0-9 /&-]{5,60})\s*$",
        r"(?im)^\s*(SECTION\s+\d+[^\n]{0,60})",
    )
    best: tuple[int, str] | None = None
    for pattern in patterns:
        for match in re.finditer(pattern, head):
            label = " ".join(match.group(0).split())[:80]
            if best is None or match.start() < best[0]:
                best = (match.start(), label)
        if best is not None:
            return best[1]
    return None


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def looks_like_pdf(content: bytes, content_type: str = "") -> bool:
    """Is this a PDF?

    The magic bytes come first because several government hosts serve a PDF
    from a URL ending in ``.aspx`` and an HTML page from a URL ending in
    ``.pdf``, and guessing from the content type alone gets that backwards
    often enough to matter.

    The content-type check looks for "pdf" rather than ".pdf" because the
    real header is ``application/pdf``, which contains no dot.
    """
    if content[:5] == b"%PDF-":
        return True
    return "pdf" in (content_type or "").lower()


def extract_bytes(
    content: bytes,
    url: str,
    settings: Settings,
    content_type: str = "",
    *,
    force_ocr: bool = False,
    collect_links: bool = False,
) -> ExtractedDoc:
    """Route to the right extractor based on what the bytes actually are.

    The magic-bytes check comes first: several government hosts serve a PDF
    from a URL ending in ``.aspx`` and vice versa, and guessing from the
    content type alone gets that backwards more often than you would think.
    """
    if looks_like_pdf(content, content_type):
        return extract_pdf(content, url, settings, force_ocr=force_ocr)
    if content[:8] == b"\x89PNG\r\n\x1a\n" or content[:3] == b"\xff\xd8\xff":
        return extract_image(content, url, settings)
    return _extract_html_response(content, url, settings, collect_links=collect_links)


def _extract_html_response(
    content: bytes, url: str, settings: Settings, *, collect_links: bool = False
) -> ExtractedDoc:
    class _Resp:  # minimal shim so the HTML path reuses CachedResponse.text()
        def __init__(self, content: bytes, url: str) -> None:
            self.content = content
            self.url = url
            self.final_url = url
            self._text: str | None = None
            self.content_type = "text/html"

        def text(self) -> str:
            if self._text is None:
                from .http import _encodings

                for encoding in _encodings(self.content_type, self.content):
                    try:
                        self._text = self.content.decode(encoding)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                else:
                    self._text = self.content.decode("utf-8", errors="replace")
            return self._text

    return extract_html(_Resp(content, url), settings, collect_links=collect_links)


def extract_image(content: bytes, url: str, settings: Settings) -> ExtractedDoc:
    """A bare image (a scanned notice board photo, a WhatsApp-forwarded page)."""
    warnings: list[str] = []
    if not settings.enable_ocr:
        raise ExtractionError("image with OCR disabled")
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover
        raise ExtractionError(f"pytesseract unavailable: {exc}") from exc
    from PIL import Image

    image = Image.open(io.BytesIO(content))
    text = _clean_text(pytesseract.image_to_string(image, lang=settings.ocr_langs, config="--psm 6"))
    chunks = [
        Chunk(index=i, text=piece, page=None, section=None, is_ocr=True)
        for i, piece in enumerate(_chunk_text(text, settings.chunk_chars, settings.chunk_overlap_chars))
    ]
    return ExtractedDoc(
        url=url,
        text=text,
        chunks=chunks,
        media_type="image",
        is_ocr=True,
        ocr_engine="pytesseract",
        char_count=len(text),
        warnings=warnings,
        source_hash=hashlib.sha256(content).hexdigest(),
    )


def extract_response(response: Any, settings: Settings, *, force_ocr: bool = False) -> ExtractedDoc:
    return extract_bytes(
        response.content,
        getattr(response, "final_url", "") or getattr(response, "url", ""),
        settings,
        content_type=getattr(response, "content_type", ""),
        force_ocr=force_ocr,
    )
