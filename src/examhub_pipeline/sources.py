"""Seed registry of official bodies and the pages their notices live on.

This is a *seed* list, not a hard-coded answer key. It exists so a first run
has somewhere to start; ``discover`` walks each ``notices_url``, and anything
it finds that is not in this registry is recorded as a new source proposal
rather than silently dropped.

The distinction that matters throughout: a body **runs** an exam
(:data:`Source.bodies` -> front matter ``bodies``), a different body may
**give you the thing** (JEE Main is run by NTA, seats are given by JoSAA).
This registry only knows about runners.

Discovery policy, applied to every index page:

* Only same-host, or an explicitly whitelisted CDN host. Government CDNs
  (ssc.gov.in, nic.in) serve notifications from sibling hosts, and those are
  allowed; anything else is dropped.
* Only links whose URL or anchor text looks like a notice. A notification is
  a PDF or a dated notice page, and its name says so.
* A discovery hit is a *lead*, never a value. Nothing is stored from here
  without passing through ``candidates`` and ``validate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Sequence

from .config import CATEGORY_ADMISSION, CATEGORY_JOB, SOURCE_TIERS

# --------------------------------------------------------------------------
# Link classification
# --------------------------------------------------------------------------

#: Tier is inferred from what the document calls itself. A corrigendum
#: supersedes a notification rather than sitting beside it, so it gets its own
#: tier -- that is what tells a reviewer the later document won.
_TIER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcorrigend", re.I), "corrigendum"),
    (re.compile(r"\b(addendum|erratum|amendment)\b", re.I), "corrigendum"),
    (re.compile(r"\b(extension|extended|extension of|extend the last date)", re.I), "press_release"),
    (re.compile(r"\bpress\s*(release|note)", re.I), "press_release"),
    (re.compile(r"\b(postpon|reschedul|defer|cancelled|canceled)\w*", re.I), "press_release"),
    (re.compile(r"\b(notification|advertisement|advt|vacancy|recruitment|notice)\b", re.I), "notification_pdf"),
)

#: Words that mean "this link is not a notice". Cheap and effective; a
#: government index page is mostly these.
_NEGATIVE = re.compile(
    r"\b(login|logout|sign in|signin|register|help|faq|contact|about|home|"
    r"feedback|search|site map|sitemap|skip to|accessibility|privacy|terms|"
    r"tenders?|careers?|rti|downloads?|archive|calendar|holiday list|"
    r"toll free|hotline|webcast|order|new letter|news letter|daily|bulletin|"
    r"public utility|format|apply online|tender)\b",
    re.I,
)

#: A date in a filename is a strong signal that it is a dated document.
#: Government hosts name files every way at all: 15-06-2027, 15_06_2027,
#: 15.06.2027, 2027-06-15, and cgl2026.
_DATE_IN_NAME = re.compile(
    r"(?<![\d])(20\d{2})[-_/.]?(0[1-9]|1[0-2])[-_/.]?(0[1-9]|[12]\d|3[01])(?![\d])"
    r"|(?<![\d])(0[1-9]|[12]\d|3[01])[-_/.](0[1-9]|1[0-2])[-_/.](20\d{2})(?![\d])"
)
#: A 4-digit year anywhere in the filename, e.g. cgl2026.pdf or 2026-27.pdf.
_YEAR_IN_NAME = re.compile(r"(?<![\d])(20[12]\d)(?![\d])")
#: A day and month with no year, e.g. advt_15-06.pdf. Used only to sort a
#: list of notices, never to fill in a field.
_DAY_MONTH_NAME = re.compile(r"(?<![\d])(0?[1-9]|[12]\d|3[01])[-_/](0?[1-9]|1[0-2])(?![\d])")
#: Stricter: a year as its own path segment, used to gate HTML notice pages so
#: a site does not walk us into its 2011 archive.
_YEAR_IN_PATH = re.compile(r"/(?:19|20)\d{2}(?:[-_/]|$)|[-_/](?:19|20)\d{2}(?:[-_/]|\.)")

_NOTICE_WORDS = re.compile(
    r"\b(notification|advertisement|advt|vacanc(y|ies)|recruitment|notice|"
    r"corrigendum|information\s*brochure|brochure|guidelines|schedule|"
    r"examination|exam\b|symposium|workshop|"
    r"tentative calendar|calendar\s*of\s*examinations|scheme\s*of\s*examination|"
    r"apply|application|invitation|resolution|order)\b",
    re.I,
)


def infer_tier(text: str, url: str = "") -> str:
    """Best-effort ``source_tier`` from a link's anchor text and filename.

    A ``.pdf`` is the usual shape of a notification. Anything else is a
    portal or notice page -- the two tiers that mean "a page, not a dated
    document".
    """
    haystack = f"{text} {url}"
    for pattern, tier in _TIER_PATTERNS:
        if pattern.search(haystack):
            return tier
    if re.search(r"\.pdf(\?|$)", url, re.I):
        return "notification_pdf"
    return "official_portal"


#: Anchor text that tells you nothing. NTA's notice page has 344 PDFs, all
#: of them linked as "Read More", and there is no way to tell which is which
#: without fetching them. So they are kept -- they may well be notices -- but
#: they sort below anything that names itself, and the per-source cap then
#: spends its budget on the informative ones first.
_UNINFORMATIVE = re.compile(
    r"^\s*(read\s*more|click\s*here|download|view|details?|here|link|"
    r"notice|pdf|document|file|open|more)\s*[.>»]*\s*$",
    re.I,
)

#: Words in a URL path that mean the document says what it is.


@dataclass(frozen=True, slots=True)
class NoticeRef:
    """A document we intend to fetch, with the tier it would be stored at."""

    body: str
    title: str
    url: str
    tier: str = "official_portal"
    from_page: str | None = None
    #: Set when the filename encodes a date or a year. A hint only; it is
    #: never a value, and it is never used to fill in a field.
    name_date: str | None = None
    #: 0-100. What to spend the request budget on first. See
    #: :data:`_UNINFORMATIVE`; this is a fetch-ordering hint, nothing more.
    priority: int = 50

    @property
    def is_document(self) -> bool:
        """True when the link points at a document (a PDF), not a page.

        Deliberately not "tier == "notification_pdf": a corrigendum is a document
        too, and a fetch budget that skips corrigenda skips exactly the
        notices that supersede the ones already recorded.
        """
        return is_document_url(self.url)


@dataclass(frozen=True, slots=True)
class Source:
    """One official body and where its notices are published."""

    key: str
    name: str
    notices_url: str
    #: Hosts this source's documents live on, including CDN siblings. A
    #: discovery hit on any other host is dropped.
    document_hosts: tuple[str, ...] = ()
    exam_kind: str | None = None
    category: str | None = None
    #: The name this body carries in ExamHub front matter, which is the
    #: taxonomy name and not the body's full legal title. "National"
    #: Testing Agency" is NTA in ``bodies``; a full legal title there
    #: puts a record on a taxonomy page nobody browses.
    taxonomy: str | None = None
    #: Set when the notices page is itself a dated document (a PDF calendar).
    notices_is_document: bool = False
    notes: str = ""

    @property
    def host(self) -> str:
        from urllib.parse import urlsplit

        return (urlsplit(self.notices_url).hostname or "").lower()

    @property
    def default_category(self) -> str | None:
        if self.category:
            return self.category
        if self.exam_kind == "job":
            return CATEGORY_JOB
        if self.exam_kind == "admission":
            return CATEGORY_ADMISSION
        return None



    @property
    def body_name(self) -> str:
        """The taxonomy name for this body, as front matter wants it."""
        return self.taxonomy or self.name

def _s(key, taxonomy, name, url, hosts=(), kind=None, notes="", doc=False) -> Source:
    """Build a Source, and make sure it can always see its own documents.

    The notices host is added to ``document_hosts`` in its www. and bare forms.
    Without that, a body whose index lives on www.pfrda.org.in and whose PDFs
    live on pfrda.org.in discards every link it finds, which is how a source
    looks broken with no error raised anywhere.

    Sibling and CDN hosts are listed by hand in the registry. Widening to the
    registrable domain is deliberately *not* done: neet.nta.nic.in and
    nta.nic.in are the same operator, and widening made every NTA URL resolve
    to whichever exam happened to be declared first.
    """
    from urllib.parse import urlsplit

    notices_host = (urlsplit(url).hostname or "").lower()
    allowed = {h.lower() for h in hosts}
    if notices_host:
        allowed.add(notices_host)
        allowed.add(notices_host[4:] if notices_host.startswith("www.") else "www." + notices_host)
    return Source(
        key=key,
        name=name,
        notices_url=url,
        document_hosts=tuple(sorted(allowed)),
        exam_kind=kind,
        notes=notes,
        notices_is_document=doc,
        taxonomy=taxonomy or key.upper(),
    )


#: The seed registry. URLs are the index/notice pages a maintainer would
#: start from by hand. `hosts` lists sibling/CDN hosts whose documents belong
#: to this body.
SEED_SOURCES: tuple[Source, ...] = (
    _s("upsc", "UPSC",
       "Union Public Service Commission",
       "https://upsc.gov.in/examinations/active-exams",
       hosts=("upsc.gov.in", "upsc.gov.in/easycms", "upsc.gov.in/sites/default/files"),
       kind="job",
       notes="Runs the exam and allocates IAS itself; authority == body for UPSC.",
    ),
    _s("ssc", "SSC",
       "Staff Selection Commission",
       "https://ssc.gov.in/Pages/ContentDashboard.aspx?PageID=1956",
       hosts=("ssc.gov.in", "ssc.gov.in/uploads", "ssc.gov.in/AdVMiscs"),
       kind="job",
       notes="CGL, CHSL, MTS, GD. The notice board is an ASP.NET dashboard whose"
                      "content is JS-rendered, so a plain fetch finds no links.",
    ),
    _s("ibps", "IBPS",
       "Institute of Banking Personnel Selection",
       "https://www.ibps.in/index.php/crp-updates/",
       hosts=("ibps.in", "ibps.in/uploads"),
       kind="job",
       notes="Conducts for 11 PSBs and RRBs. Uses pre-7th-CPC pay scales.",
    ),
    _s("rbi", "RBI",
       "Reserve Bank of India",
       "https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx",
       hosts=("rbi.org.in", "rbi.org.in/Scripts"),
       kind="job",
    ),
    _s("pfrda", "PFRDA",
       "Pension Fund Regulatory and Development Authority",
       "https://www.pfrda.org.in/CONTENT/Examination/Examination.aspx",
       hosts=("pfrda.org.in",),
       kind="job",
       notes="robots.txt is `User-agent: * / Disallow: /` with an Allow for"
                      "Googlebot only, so this tool refuses it. That is the policy working.",
    ),
    _s("nta", "NTA",
       "National Testing Agency",
       "https://nta.ac.in/",
       hosts=("ntalnti.co.in", "nta.gov.in", "nta.nic.in"),
       kind="admission",
       notes="Runs the exam; JoSAA and MCC are the authorities, not NTA. Owns the"
                      "whole nta.* family; the individual exam sites below are kept for"
                      "their own URLs but must not win a lookup for a general NTA URL.",
    ),
    _s("ugcnet", "UGC",
       "NTA, UGC NET",
       "https://ugcnet.nta.ac.in/",
       hosts=("ugc.gov.in",),
       kind="job",
       notes="Common recruitment drives for JRF and Assistant Professor. The only"
                      "source in the registry whose notices were fetchable end to end, and"
                      "the one the dev set is built from.",
    ),
    _s("jeemain", "NTA",
       "NTA, JEE Main",
       "https://jeemain.nta.nic.in/",
       kind="admission",
       notes="NTA ranks; JoSAA allocates. Never claim NTA admits.",
    ),
    _s("neet", "NTA",
       "NTA, NEET UG",
       "https://neet.nta.nic.in/",
       kind="admission",
       notes="MCC does the counselling. 2026 was cancelled on 3 May and re-run on"
                      "21 June with the original admit card explicitly declared invalid.",
    ),
    _s("aiims", "AIIMS",
       "All India Institute of Medical Sciences",
       "https://aiimsexams.ac.in/landingpage/key-dates",
       hosts=("aiims.edu", "aiimsexams.ac.in/UploadAnnouncement"),
       kind="job",
       notes="Next.js: the calendar links render client-side, so the static HTML"
                      "has no notice URLs. Needs a browser or a maintainer-supplied URL"
                      "list.",
    ),
    _s("mcc", "MCC",
       "Medical Counselling Committee",
       "https://mcc.nta.ac.in/",
       kind="admission",
       notes="Counselling schedules are frequently image-only PDFs. OCR required."
                      "Does not resolve in DNS from here.",
    ),
    _s("esic", "ESIC",
       "Employees' State Insurance Corporation",
       "https://www.esic.gov.in/recruitment",
       hosts=("esic.gov.in",),
       kind="job",
    ),
    _s("isro", "ISRO",
       "Indian Space Research Organisation",
       "https://www.isro.gov.in/recruitment.html",
       hosts=("isro.gov.in",),
       kind="job",
       notes="Selection is 50:50 prelims/mains; the ratio is not always printed.",
    ),
    _s("sebi", "SEBI",
       "Securities and Exchange Board of India",
       "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0",
       hosts=("sebi.gov.in",),
       kind="job",
    ),
    _s("mppsc", "MPPSC",
       "Madhya Pradesh Public Service Commission",
       "https://mppsc.mp.gov.in/",
       hosts=("mp.gov.in",),
       kind="job",
       notes="Introduced negative marking in 2026; aggregators still say it has"
                      "none.",
    ),
    _s("bpsc", "BPSC",
       "Bihar Public Service Commission",
       "https://bpsc.bih.nic.in/",
       hosts=("bih.nic.in",),
       kind="job",
    ),
    _s("cgpsc", "CGPSC",
       "Chhattisgarh Public Service Commission",
       "https://psctribal.cgstate.gov.in/",
       hosts=("cgstate.gov.in", "psc.cg.gov.in", "psctribal.cgstate.gov.in"),
       kind="job",
    ),
    _s("sikkimpsc", "Sikkim PSC",
       "Sikkim Public Service Commission",
       "https://sikkimpsc.gov.in/",
       hosts=("sikkim.gov.in",),
       kind="job",
       notes="Notice PDFs are commonly image-only scans.",
    ),
    _s("mizorampsc", "Mizoram PSC",
       "Mizoram Public Service Commission",
       "https://mizorampsc.gov.in/",
       kind="job",
       notes="Notice PDFs are commonly image-only scans.",
    ),
    _s("kpsc", "Karnataka PSC",
       "Karnataka Public Service Commission",
       "https://kpsc.karnataka.gov.in/",
       hosts=("karnataka.gov.in",),
       kind="job",
    ),
    _s("wbpsc", "West Bengal PSC",
       "West Bengal Public Service Commission",
       "https://wbpsc.gov.in/",
       hosts=("wbpscwb.gov.in",),
       kind="job",
    ),
    _s("uppsc", "UPPSC",
       "Uttar Pradesh Public Service Commission",
       "https://uppsc.up.nic.in/",
       hosts=("up.nic.in",),
       kind="job",
    ),
    _s("aptsc", "APPSC",
       "Andhra Pradesh Public Service Commission",
       "https://www.apsc.gov.in/",
       kind="job",
    ),
    _s("tspsc", "TSPSC",
       "Telangana Public Service Commission",
       "https://www.tspsc.gov.in/",
       hosts=("telangana.gov.in",),
       kind="job",
    ),
    _s("gjpsc", "GPSC",
       "Gujarat Public Service Commission",
       "https://gpsc.gujarat.gov.in/",
       hosts=("gujarat.gov.in",),
       kind="job",
    ),
    _s("rpsc", "RPSC",
       "Rajasthan Public Service Commission",
       "https://rpsc.rajasthan.gov.in/",
       hosts=("rajasthan.gov.in",),
       kind="job",
       notes="Safai Karmachari drives are a lottery on work experience: no written"
                      "test.",
    ),
    _s("kgf", "Railway Recruitment Boards",
       "Railway Recruitment Boards",
       "https://rrbapply.gov.in/",
       hosts=("indianrailways.gov.in", "rrbcdg.gov.in"),
       kind="job",
       notes="NTPC spans Pay Level 2 and 3; pay is per-post, never per-exam.",
    ),
    _s("sbinet", "State Bank of India",
       "State Bank of India",
       "https://www.sbi.co.in/careers/static/career.html",
       hosts=("onlinesbi.sbi",),
       kind="job",
       notes="PSU grade pay: E1/E2 plus a range plus an initial basic pay.",
    ),
)




def get_source(key: str) -> Source | None:
    for source in SEED_SOURCES:
        if source.key == key:
            return source
    return None


def get_source_by_url(url: str) -> Source | None:
    """Which registry entry owns this URL.

    Scored by how much of the host each source actually accounts for, with a
    large bonus for an exact match. That is what makes
    ``ugcnet.nta.ac.in`` resolve to UGC NET rather than to NTA: NTA's suffix
    match is ten characters long, UGC NET's exact match is the whole fifteen.
    Ranking by "exact beats suffix" alone got this backwards, because NTA also
    lists the exam subdomains as document hosts.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return None
    best: tuple[int, str, Source] | None = None
    for source in SEED_SOURCES:
        for candidate in {source.host, *source.document_hosts}:
            if not candidate:
                continue
            if host == candidate:
                score = 10_000 + len(candidate)
            elif host.endswith("." + candidate):
                score = len(candidate)
            else:
                continue
            key = (score, source.key)
            if best is None or key > (best[0], best[1]):
                best = (score, source.key, source)
    return best[2] if best else None



