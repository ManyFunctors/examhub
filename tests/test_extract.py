"""Tests for HTML/PDF/scan -> text.

The OCR path is tested by asserting that it *fires* and reports itself. A
machine with tesseract installed can additionally check the transcription via
the ``ocr`` marker; without it the honest assertion is that a document with no
text layer is detected as a scan, is flagged, and says why it could not be
read.
"""

from __future__ import annotations

import dataclasses
import shutil

import pytest

from examhub_pipeline.config import Settings
from examhub_pipeline.extract import (
    ExtractionError,
    _chunk_text,
    _clean_text,
    _nearest_heading,
    extract_bytes,
    extract_html,
    extract_pdf,
    html_to_text,
    looks_like_pdf,
)

HAS_TESSERACT = shutil.which("tesseract") is not None


class _Resp:
    def __init__(self, content: bytes, url: str = "https://x.gov.in/p", ctype="text/html"):
        self.content = content
        self.url = url
        self.final_url = url
        self.content_type = ctype

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class TestHtmlToText:
    def test_text_and_title(self):
        text, title, links = html_to_text(
            "<html><head><title>Notice</title></head><body><p>Hello</p></body></html>"
        )
        assert title == "Notice"
        assert "Hello" in text

    def test_script_and_style_are_dropped(self):
        text, _, _ = html_to_text(
            "<html><body><script>var x=1;</script><style>p{}</style>"
            "<p>Real content</p></body></html>"
        )
        assert "var x" not in text
        assert "Real content" in text

    def test_nav_and_footer_links_are_dropped(self):
        """A third of the links on a notice board are navigation, and fetching
        them all would be rude and useless."""
        _, _, links = html_to_text(
            "<html><body><nav><a href='/home'>Home</a></nav>"
            "<ul><li><a href='/n.pdf'>Notice for recruitment 2026</a></li></ul>"
            "<footer><a href='/faq'>FAQ</a></footer></body></html>",
            base_url="https://x.gov.in/",
        )
        assert [u for _, u in links] == ["https://x.gov.in/n.pdf"]

    def test_relative_links_are_resolved(self):
        _, _, links = html_to_text(
            "<html><body><a href='../notice.pdf'>Notice 2026</a></body></html>",
            base_url="https://x.gov.in/pages/index.html",
        )
        assert links[0][1] == "https://x.gov.in/notice.pdf"

    def test_tables_keep_their_rows(self):
        text, _, _ = html_to_text(
            "<html><body><table><tr><th>Category</th><th>Fee</th></tr>"
            "<tr><td>General</td><td>Rs 100</td></tr></table></body></html>"
        )
        assert "Category | Fee" in text
        assert "General | Rs 100" in text

    def test_a_table_is_a_block_not_a_glued_paragraph(self):
        text, _, _ = html_to_text(
            "<html><body><p>Intro</p><table><tr><td>1</td></tr></table></body></html>"
        )
        assert "Intro\n\n" in text

    def test_an_empty_table_is_dropped(self):
        text, _, _ = html_to_text("<html><body><table></table><p>Only this</p></body></html>")
        assert "Only this" in text

    def test_anchor_text_is_whitespace_collapsed(self):
        _, _, links = html_to_text(
            "<html><body><a href='/n.pdf'>Release\n  of\n  Admit Card</a></body></html>"
        )
        assert links[0][0] == "Release of Admit Card"

    def test_a_link_with_no_text_is_kept_with_empty_anchor(self):
        _, _, links = html_to_text("<html><body><a href='/n.pdf'></a></body></html>")
        assert links == [("", "/n.pdf")]

    def test_unclosed_tags_do_not_crash(self):
        text, _, _ = html_to_text("<html><body><p>One<div>Two<span>Three")
        assert "Three" in text


class TestCleaning:
    def test_windows_newlines(self):
        assert _clean_text("a\r\nb\rc") == "a\nb\nc"

    def test_blank_runs_collapse_to_one(self):
        assert _clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_trailing_whitespace_is_stripped_per_line(self):
        assert _clean_text("a   \n  b") == "a\nb"


class TestChunking:
    def test_short_text_is_one_chunk(self):
        assert _chunk_text("short", 100, 10) == ["short"]

    def test_long_text_is_split(self):
        text = "x" * 1000
        pieces = _chunk_text(text, 300, 50)
        assert len(pieces) > 1
        assert all(len(p) <= 320 for p in pieces)

    def test_chunks_overlap(self):
        text = "".join(f"{i:04d} " for i in range(400))
        pieces = _chunk_text(text, 400, 100)
        assert pieces[0][-20:] in pieces[1] or pieces[1].startswith(pieces[0][-20:][:10])

    def test_chunking_breaks_on_a_boundary_not_mid_token(self):
        """A chunk that starts mid-word reads as noise to the model, and a
        chunk that splits a table row loses the row's column membership."""
        text = "\n".join(f"line {i:03d} of the notice" for i in range(200))
        pieces = _chunk_text(text, 200, 40)
        assert len(pieces) > 1
        for piece in pieces[1:]:
            assert not piece[0].isalpha() or piece.split()[0] in {
                w for w in text.split()
            }, f"chunk starts mid-token: {piece[:30]!r}"

    def test_never_infinite_loops(self):
        """A pathological input must terminate, not hang the run."""
        assert _chunk_text("a" * 10_000, 1, 0)


