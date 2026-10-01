"""Feed adapters: turn one fetched index page into notice rows.

Pure functions over (feed config, page URL, page body). No network, no
Scrapy, so every adapter is testable against a saved page. The set is fixed
and small on purpose -- a body is described by filling in an adapter's
parameters in the catalogue, never by writing a new adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit

from parsel import Selector

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

DOC_EXT = re.compile(r"\.(pdf|docx?|xlsx?|jpe?g|png|zip)(?:[?#]|$)", re.I)

_SKIP_SCHEMES = ("mailto:", "javascript:", "tel:", "#", "data:")

#: Anchor text that says nothing about the document. The row text is used
#: instead when a link is labelled like this.
UNINFORMATIVE = re.compile(
    r"^\s*(read\s*more|click\s*here|download|view|details?|here|link|pdf|"
    r"document(\s*(notice|notification|file))?|notice|notification|advertisement|"
    r"file|open|more|new|english|hindi|कृपया.*|डाउनलोड|देखें|"
    r"\(?\d+(\.\d+)?\s*(kb|mb)\)?)\s*[.>»]*\s*$",
    re.I,
)

#: Navigation and boilerplate. Applied only when a feed sets no `include`.
NAV = re.compile(
    r"^\s*(home|about( us)?|contact( us)?|sitemap|site map|faq s?|help|login|log in|"
    r"sign in|register|feedback|disclaimer|privacy policy|terms.*|copyright.*|"
    r"accessibility.*|screen reader.*|skip to .*|rti|tenders?|gallery|photo gallery|"
    r"who'?s who|organi[sz]ation chart|citizen charter|hyperlink policy|"
    r"website policies|help desk|archives?|what'?s new|news|events|go to top|top|"
    r"back|previous|next|\d+|«|»|‹|›|first|last)\s*$",
    re.I,
)

NOTICE_WORDS = re.compile(
    r"\b(notification|notice|advertisement|advt|vacanc|recruit|examination|exam\b|"
    r"corrigendum|addendum|admit|hall ?ticket|call letter|answer ?key|result|"
    r"merit list|select list|shortlist|cut ?off|schedule|calendar|syllabus|"
    r"interview|document verification|walk[- ]in|counsell?ing|admission|"
    r"entrance|test\b|posts?\b|bharti|bharati|bharthi|bulletin|prospectus)",
    re.I,
)

#: First match wins, so the narrow types (a walk-in, a scrutiny list) come before the broad ones.
_DOC_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("walk_in", re.compile(r"walk\s*-?\s*in", re.I)),
    # a title that says it is the advertisement stays one, whatever else it mentions
    ("notification", re.compile(r"detailed\s+advertisement|\badvertisement\s+for\b|recruitment\s+notification"
                                r"|notification\s+for\s+(?:the\s+)?(?:post|recruitment)", re.I)),
    ("application_status", re.compile(r"(?:in)?eligib(?:le|ility)\s+(?:and\s+(?:in)?eligible\s+)?(?:candidates?\s+)?list|list\s+of\s+(?:in)?eligible"
                                      r"|scrutiny|applic?n?\.?\s*status|rejected\s+(?:applications?|candidates?)|rejection\s+list"
                                      r"|provisionally\s+(?:admitted|rejected)|status\s+of\s+applications?", re.I)),
    ("counselling", re.compile(r"counsell?ing|seat\s*matrix|seat\s*allot|allotment|mop\s*-?\s*up|stray\s*vacanc|choice\s*filling|upgradation", re.I)),
    ("corrigendum", re.compile(r"corrigend|addend|errat|amendment|revised\s+(notice|notification|advertisement)", re.I)),
    ("answer_key", re.compile(r"answer\s*-?\s*key|model\s*answer|key\s*answer|provisional\s*key|final\s*key|objection", re.I)),
    ("admit_card", re.compile(r"admit\s*card|hall\s*-?\s*ticket|call\s*letter|e-?admit|admission\s*certificate|city\s*(intimation|slip)|exam(ination)?\s*city", re.I)),
    ("result", re.compile(r"\bresults?\b|merit\s*list|select(ion)?\s*list|shortlist|cut\s*-?\s*off|marks\s*of|score\s*card|rank\s*list|qualified\s*candidates|final\s*selection", re.I)),
    ("calendar", re.compile(r"calend[ae]r|tentative\s*(schedule|programme)|annual\s*(schedule|programme)|exam(ination)?\s*plan", re.I)),
    ("schedule", re.compile(r"schedule|time\s*-?\s*table|date\s*sheet|exam(ination)?\s*date|interview|postpone|reschedul"
                            r"|physical\s*(?:efficiency|measurement|standard)?\s*test|\b(?:pet|pst|pmt)\b|document\s*verification|\bdv\b|skill\s*test|typing\s*test", re.I)),
    ("press_release", re.compile(r"press\s*(release|note)|extension|extended|public\s*notice", re.I)),
    ("syllabus", re.compile(r"syllabus|scheme\s+of\s+exam", re.I)),
    ("notification", re.compile(r"notification|gazette|advertisement|advt|recruitment|vacanc|information\s*bulletin|brochure|prospectus|detailed\s*notice|notice\s*of\s*exam", re.I)),
)


def classify_doc_type(title: str, url: str = "") -> str:
    hay = f"{title} {url.rsplit('/', 1)[-1]}"
    for name, pat in _DOC_TYPES:
        if pat.search(hay):
            return name
    return "other"


#: Query parameters that sign a URL rather than name a document: S3 / GCS
#: presigned URLs and Azure SAS tokens. They change on every page load (AIIMS
#: serves every PDF this way), so they are not part of a notice's identity.
_SIGNING = re.compile(
    r"^(x-amz-[a-z-]+|x-goog-[a-z-]+|awsaccesskeyid|signature|expires|googleaccessid|"
    r"response-content-(type|disposition)|sv|se|sr|sp|sig|st|spr|skoid|sktid|skt|ske|sks|skv)$", re.I)
_SIGNED = re.compile(r"(?:^|&)(?:x-amz-signature|x-goog-signature|signature|sig)=", re.I)


def canonical_url(url: str) -> str:
    """Lower-case scheme and host, drop the fragment, a default port and
    URL-signing parameters. Nothing else: query strings are identity on
    ASP.NET sites."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and not ((parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    query = parts.query
    # Only a URL that carries a signature is stripped, so an ordinary
    # site's "?sp=2" is left alone.
    if _SIGNED.search(query):
        query = "&".join(kv for kv in query.split("&") if not _SIGNING.match(kv.split("=", 1)[0]))
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def notice_id(url: str, title: str | None = None) -> str:
    """sha256 of the canonical URL; with ``title``, of URL and title. The
    second form is for feeds with ``identity = "url_title"``: update lists
    that reuse one URL per category and change only the dated title."""
    key = canonical_url(url) + (f"\n{title}" if title else "")
    return hashlib.sha256(key.encode()).hexdigest()