def all_hosts() -> Sequence[str]:
    """Every host this pipeline will talk to, for the robots audit."""
    hosts: set[str] = set()
    for source in SEED_SOURCES:
        hosts.add(source.host)
        hosts.update(source.document_hosts)
    return sorted(h for h in hosts if h)


#: Words in a URL path that mean the document says what it is. Used as a
#: fetch signal: a link called ``/images/public-notice-for-extension.pdf``
#: is worth a request even when the anchor just says "Read More", and a
#: link called ``/Download/Notice/20260925215817.pdf`` is not.
_SELF_DESCRIBING = re.compile(
    r"(notification|notice|corrigendum|schedule|calendar|brochure|guidelines|"
    r"advertisement|advt|recruitment|vacanc|admit|hall[-_ ]?ticket|answer[-_ ]?key|"
    r"cut[-_ ]?off|press[-_ ]?release|result|scheme|syllabus|apply|extension|"
    r"tentative|exam[-_ ]?calendar|key[-_ ]?dates)",
    re.I,
)


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


def is_document_url(url: str) -> bool:
    return bool(re.search(r"\.pdf(\?|#|$)", url, re.I))


def looks_like_notice(anchor_text: str, url: str) -> bool:
    """Is this link plausibly a notice we should fetch?

    Deterministic and cheap on purpose. Recall matters more than precision
    here -- a missed link costs a manual visit, a wrong one costs a fetch
    against a rate-limited government host.
    """
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    text = anchor_text or ""

    if _NEGATIVE.search(text):
        # A negative word alongside a positive one is usually the site's
        # boilerplate ("Home > Notice Board"), so only drop when the whole
        # anchor is the negative word.
        if not _NOTICE_WORDS.search(text):
            return False

    if is_document_url(url):
        # A PDF is nearly always worth fetching when the anchor names it or
        # the filename carries a year. Government hosts are also full of
        # scanned "scan0001.pdf" files that are not notices at all, so an
        # anchor with no notice word and no year is dropped.
        blob = f"{text} {url}"
        if _NOTICE_WORDS.search(blob):
            return True
        if _SELF_DESCRIBING.search(url):
            return True
        return bool(_DATE_IN_NAME.search(url) or _YEAR_IN_NAME.search(url))

    if not _NOTICE_WORDS.search(text):
        return False
    # An HTML notice page has to look dated -- in the path, or in its title.
    return bool(
        _DATE_IN_NAME.search(url)
        or _YEAR_IN_PATH.search(url)
        or re.search(r"\b(20\d{2})\b", text)
    )


