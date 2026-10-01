"""Settings, paths and constants.

Every tunable the pipeline has lives here, so that behaviour is auditable in
one file rather than scattered through the modules. Values can be overridden
from the environment (prefix ``EXAMHUB_``) which is what CI and the nix shell
use; see ``Settings.from_env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# Identification
# --------------------------------------------------------------------------

#: Contact address is intentionally a placeholder. Government sites are
#: unusually sensitive to unidentified crawlers and several block on a bare
#: user-agent string. Set EXAMHUB_CONTACT to a real mailbox before running
#: this against a host that cares.
DEFAULT_CONTACT = "examhub-maintainer@example.invalid"

#: A real, honest, identifying User-Agent. Not a browser impersonation.
USER_AGENT_TEMPLATE = (
    "examhub-pipeline/0.1 (+https://github.com/manyfunctors/examhub; "
    "contact: {contact}) python-httpx"
)

# --------------------------------------------------------------------------
# Politeness
# --------------------------------------------------------------------------

#: Minimum seconds between two requests to the same host. Government sites are
#: slow and flaky; one request per five seconds is the default and should not
#: be lowered for a .gov.in or .nic.in host.
DEFAULT_HOST_DELAY_SECONDS = 5.0

#: Per-host concurrency cap. Kept at 2 because a little overlap hides the
#: latency of a dead link without looking like a flood.
DEFAULT_MAX_PER_HOST = 2

#: Global request cap so an accidental huge registry cannot run for hours.
DEFAULT_MAX_REQUESTS = 400

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0

#: 429 and 5xx are retried with exponential backoff + jitter. Everything else
#: is returned to the caller as-is; retrying a 404 is rude and pointless.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 509})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_BACKOFF_CAP_SECONDS = 120.0

#: Cache freshness. The pipeline re-checks the same notices constantly, so a
#: re-run inside this window does no network IO at all.
DEFAULT_CACHE_TTL_SECONDS = 6 * 3600
#: Documents (notification PDFs) change rarely and are big. Keep them longer.
DEFAULT_CACHE_TTL_DOCUMENT_SECONDS = 24 * 3600

#: Hard cap on a single cached/downloaded body. A notice PDF is ~2MB; anything
#: past this is a mis-typed URL and is not worth the disk.
DEFAULT_MAX_BODY_BYTES = 40 * 1024 * 1024

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

#: A PDF with fewer than this many extractable characters across the whole
#: document is treated as a scan and sent to OCR.
OCR_CHAR_THRESHOLD = 240

#: Characters per page considered "this page is image-only".
OCR_PAGE_CHAR_THRESHOLD = 60

#: Tesseract OCR language codes, in order of preference.
DEFAULT_OCR_LANGS = "eng"

#: OCR is slow. Above this page count we stop and say so rather than run for
#: an hour: the operator decides whether to do it in the background.
DEFAULT_OCR_MAX_PAGES = 60

# --------------------------------------------------------------------------
# Validation (Laya)
# --------------------------------------------------------------------------

#: Checkpoint, chosen by measurement on the labelled dev set rather than by
#: the published benchmark table.
#:
#: ``multilingual`` (mmBERT-base, 322M) is 2.2x faster and was the obvious
#: choice on a CPU-only box, but on real notice text it answered
#: "does this notice state <label>?" with P(true) = 1.000 for every document,
#: present or absent, and scored 0/6 on the value-choice question -- it
#: always picked the same near-uniform distractor. See validate.py's module
#: docstring for the full table.
#:
#: ``typed-decisions`` (ModernBERT-large, 421M) is the one fine-tuned for
#: typed decisions. It is slower on CPU but picks the labelled value, and
#: its probabilities actually spread. The Router will not pick it
#: automatically -- it is specialised and should not be a silent default --
#: so the pipeline asks for it by name.
DEFAULT_LAYA_MODEL = "typed-decisions"

#: Context. 1024 is the typed-decisions ceiling, and it is the right number
#: here for two reasons: the checkpoint cannot take more, and on this CPU box
#: latency is linear in tokens (~7 ms/token for 421M params on 8 threads), so
#: asking for 8192 would be silently truncated anyway and cost 45 seconds a
#: call. Long documents are chunked to this instead.
DEFAULT_LAYA_MAX_LEN = 1024

#: The faster checkpoint, for a big crawl where the reviewer is reading every
#: line anyway. Measure before trusting it; see the note above.
FAST_LAYA_MODEL = "multilingual"

#: Chunk size in characters handed to the model per call.
#:
#: Derived from the context, not chosen for looks: 1024 tokens is roughly
#: 4000 characters of English for a BERT-family tokenizer, and the window
#: has to hold the candidate's evidence *and* its surrounding clause without
#: being truncated, so 4000 with a 400-character overlap. Bigger windows
#: cost latency linearly and dilute the answer -- a date table is one page of
#: sixty, and the model is being asked about a page, not a document.
DEFAULT_CHUNK_CHARS = 4000
DEFAULT_CHUNK_OVERLAP_CHARS = 400

#: How many chunks a single candidate's question set is asked across. The
#: deterministic layer already knows which chunk the evidence sits in, so 3
#: is generous.
MAX_CHUNKS_PER_CANDIDATE = 3

#: Thresholds on the ``noul`` presence probability.
#:
#: These are REPORTING thresholds, not decision thresholds. The model is
#: asked whether the document publishes each field, and the answer is
#: recorded and shown to the reviewer, but it never adds or removes a key on
#: its own. Absence is decided in candidates.py, deterministically, because
#: the model cannot do it: on the labelled dev set the presence question
#: scored AUC 0.58-0.69 across four phrasings, i.e. barely better than a
#: coin flip. See validate.py's module docstring.
#:
#:   noul P(true) >= PUBLISH_THRESHOLD  -> reported as "the model sees this"
#:   noul P(true) <= ABSENCE_THRESHOLD  -> reported as "the model does not see this"
PUBLISH_THRESHOLD = 0.75
ABSENCE_THRESHOLD = 0.30

#: A `choice` answer must beat this to be acted on. Below it the field is
#: marked `undecided` and the stored value is left alone.
#:
#: Tuned on the dev set, where correct picks had top probabilities of 0.29,
#: 0.33 and 0.45. A gate at the 0.55 that reads sensibly on paper would have
#: rejected all three. 0.25 is deliberately low: with six labelled examples
#: this is a floor, not an optimum, and every `verified` write still has to
#: clear the human review gate. Raising it trades recall for precision on a
#: sample far too small to model properly.
CHOICE_CONFIDENCE_THRESHOLD = 0.25

#: How close the runner-up choice must be before we call it a genuine
#: disagreement rather than a clear pick. Only used to add a note to the
#: review output; it never changes a verdict on its own.
CHOICE_MARGIN_THRESHOLD = 0.05

#: Torch thread count. 8 cores / 16 threads on the target box; leave headroom
#: so the fetcher and the OCR can still make progress.
DEFAULT_TORCH_THREADS = 8

#: Hard cap on model calls per run, so a bad registry cannot spin for an hour.
DEFAULT_MAX_MODEL_CALLS = 400

# --------------------------------------------------------------------------
# Domain constants
# --------------------------------------------------------------------------

#: source_tier is five values and describes what kind of document this is,
#: not how much we trust it. See data-model-notes.md section 2.8.
SOURCE_TIERS = (
    "notification_pdf",
    "official_portal",
    "press_release",
    "corrigendum",
    "other",
)

#: Section name in a record.
EXAM_SECTION = "exams"

#: Admitting-authority style exam -> category. Job examinations are
#: Government, admissions are Academic. This is a hard rule in the data model.
CATEGORY_JOB = "Government"
CATEGORY_ADMISSION = "Academic"


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings.

    Construct with :meth:`from_env` in real use; the tests construct it
    directly with a ``tmp_path`` root so nothing touches ``$HOME``.
    """

    root: Path = field(default_factory=lambda: Path.cwd())

    # -- identity ---------------------------------------------------------
    contact: str = DEFAULT_CONTACT

    # -- politeness -------------------------------------------------------
    host_delay_seconds: float = DEFAULT_HOST_DELAY_SECONDS
    max_per_host: int = DEFAULT_MAX_PER_HOST
    max_requests: int = DEFAULT_MAX_REQUESTS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS
    respect_robots: bool = True

    # -- caching ----------------------------------------------------------
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    cache_ttl_document_seconds: int = DEFAULT_CACHE_TTL_DOCUMENT_SECONDS
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES

    # -- extraction -------------------------------------------------------
    ocr_langs: str = DEFAULT_OCR_LANGS
    ocr_char_threshold: int = OCR_CHAR_THRESHOLD
    ocr_page_char_threshold: int = OCR_PAGE_CHAR_THRESHOLD
    ocr_max_pages: int = DEFAULT_OCR_MAX_PAGES
    enable_ocr: bool = True

    # -- validation -------------------------------------------------------
    enable_model: bool = True
    laya_model: str = DEFAULT_LAYA_MODEL
    laya_max_len: int = DEFAULT_LAYA_MAX_LEN
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    chunk_overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS
    max_chunks_per_candidate: int = MAX_CHUNKS_PER_CANDIDATE
    publish_threshold: float = PUBLISH_THRESHOLD
    absence_threshold: float = ABSENCE_THRESHOLD
    choice_confidence_threshold: float = CHOICE_CONFIDENCE_THRESHOLD
    choice_margin_threshold: float = CHOICE_MARGIN_THRESHOLD
    torch_threads: int = DEFAULT_TORCH_THREADS
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS

    # -- repo / output ----------------------------------------------------
    #: The Hugo site that records are written into (content/exams/ under it).
    repo_dir: Path = field(default_factory=lambda: Path.cwd() / "site")
    work_dir: Path = field(default_factory=lambda: Path.cwd() / "work")
    cache_dir: Path = field(default_factory=lambda: Path.cwd() / "work" / "cache")
    branch_prefix: str = "pipeline"

    # -- derived paths ----------------------------------------------------
    @property
    def content_dir(self) -> Path:
        return self.repo_dir / "content" / EXAM_SECTION

    @property
    def docs_dir(self) -> Path:
        return self.work_dir / "docs"

    @property
    def reviews_dir(self) -> Path:
        return self.work_dir / "reviews"

    @property
    def state_dir(self) -> Path:
        return self.work_dir / "state"

    @property
    def devset_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "devset"

    def content_rel(self, rel: str) -> Path:
        """Resolve a repo-relative content path, refusing to escape the repo."""
        root = (self.repo_dir / "content").resolve()
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"path escapes content/: {rel!r}")
        return target

    @property
    def user_agent(self) -> str:
        return USER_AGENT_TEMPLATE.format(contact=self.contact)

    def ensure_dirs(self) -> None:
        for path in (
            self.work_dir,
            self.cache_dir,
            self.docs_dir,
            self.reviews_dir,
            self.state_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build settings from ``EXAMHUB_*`` env vars, then ``overrides``.

        Recognised: ``EXAMHUB_REPO_DIR``, ``EXAMHUB_WORK_DIR``,
        ``EXAMHUB_CACHE_DIR``, ``EXAMHUB_CONTACT``, ``EXAMHUB_HOST_DELAY``,
        ``EXAMHUB_RESPECT_ROBOTS``, ``EXAMHUB_LAYA_MODEL``,
        ``EXAMHUB_LAYA_MAX_LEN``, ``EXAMHUB_ENABLE_MODEL``,
        ``EXAMHUB_ENABLE_OCR``, ``EXAMHUB_OCR_LANGS``, ``EXAMHUB_TORCH_THREADS``.
        """
        root = Path(os.environ.get("EXAMHUB_ROOT", Path.cwd()))
        data: dict[str, object] = {"root": root}

        def _p(env_name: str) -> Path | None:
            raw = os.environ.get(env_name)
            return Path(raw).expanduser() if raw else None

        def _b(env_name: str) -> bool | None:
            raw = os.environ.get(env_name)
            if raw is None:
                return None
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        for env_name, attr in (
            ("EXAMHUB_REPO_DIR", "repo_dir"),
            ("EXAMHUB_WORK_DIR", "work_dir"),
            ("EXAMHUB_CACHE_DIR", "cache_dir"),
        ):
            value = _p(env_name)
            if value is not None:
                data[attr] = value

        for env_name, attr, caster in (
            ("EXAMHUB_CONTACT", "contact", str),
            ("EXAMHUB_HOST_DELAY", "host_delay_seconds", float),
            ("EXAMHUB_LAYA_MODEL", "laya_model", str),
            ("EXAMHUB_LAYA_MAX_LEN", "laya_max_len", int),
            ("EXAMHUB_TORCH_THREADS", "torch_threads", int),
            ("EXAMHUB_CACHE_TTL", "cache_ttl_seconds", int),
            ("EXAMHUB_OCR_LANGS", "ocr_langs", str),
        ):
            raw = os.environ.get(env_name)
            if raw is not None:
                data[attr] = caster(raw) if caster is not str else raw

        for env_name, attr in (
            ("EXAMHUB_RESPECT_ROBOTS", "respect_robots"),
            ("EXAMHUB_ENABLE_MODEL", "enable_model"),
            ("EXAMHUB_ENABLE_OCR", "enable_ocr"),
        ):
            value = _b(env_name)
            if value is not None:
                data[attr] = value

        for env_name, attr, caster in (
            ("EXAMHUB_PUBLISH_THRESHOLD", "publish_threshold", float),
            ("EXAMHUB_ABSENCE_THRESHOLD", "absence_threshold", float),
            ("EXAMHUB_CHOICE_THRESHOLD", "choice_confidence_threshold", float),
        ):
            raw = os.environ.get(env_name)
            if raw is not None:
                data[attr] = caster(raw)

        known = {f.name for f in fields(cls)}
        # A None override is "not specified", not "set to nothing". Passing
        # one through replaces a real default with None and every derived path
        # property then fails.
        data.update(
            {k: v for k, v in overrides.items() if k in known and v is not None}
        )
        return cls(**data)  # type: ignore[arg-type]


def today() -> date:
    return date.today()