_SIZE = re.compile(r"\(?\s*\d+(\.\d+)?\s*(kb|mb|kib|mib|bytes)\s*\)?|\b(click\s*here|new!?|pdf\s*icon)\b"
    r"|\b(pdf\s*file|external\s*site|link)\s*that\s*opens\s*in\s*a\s*(new\s*)?window\.?", re.I)


def clean(text: str | None) -> str:
    """Collapse whitespace and drop the file-size and "click here" noise that
    notice boards append to titles."""
    # Whitespace first: _SIZE starts with ``\s*``, which is quadratic on the
    # thousand-space runs some table layouts are made of.
    text = " ".join((text or "").split())
    text = _SIZE.sub(" ", text)
    return " ".join(text.split()).strip(" \t\r\n-–|:•·")


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_D_NUM = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2}|\d{2})(?!\d)")
_D_ISO = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)")
_D_TXT = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s.,-]*([A-Za-z]{3,9})[\s.,'-]*(20\d{2})(?!\d)")
_D_TXT2 = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})(?!\d)")


def parse_date(text: str) -> str | None:
    """A published date printed next to a notice. Day-first, as Indian
    notices are. Returns ISO or None; never guesses a missing day."""
    if not text:
        return None
    for rx, order in ((_D_ISO, "ymd"), (_D_NUM, "dmy"), (_D_TXT, "dMy"), (_D_TXT2, "Mdy")):
        m = rx.search(text)
        if not m:
            continue
        try:
            if order == "ymd":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif order == "dmy":
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
                y += 2000 if y < 100 else 0
            elif order == "dMy":
                d, mo, y = int(m[1]), _MONTHS.get(m[2][:3].lower(), 0), int(m[3])
            else:
                mo, d, y = _MONTHS.get(m[1][:3].lower(), 0), int(m[2]), int(m[3])
            return date(y, mo, d).isoformat()
        except (ValueError, KeyError):
            continue
    return None