def tier_for(anchor_text: str, url: str) -> str:
    tier = infer_tier(anchor_text, url)
    if tier not in SOURCE_TIERS:  # pragma: no cover - infer_tier is closed-set
        return "other"
    return tier


def name_date_hint(anchor_text: str, url: str) -> str | None:
    """A date or year visible in the filename. A hint, never a value.

    Never used to populate a field. It exists so a reviewer can sort a list of
    400 discovered notices by year without opening any of them.
    """
    match = _DATE_IN_NAME.search(url)
    if match:
        digits = [int(g) for g in match.groups() if g]
        if len(digits) == 3:
            a, b, c = digits
            # Disambiguate DD-MM-YYYY from YYYY-MM-DD by magnitude: only a year
            # exceeds 31, and only a year or a day can exceed 12.
            if a > 31:
                return f"{a:04d}-{b:02d}-{c:02d}"
            if c > 31:
                return f"{c:04d}-{b:02d}-{a:02d}"
            if b > 12:  # e.g. 15/13/2027 -- a real typo in a real filename
                return None
            # Day and month with no year. Returned as the raw fragment rather than
            # a date with an invented year: a hint that looks like a date is a
            # hint something will eventually treat as one.
            return f"{a:02d}-{b:02d}"
    match = _DAY_MONTH_NAME.search(url)
    if match:
        a, b = int(match.group(1)), int(match.group(2))
        if a <= 31 and b <= 12 and a > 0 and b > 0:
            return f"{a:02d}-{b:02d}"
    match = _YEAR_IN_NAME.search(url)
    if match:
        return match.group(1)
    match = re.search(r"\b(20\d{2})\b", anchor_text or "")
    if match:
        return match.group(1)
    return None


