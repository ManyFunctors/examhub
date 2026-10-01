"""What a link actually is, from fetching it: the facts the links step places links by.

``classify`` looks at one fetched response and says:

* ``state``  ok · soft_404 · blocked · not_found · error (as in url-health)
* ``kind``   file (a PDF, a Word file: the server says so, or the bytes do)
             · portal (a page with a login or registration form)
             · page (anything else a person reads)
* ``home``   the site's front page
* ``apply_links``  where the page's own "Apply Online" / "Registration" links go
* ``title`` and ``text``: what the page says, so a record can tell whether it names its exam

Pure: no network. The ``links`` spider fetches, this decides.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from parsel import Selector

_SOFT_404 = re.compile(r"page\s*not\s*found|pagenotfound|filenotfound|404\s*error|error\s*404"
                       r"|the requested url was not found", re.I)
_FILE_TYPES = re.compile(r"application/(pdf|msword|vnd\.|zip|octet-stream)|image/", re.I)
#: link text that sends a candidate to apply
_APPLY_TEXT = re.compile(r"apply\s*(online|now|here)?|online\s*(application|registration|form)|registration"
                         r"|register|candidate\s*login|log\s*-?\s*in|sign\s*in|one\s*time\s*registration|\bOTR\b",
                         re.I)
#: form fields that only a login or application form asks for
_FORM_FIELDS = re.compile(r"password|passwd|otp|captcha|registration.?(no|number|id)|roll.?no|date.?of.?birth|\bdob\b"
                          r"|mobile|user.?(name|id)|login|email", re.I)
TEXT_KEEP = 1500


def state_of(status: int, url: str, head: str) -> str:
    if status in (401, 403, 429, 503):
        return "blocked"
    if status in (404, 410):
        return "not_found"
    if status >= 400:
        return "error"
    if _SOFT_404.search(url) or _SOFT_404.search(head[:3000]):
        return "soft_404"
    return "ok"


def is_portal(sel: Selector) -> bool:
    """A login or application form: a password field, or a form asking for two or more
    of the things only such a form asks (registration number, date of birth, OTP ...)."""
    if sel.css("input[type=password]"):
        return True
    for form in sel.css("form"):
        names = " ".join(form.css("input::attr(name), input::attr(id), input::attr(placeholder), label::text").getall())
        if len({m.group(0).lower() for m in _FORM_FIELDS.finditer(names)}) >= 2:
            return True
    return False


def classify(url: str, final_url: str, status: int, content_type: str, body: bytes) -> dict:
    head = body[:8]
    info: dict = {"final_url": final_url, "status": status,
                  "home": not [p for p in urlsplit(final_url).path.split("/") if p] and not urlsplit(final_url).query}
    if head.startswith(b"%PDF") or head.startswith(b"PK\x03\x04") or head.startswith(b"\xd0\xcf\x11\xe0") \
            or (_FILE_TYPES.search(content_type or "") and not head.lstrip().startswith(b"<")):
        info.update(state="ok" if status < 400 else state_of(status, final_url, ""), kind="file")
        return info
    html = body.decode("utf-8", errors="replace")
    info["state"] = state_of(status, final_url, html)
    sel = Selector(text=html)
    title = " ".join(sel.css("title::text").get(default="").split())
    h1 = " ".join(" ".join(sel.css("h1 ::text, h2 ::text").getall()[:6]).split())
    body_text = " ".join(" ".join(sel.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]").getall()).split())
    applies = []
    for a in sel.css("a[href]"):
        text = " ".join(" ".join(a.css("::text").getall()).split())
        href = a.attrib.get("href", "")
        if text and len(text) <= 60 and _APPLY_TEXT.search(text) and not href.strip().lower().startswith(("#", "javascript:", "mailto:", "tel:")):
            target = urljoin(final_url, href)
            if target != final_url and target not in applies:
                applies.append(target)
    info.update(kind="portal" if is_portal(sel) else "page", title=title[:200], text=f"{h1} {body_text}"[:TEXT_KEEP],
                apply_links=applies[:5], thin=len(body_text) < 200)
    return info