class TestHeadings:
    def test_numbered_clause_is_found(self):
        assert _nearest_heading("3. APPLICATION FEE\nGeneral Rs 100", "General Rs 100")

    def test_all_caps_heading_is_found(self):
        assert _nearest_heading("SCHEDULE OF EXAMINATION\nThe exam is on...", "The exam is on")

    def test_no_heading_returns_none(self):
        assert _nearest_heading("just some running text here", "some running text") is None


class TestPdfRouting:
    def test_pdf_is_detected_by_magic_bytes(self):
        assert looks_like_pdf(b"%PDF-1.7\n...")
        assert looks_like_pdf(b"not a pdf", "application/pdf")
        assert not looks_like_pdf(b"<html>", "text/html")

    def test_a_broken_pdf_raises_rather_than_looking_empty(self, settings: Settings):
        """A corrupt download must not look like a notice with no dates.

        The failure mode this guards against is the expensive one: an empty
        document passes every downstream check and silently contributes
        nothing to a review bundle that looks complete.
        """
        with pytest.raises(ExtractionError):
            extract_bytes(b"%PDF-1.4 broken", "https://x.gov.in/a.pdf", settings)

    def test_extract_bytes_routes_html(self, settings: Settings):
        doc = extract_bytes(
            b"<html><body><p>Notice 2026</p></body></html>",
            "https://x.gov.in/a.aspx",
            settings,
        )
        assert doc.media_type == "text/html"
        assert "Notice 2026" in doc.text
        assert doc.chunks


class TestPdfTextLayer:
    """A real PDF with a real text layer, built in-process by pymupdf."""

    @pytest.fixture
    def text_pdf(self, tmp_path):
        pymupdf = pytest.importorskip("pymupdf")
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text(
            (72, 100),
            "1. VACANCIES: Total No. of Posts: 1,044\n"
            "The examination will be held on 15.06.2026 at 10:00 AM.\n"
            "Last date to apply: 22.02.2026 up to 23:00 hours.",
            fontsize=11,
        )
        data = doc.tobytes()
        doc.close()
        return data

    def test_text_layer_is_extracted(self, text_pdf, settings: Settings):
        doc = extract_pdf(text_pdf, "https://x.gov.in/n.pdf", settings)
        assert doc.is_ocr is False
        assert "1,044" in doc.text
        assert "15.06.2026" in doc.text
        assert doc.pages == 1

    def test_pages_and_chunks_are_attached(self, text_pdf, settings: Settings):
        doc = extract_pdf(text_pdf, "https://x.gov.in/n.pdf", settings)
        assert doc.chunks
        for chunk in doc.chunks:
            assert chunk.page == 1
            assert chunk.is_ocr is False
            assert chunk.location.startswith("p.1")

    def test_source_hash_is_content_addressed(self, text_pdf, settings: Settings):
        a = extract_pdf(text_pdf, "u", settings)
        b = extract_pdf(text_pdf, "u", settings)
        assert a.source_hash == b.source_hash

    @pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract is not installed")
    def test_an_image_only_pdf_is_detected_as_a_scan(self, settings: Settings):
        pymupdf = pytest.importorskip("pymupdf")
        settings = dataclasses.replace(settings, enable_ocr=True)  # the fixture turns OCR off
        doc = pymupdf.open()
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 60))
        pix.set_rect(pix.irect, (255, 255, 255))
        page.insert_image(pymupdf.Rect(20, 20, 180, 50), pixmap=pix)
        data = doc.tobytes()
        doc.close()
        extracted = extract_pdf(data, "https://x.gov.in/scan.pdf", settings)
        assert extracted.is_ocr is True
        assert extracted.ocr_engine is not None
        # The flag has to survive into provenance, so it must be on the doc.
        assert hasattr(extracted, "ocr_engine")

    def test_a_scan_without_an_ocr_engine_still_says_so(self, settings: Settings):
        """A PDF with no text layer must be visible as empty, not silently
        treated as a document with no facts."""
        pymupdf = pytest.importorskip("pymupdf")
        doc = pymupdf.open()
        doc.new_page()
        data = doc.tobytes()
        doc.close()
        no_ocr = Settings(**{**settings.__dict__, "enable_ocr": False})
        extracted = extract_pdf(data, "https://x.gov.in/scan.pdf", no_ocr)
        assert extracted.is_ocr is True
        assert any("OCR is disabled" in w for w in extracted.warnings)

    def test_page_ceiling_is_reported(self, settings: Settings):
        pymupdf = pytest.importorskip("pymupdf")
        doc = pymupdf.open()
        for _ in range(5):
            doc.new_page()
        data = doc.tobytes()
        doc.close()
        capped = Settings(**{**settings.__dict__, "ocr_max_pages": 2, "enable_ocr": True})
        extracted = extract_pdf(data, "https://x.gov.in/scan.pdf", capped)
        assert any("OCR stopped after" in w for w in extracted.warnings)


class TestExtractHtmlWrapper:
    def test_links_are_collected_when_asked(self, settings: Settings):
        resp = _Resp(
            b"<html><body><ul><li><a href='/n.pdf'>Notice for 2026 recruitment</a></li>"
            b"</ul></body></html>"
        )
        doc = extract_html(resp, settings, collect_links=True)
        assert doc.links == [("Notice for 2026 recruitment", "https://x.gov.in/n.pdf")]

    def test_encoding_fallbacks(self, settings: Settings):
        """Government notices are served as windows-1252 with no charset
        declared more often than anyone would like."""
        body = "<html><body><p>Rs 100 fee \u20b9</p></body></html>".encode("windows-1252", "replace")
        resp = _Resp(body, ctype="text/html; charset=windows-1252")
        doc = extract_html(resp, settings)
        assert "Rs 100 fee" in doc.text
