"""Languages of the notices: which OCR models to try, and Indic digits and month
names turned into the English forms the readers' patterns already know.

A state body prints its notice in the state's language beside English, and a
scan of it is only readable with that language's OCR model. The jurisdiction
(a body id's first part, "mh" in "mh-sppu-set") says which.
"""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
import unicodedata

#: Tesseract model of each state's own language (the union territories and
#: states that print in Hindi or English only are covered by the base set).
REGIONAL = {
    "mh": "mar", "ga": "mar", "gj": "guj", "wb": "ben", "tr": "ben", "as": "asm", "tn": "tam", "py": "tam",
    "ka": "kan", "kl": "mal", "ld": "mal", "ap": "tel", "tg": "tel", "od": "ori", "pb": "pan", "ch": "pan",
    "jk": "urd", "la": "urd",
}
#: Hindi-belt jurisdictions and the centre: Hindi sits next to English.
BASE = ("eng", "hin")


def ocr_langs(jurisdiction: str | None, base: str = "eng") -> str:
    """'eng+hin+mar' for Maharashtra; just the base for an unknown jurisdiction."""
    langs = [*base.split("+"), *BASE, REGIONAL.get(jurisdiction or "", "")]
    return "+".join(dict.fromkeys(l for l in langs if l))


@functools.lru_cache(maxsize=1)
def installed() -> frozenset[str]:
    """The tesseract models on this machine (none when tesseract is missing)."""
    exe = shutil.which("tesseract")
    if not exe:
        return frozenset()
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(l.strip() for l in out.splitlines()[1:] if l.strip())


def usable(langs: str) -> str:
    """The requested models that are installed; a missing one must not fail the page."""
    have = installed()
    kept = [l for l in langs.split("+") if not have or l in have]
    return "+".join(kept) or "eng"


# ---------------------------------------------------------------- normalising

#: Month names in Devanagari (Hindi and Marathi spellings), as English.
_MONTHS = {
    "जनवरी": "January", "जानेवारी": "January", "फरवरी": "February", "फेब्रुवारी": "February",
    "मार्च": "March", "अप्रैल": "April", "एप्रिल": "April", "मई": "May", "मे": "May",
    "जून": "June", "जुलाई": "July", "जुलै": "July", "अगस्त": "August", "ऑगस्ट": "August",
    "सितंबर": "September", "सितम्बर": "September", "सप्टेंबर": "September",
    "अक्तूबर": "October", "अक्टूबर": "October", "ऑक्टोबर": "October", "नवंबर": "November", "नवम्बर": "November",
    "नोव्हेंबर": "November", "दिसंबर": "December", "दिसम्बर": "December", "डिसेंबर": "December",
}
_MONTH_RE = re.compile("(?<![ऀ-ॿ])(" + "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
                       + ")(?![ऀ-ॿ])")
_DIGIT_RE = re.compile(r"[०-९০-৯੦-੯૦-૯୦-୯"
                       r"௦-௯౦-౯೦-೯൦-൯]")


def normalise(text: str) -> str:
    """Indic digits to 0-9 and Devanagari month names to English, nothing else touched."""
    if not text or text.isascii():
        return text
    text = _DIGIT_RE.sub(lambda m: str(unicodedata.digit(m.group())), text)
    return _MONTH_RE.sub(lambda m: _MONTHS[m.group(1)], text)