#: Where a title states its own issue date: a leading date ("05-02-2025 - Result ..."), or one
#: after "dated"/"dt." ("Result dated 15.03.2023"). A date elsewhere in a title is often an
#: event ("holiday on 5th July"), so it is not taken.
_TITLE_STAMP = re.compile(r"^\s*(?P<a>[\dA-Za-z.,/ -]{6,20}?)\s*[-–:|]\s|\b(?:dated|dt\.?)\s*[:-]?\s*(?P<b>[\dA-Za-z.,/ -]{6,20})", re.I)
#: A date in the file name: "Notice25Sep2024a.pdf", "result_2024-03-15.pdf".
_URL_STAMP = re.compile(r"(?<!\d)(\d{1,2}[A-Za-z]{3,9}\d{4}|\d{2}[._-]\d{2}[._-]20\d{2}|20\d{2}-\d{2}-\d{2})(?!\d)")

#: A file name about an event ("Exam-Date-21-08-2016", "GS_B_01Dec2020") carries that date.
_URL_EVENT = re.compile(r"exam|held|date|series|_[a-d]_|key|test", re.I)


def stamped_date(title: str, url: str, today: str | None = None) -> tuple[str, str] | None:
    """(ISO date, "title" or "url") when a notice names its own issue date, else None.
    Never a date after ``today``, which is an event, not an issue date."""
    today = today or date.today().isoformat()
    m = _TITLE_STAMP.search(title or "")
    name = urlsplit(url or "").path.rsplit("/", 1)[-1]  # the query is a script's, not the file's
    for text, source in ((m and (m["a"] or m["b"]), "title"),
                         ("" if _URL_EVENT.search(name) else " ".join(_URL_STAMP.findall(name)), "url")):
        text = re.sub(r"(\d)([A-Za-z]{3,9})(\d{4})", r"\1 \2 \3", text or "").replace("_", "-")
        iso = parse_date(text)
        if iso and "2000-01-01" <= iso <= today:
            return iso, source
    return None


def _keep(feed: dict, title: str, url: str) -> bool:
    """Include/exclude, plus a default filter when the feed gives none.

    A feed with an ``item_selector`` has already said "every row here is a
    notice", so only navigation words are dropped. An unscoped feed reads a
    whole page, so a link must also look like a document or name itself as
    a notice."""
    hay = f"{title} {url}"
    inc = feed.get("include")
    if inc:
        if not re.search(inc, hay, re.I):
            return False
    else:
        if NAV.match(title) and not DOC_EXT.search(url):
            return False
        if not feed.get("item_selector") and not (
            DOC_EXT.search(url) or NOTICE_WORDS.search(title) or NOTICE_WORDS.search(url)
        ):
            return False
    exc = feed.get("exclude")
    if exc and re.search(exc, hay, re.I):
        return False
    return True


def _row(feed: dict, page_url: str, href: str, title: str, published: str | None) -> dict[str, Any]:
    url = canonical_url(urljoin(page_url, href))
    title = title[:500]
    return {
        "id": notice_id(url, title if feed.get("identity") == "url_title" else None),
        "url": url,
        "title": title,
        "published": published,
        "body": feed["body"],
        "feed": feed["id"],
        "doc_type": classify_doc_type(title, url),
    }


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------


#: Links inside these are site chrome, not notices. An ancestor is chrome if
#: it is nav/header/footer/select, or if one of its class or id *tokens*
#: (split on space, "-" and "_") is one of these words. Whole tokens only:
#: "menu-item" and "navbar" count, "home page-template" does not, and
#: <html>/<body> never do.
_CHROME_TAGS = {"nav", "header", "footer", "select"}
_CHROME_TOKENS = {"menu", "menus", "submenu", "megamenu", "nav", "navbar", "navigation",
                  "breadcrumb", "breadcrumbs", "footer", "header", "topbar", "sidebar-menu"}