def classify_links(
    links: Sequence[tuple[str, str]],
    source: Source,
    page_url: str | None = None,
) -> Iterator[NoticeRef]:
    """Turn ``(anchor_text, absolute_url)`` pairs into notice references.

    Deduplicated by URL, preserving first-seen order so a run is reproducible.
    """
    allowed = {source.host, *source.document_hosts}
    seen: set[str] = set()
    seen_titles: set[str] = set()
    for text, url in links:
        if url in seen:
            continue
        host = _host(url)
        if not host:
            continue
        if not any(host == h or host.endswith("." + h) for h in allowed if h):
            continue
        if not looks_like_notice(text, url):
            continue
        # Deduplicate by title as well as by URL. Several government index
        # pages repeat the same document four or five times with the same
        # anchor text and different URLs, and the URL-only check happily spent
        # the whole request budget downloading one city-allotment notice five
        # times over. Anchors are compared after folding the boilerplate
        # ("Reg.", "reg.", stray punctuation) that differs between repeats.
        title_key = _title_key(text)
        if title_key and title_key in seen_titles:
            continue
        seen.add(url)
        if title_key:
            seen_titles.add(title_key)
        yield NoticeRef(
            body=source.name,
            title=" ".join((text or "").split())[:200] or url,
            url=url,
            tier=tier_for(text, url),
            from_page=page_url,
            name_date=name_date_hint(text, url),
            priority=priority_for(text, url),
        )


