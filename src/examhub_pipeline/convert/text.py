"""Page text and tables for every document fetched by ``scrapy crawl records``.

Writes ``work/records/<slug>/<file>.json`` beside each fetched file:
``{"url", "kind", "pages": [str], "structure": documents.structure() output, "warnings": [...]}``. A file already converted is skipped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import documents, extract
from ..config import Settings

log = logging.getLogger(__name__)
RECORDS = Path("work/records")


def convert_file(path: Path, row: dict, settings: Settings) -> dict:
    content = path.read_bytes()
    out = {"url": row["url"], "role": row["role"], "kind": row["kind"], "pages": [], "tables": [],
           "ocr": None, "warnings": []}
    if row["kind"] == "html":
        text, title, links = extract.html_to_text(content.decode("utf-8", "replace"), row["url"])
        out["pages"] = [text]
        out["title"] = title
        out["links"] = [{"text": t, "url": u} for t, u in links if u.lower().split("?")[0].endswith(".pdf")]
        return out
    role = row["role"].split(":", 3)
    notice = {"url": row["url"], "title": role[3] if role[0] == "notice" and len(role) > 3 else "",
              "doc_type": role[1] if role[0] == "notice" else None}
    out["structure"] = documents.structure(content, notice, settings)
    try:  # the text layer only; structure() has already OCR'd a scan
        out["pages"] = extract.pdf_page_texts(content)
    except Exception as exc:
        out["warnings"].append(f"no text layer: {exc}")
    return out

def run(only: set[str] | None = None, force: bool = False) -> None:
    settings = Settings()
    for manifest in sorted(RECORDS.glob("*/manifest.jsonl")):
        slug = manifest.parent.name
        if only and slug not in only:
            continue
        for line in manifest.open(encoding="utf-8"):
            row = json.loads(line)
            if row.get("status") != "ok":
                continue
            src = manifest.parent / row["file"]
            dst = src.with_suffix(".json")
            if dst.exists() and not force:
                continue
            try:
                data = convert_file(src, row, settings)
            except Exception as exc:  # one bad PDF must not stop the rest
                data = {"url": row["url"], "role": row["role"], "kind": row["kind"], "pages": [],
                        "tables": [], "ocr": None, "warnings": [f"unreadable: {exc}"[:300]]}
            dst.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            log.info("%s %s: %d pages, %d tables", slug, row["file"], len(data["pages"]), len(data["tables"]))