_TOKEN_SPLIT = re.compile(r"[\s_-]+")


def _is_chrome(el) -> bool:
    if el.tag in _CHROME_TAGS:
        return True
    if el.tag in ("html", "body"):
        return False
    words = set(_TOKEN_SPLIT.split(f"{el.get('class') or ''} {el.get('id') or ''}".lower()))
    return bool(words & _CHROME_TOKENS)


def _chrome_filter(sel):
    """Return ``is_chrome(anchor)`` for one page.

    Chrome is where a site keeps its menus, so it rarely holds most of a
    page's documents. When it does -- a notice board built as a mega-menu, or
    an unclosed ``<header>`` the parser stretched over the whole page -- that
    element is the content, and it is not treated as chrome. The threshold is
    40% of the page's document links."""
    anchors = sel.xpath("//a[@href]")
    docs = [a for a in anchors if DOC_EXT.search(a.attrib.get("href", ""))]
    held: dict[Any, int] = {}
    for a in docs:
        for el in a.root.iterancestors():
            if _is_chrome(el):
                held[el] = held.get(el, 0) + 1
    big = {el for el, n in held.items() if docs and n > 0.4 * len(docs)}

    def check(a) -> bool:
        ancestors = list(a.root.iterancestors())
        if any(el in big for el in ancestors):
            return False  # inside the content, however its items are classed
        return any(_is_chrome(el) for el in ancestors)
    return check


_ROW_XPATH = "ancestor::*[self::li or self::tr or self::p or self::dd or self::dt or self::td or self::div or self::article or self::table]"


def _context(a) -> str:
    """Text of the nearest row-like ancestor that says more than the link
    itself, while still being short enough to be about one notice. "Read
    More" beside a title, and a "Document" link in a one-exam-per-table
    layout, are the two common cases."""
    own = clean(" ".join(a.css("::text").getall()))
    for anc in reversed(a.xpath(_ROW_XPATH)):  # nearest first
        raw = " ".join(" ".join(anc.css("::text").getall()).split())
        if len(raw) > 700:
            return ""
        text = clean(raw)
        if len(text) > len(own) + 8:
            return text if len(text) <= 600 else ""
    return ""


def html_links(feed: dict, page_url: str, body: bytes | str) -> Iterator[dict]:
    sel = Selector(text=body if isinstance(body, str) else body.decode("utf-8", "replace"))
    scoped = bool(feed.get("item_selector"))
    items = sel.css(feed["item_selector"]) if scoped else [sel]
    link_css = feed.get("link_selector") or "a[href]"
    keep_chrome = feed.get("keep_chrome", False)
    in_chrome = _chrome_filter(sel) if not scoped and not keep_chrome else None
    seen: set[str] = set()
    for item in items:
        item_text = clean(" ".join(item.css("::text").getall())) if scoped else ""
        pub_item = None
        if feed.get("date_selector"):
            pub_item = parse_date(clean(" ".join(item.css(feed["date_selector"] + " ::text").getall())))
        elif scoped and len(item_text) <= 400:
            pub_item = parse_date(item_text)
        for a in item.css(link_css):
            href = (a.attrib.get("href") or "").strip()
            if not href or href.lower().startswith(_SKIP_SCHEMES):
                continue
            if in_chrome and in_chrome(a):
                continue
            ctx = item_text if scoped else ""
            if feed.get("title_selector"):
                title = clean(" ".join(item.css(feed["title_selector"] + " ::text").getall()))
            else:
                title = clean(" ".join(a.css("::text").getall())) or clean(a.attrib.get("title"))
                if not title or UNINFORMATIVE.match(title):
                    if not ctx or UNINFORMATIVE.match(ctx) or len(ctx) <= len(title) + 8:
                        ctx = _context(a)
                    title = ctx or title
            if not title or UNINFORMATIVE.match(title):
                # Last resort: the file name, which on most boards encodes
                # the exam and a date (Notif-ESEP-2027-Engl-160926.pdf).
                stem = re.sub(r"\.[a-z0-9]{2,4}$", "", href.split("?")[0].rstrip("/").rsplit("/", 1)[-1], flags=re.I)
                title = f"{title} [{stem}]".strip() if title else stem
            pub = pub_item
            if pub is None and not feed.get("date_selector"):
                pub = parse_date(ctx or _context(a))
            if not _keep(feed, title, href):
                continue
            row = _row(feed, page_url, href, title, pub)
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            yield row