def priority_for(anchor_text: str, url: str) -> int:
    """Fetch-ordering score for one notice. Never a value, never a tier.

    The question this answers is narrow: given a request budget of N, which N
    of these 344 PDFs are worth the host's patience. A link whose anchor text
    names the document scores highest; a link called "Read More" pointing at
    ``Notice_20260925215817.pdf`` is probably a real notice but we have no way
    of knowing which one, so it goes last.
    """
    text = anchor_text or ""
    score = 50
    if _UNINFORMATIVE.fullmatch(text) or not text.strip():
        score -= 30
    elif _NOTICE_WORDS.search(text):
        score += 25
    if _SELF_DESCRIBING.search(url):
        score += 20
    if _DATE_IN_NAME.search(url):
        score += 10
    elif _YEAR_IN_NAME.search(url):
        score += 5
    if re.search(r"\.pdf(\?|$)", url, re.I):
        score += 5
    if _NEGATIVE.search(text) and not _NOTICE_WORDS.search(text):
        score -= 40
    return max(0, min(100, score))


_TITLE_NOISE = re.compile(
    r"\b(?:reg(?:istration)?|corrigendum|notice|no\.?|advertisement|advt)\b|"
    r"[\s\u2013\u2014\-_,.;:()\[\]/\\]+",
    re.I,
)


def _title_key(anchor_text: str) -> str:
    """A comparable key for an anchor, or "" when the anchor says nothing.

    Anchors that are pure boilerplate -- "Read More", "Click Here", an empty
    string -- must NOT be deduplicated against each other, because 300 links
    on an NTA page are all called "Read More" and they are not the same
    document. So the key is only produced when the anchor carries real words.
    """
    text = (anchor_text or "").strip()
    if not text or _UNINFORMATIVE.fullmatch(text):
        return ""
    folded = _TITLE_NOISE.sub(" ", text).strip().lower()
    if len(folded) < 8:
        return ""
    return folded