def html_table(feed: dict, page_url: str, body: bytes | str) -> Iterator[dict]:
    """One notice per table row: the first link, the longest non-date cell
    as the title, the first date-looking cell as the published date."""
    sel = Selector(text=body if isinstance(body, str) else body.decode("utf-8", "replace"))
    rows = sel.css(feed.get("item_selector") or "table tr")
    seen: set[str] = set()
    for tr in rows:
        cells = [clean(" ".join(td.css("::text").getall())) for td in tr.css("td, th")]
        links = tr.css(feed.get("link_selector") or "a[href]")
        if not links:
            continue
        href = (links[0].attrib.get("href") or "").strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            continue
        pub = None
        text_cells = []
        for c in cells:
            d = parse_date(c) if len(c) <= 40 else None
            if d and pub is None:
                pub = d
            elif c and not re.fullmatch(r"[\d.\s]+", c):
                text_cells.append(c)
        title = max(text_cells, key=len) if text_cells else clean(" ".join(links[0].css("::text").getall()))
        if feed.get("date_selector"):
            pub = parse_date(clean(" ".join(tr.css(feed["date_selector"] + " ::text").getall()))) or pub
        if not title or not _keep(feed, title, href):
            continue
        row = _row(feed, page_url, href, title, pub)
        if row["id"] not in seen:
            seen.add(row["id"])
            yield row


def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)]
        else:
            return None
    return obj


def json_api(feed: dict, page_url: str, body: bytes | str) -> Iterator[dict]:
    data = json.loads(body)
    items = _dig(data, feed.get("items_path")) or []
    f = feed["fields"]
    tmpl = feed.get("url_template")
    for it in items:
        if not isinstance(it, dict):
            continue
        title = clean(str(_dig(it, f.get("title")) or ""))
        raw_url = _dig(it, f.get("url")) if f.get("url") else None
        if tmpl:
            try:
                vals = {k: _dig(it, v) for k, v in f.items()}
                vals["url"] = raw_url or ""
                href = tmpl.format(**vals)
            except (KeyError, IndexError):
                continue
        else:
            href = str(raw_url or "")
        if not title or not href:
            continue
        pub = parse_date(str(_dig(it, f["date"]))) if f.get("date") else None
        if not _keep(feed, title, href) and feed.get("include"):
            continue
        row = _row(feed, page_url, href, title, pub)
        row["raw"] = {k: _dig(it, v) for k, v in f.items()}
        yield row


def rss(feed: dict, page_url: str, body: bytes | str) -> Iterator[dict]:
    sel = Selector(text=body if isinstance(body, str) else body.decode("utf-8", "replace"), type="xml")
    sel.remove_namespaces()
    for it in sel.xpath("//item | //entry"):
        title = clean(it.xpath("string(title)").get())
        href = clean(it.xpath("string(link)").get()) or it.xpath("link/@href").get() or ""
        pub = parse_date(clean(it.xpath("string(pubDate|published|updated)").get()))
        if title and href and _keep(feed, title, href):
            yield _row(feed, page_url, href, title, pub)


def pdf_document(feed: dict, page_url: str, body: bytes | str) -> Iterator[dict]:
    """The feed URL is itself the document (an annual calendar PDF)."""
    title = feed.get("notes") or page_url.rsplit("/", 1)[-1]
    yield _row(feed, page_url, page_url, title, None)


ADAPTERS = {
    "html_links": html_links,
    "html_table": html_table,
    "json_api": json_api,
    "rss": rss,
    "pdf_document": pdf_document,
}


def looks_unrendered(body: bytes | str) -> bool:
    """A page whose content is drawn by script: few links and little text.
    The thresholds are generous on purpose; a false positive costs one
    browser fetch, a false negative costs a feed."""
    sel = Selector(text=body if isinstance(body, str) else body.decode("utf-8", "replace"))
    links = len(sel.xpath("//body//a[@href]"))
    words = len(" ".join(sel.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]").getall()).split())
    return links < 10 or words < 150


def run(feed: dict, page_url: str, body: bytes | str) -> list[dict]:
    return list(ADAPTERS[feed["adapter"]](feed, page_url, body))
