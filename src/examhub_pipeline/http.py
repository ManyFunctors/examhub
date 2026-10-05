"""Cached, polite HTTP fetcher.

Three rules, in priority order:

1. **robots.txt is obeyed.** Fetched through the same throttle, cached, and
   consulted before every request. A 404 means "allowed" (RFC 9309); a 401
   or 403 means "disallowed"; anything else is treated as "disallowed" unless
   the caller explicitly overrides, because failing closed is the safe
   default for a tool that visits hosts it does not own.
2. **One host at a time, slowly.** A per-host minimum interval derived from
   ``Crawl-delay`` when robots.txt states one, and from the settings
   otherwise. Government sites are slow and flaky; hammering one is how you
   get an IP blocked for a month.
3. **Never fetch the same bytes twice.** The disk cache is keyed by URL and
   stores the body addressed by content hash, so a re-run inside the TTL does
   zero network IO, and a conditional request that returns 304 costs one
   conditional GET rather than a full download.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import logging
import random
import threading
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import certifi
import httpx

from .config import RETRY_STATUSES, Settings

#: Hosts whose server omits an intermediate certificate that is not in the
#: default trust store. The intermediate is trusted for that host alone.
EXTRA_CA_FILES: dict[str, Path] = {
    host: Path(__file__).resolve().parents[2] / "data" / "certs" / "globalsign-rsa-ov-ssl-ca-2018.pem"
    for host in ("www.ibps.in", "ibps.in")
}

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """A fetch that failed in a way the caller has to know about."""


class RobotsDenied(FetchError):
    """The host's robots.txt disallows this URL for our user-agent."""


class BudgetExhausted(FetchError):
    """The run's request budget is used up. Deliberately a distinct type: a
    partial run is a legitimate outcome and should not be reported as a bug."""


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CachedResponse:
    url: str
    final_url: str
    status: int
    content_type: str
    content: bytes
    etag: str | None
    last_modified: str | None
    retrieved: float
    checked: float
    from_cache: bool
    not_modified: bool

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def age_seconds(self) -> float:
        return time.time() - self.checked

    def text(self, errors: str = "replace") -> str:
        """Decode using the declared charset where there is one.

        Government notices are routinely served as windows-1252 or with no
        charset at all; guessing wrong turns ``₹`` into mojibake and a date
        into an unparseable string.
        """
        for encoding in _encodings(self.content_type, self.content):
            try:
                return self.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.content.decode("utf-8", errors=errors)

    def meta(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "retrieved": self.retrieved,
            "checked": self.checked,
            "content_hash": self.content_hash,
            "bytes": len(self.content),
        }


def _encodings(content_type: str, content: bytes) -> Iterable[str]:
    seen: list[str] = []
    if "charset=" in (content_type or "").lower():
        seen.append(content_type.lower().split("charset=", 1)[1].split(";")[0].strip())
    head = content[:4096].lower()
    if b"charset=" in head:
        try:
            blob = head.decode("ascii", "ignore")
            seen.append(blob.split("charset=", 1)[1].split(";")[0].split('"')[0].strip())
        except Exception:  # pragma: no cover - defensive
            pass
    seen += ["utf-8", "windows-1252", "latin-1"]
    return [e for e in seen if e]


class DiskCache:
    """URL -> {meta, content-hash} with the body stored once per content hash.

    Layout::

        <cache>/meta/<sha256(url)>.json
        <cache>/blobs/<content_hash>

    Storing the body under its own hash means the 200-document re-check
    shares one copy of anything that did not change, and the key is auditable
    by eye: the meta file records which hash the URL resolved to and when.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.meta_dir = self.root / "meta"
        self.blob_dir = self.root / "blobs"

    def ensure(self) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.blob_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _meta_path(self, url: str) -> Path:
        return self.meta_dir / f"{self._key(url)}.json"

    def _blob_path(self, content_hash: str) -> Path:
        return self.blob_dir / content_hash

    def get(self, url: str) -> dict[str, Any] | None:
        path = self._meta_path(url)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # pragma: no cover - corrupt cache
            log.warning("cache meta unreadable for %s, refetching", url)
            return None

    def blob(self, content_hash: str) -> bytes | None:
        path = self._blob_path(content_hash)
        try:
            return path.read_bytes()
        except OSError:
            return None

    def put(self, meta: dict[str, Any], content: bytes) -> None:
        self.ensure()
        content_hash = hashlib.sha256(content).hexdigest()
        blob = self._blob_path(content_hash)
        if not blob.exists():
            tmp = blob.with_suffix(".tmp")
            tmp.write_bytes(content)
            tmp.replace(blob)
        record = dict(meta)
        record["content_hash"] = content_hash
        record["bytes"] = len(content)
        path = self._meta_path(str(meta["url"]))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def touch(self, url: str, when: float) -> None:
        """Record that a conditional request came back 304.

        Only the meta is rewritten. The body is left exactly where it is: a
        304 means the bytes we already have are still current, and re-hashing
        a 2 MB PDF to re-store it under the same hash would be pure waste.
        """
        meta = self.get(url)
        if meta is None:  # pragma: no cover - guarded by caller
            return
        meta["checked"] = when
        self._meta_path(url).write_text(
            json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8"
        )

    def stats(self) -> dict[str, int]:
        def count(path: Path, suffix: str) -> int:
            return len(list(path.glob(f"*{suffix}"))) if path.exists() else 0

        return {
            "urls": count(self.meta_dir, ".json"),
            "blobs": len(list(self.blob_dir.glob("*"))) if self.blob_dir.exists() else 0,
        }


# --------------------------------------------------------------------------
# Politeness
# --------------------------------------------------------------------------


class HostThrottle:
    """Per-host minimum interval, with a slot semaphore for concurrency."""

    def __init__(self, delay: float = 5.0, max_per_host: int = 2) -> None:
        self.base_delay = delay
        self.max_per_host = max(1, max_per_host)
        # RLock, not Lock: wait() holds this lock while calling delay_for(),
        # which takes it again. A plain Lock self-deadlocks on the first
        # request, silently, with no traceback.
        self._lock = threading.RLock()
        self._last: dict[str, float] = {}
        self._delay: dict[str, float] = {}
        self._slots: dict[str, threading.BoundedSemaphore] = {}
        self._inflight: dict[str, int] = {}

    def delay_for(self, host: str) -> float:
        with self._lock:
            return max(self.base_delay, self._delay.get(host, 0.0))

    def _semaphore(self, host: str) -> threading.BoundedSemaphore:
        with self._lock:
            if host not in self._slots:
                self._slots[host] = threading.BoundedSemaphore(self.max_per_host)
            return self._slots[host]

    def wait(self, host: str) -> None:
        """Block until this host is allowed another request."""
        sem = self._semaphore(host)
        sem.acquire()
        try:
            while True:
                with self._lock:
                    now = time.monotonic()
                    delay = max(self.base_delay, self._delay.get(host, 0.0))
                    earliest = self._last.get(host, 0.0) + delay
                    if now >= earliest:
                        self._last[host] = now
                        self._inflight[host] = self._inflight.get(host, 0) + 1
                        return
                    sleep_for = earliest - now
                # Crawl-delay can be a long wait; cap a single sleep so a
                # shutdown is not blocked forever.
                time.sleep(min(sleep_for, 30.0))
        except BaseException:
            sem.release()
            raise

    def done(self, host: str) -> None:
        with self._lock:
            self._inflight[host] = max(0, self._inflight.get(host, 1) - 1)
        self._semaphore(host).release()

    def inflight(self, host: str) -> int:
        with self._lock:
            return self._inflight.get(host, 0)

    def request_rate_delay(self, host: str, delay: float) -> None:
        """Adopt a robots.txt ``Crawl-delay`` if it is more conservative."""
        with self._lock:
            self._delay[host] = max(self._delay.get(host, 0.0), delay)


class RobotsCache:
    """robots.txt, fetched politely and remembered for the whole run."""

    def __init__(
        self,
        settings: Settings,
        client: "Fetcher",
        user_agent: str,
        throttle: HostThrottle | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.user_agent = user_agent
        # The throttle is taken explicitly rather than reached for as
        # ``client.throttle``. Anything that can fetch a robots.txt can own one
        # -- which is exactly what the tests need, and duck-typing a Fetcher
        # here meant the class could only be exercised with a real one.
        self.throttle = throttle if throttle is not None else getattr(client, "throttle", None)
        self._parsers: dict[str, robotparser.RobotFileParser | None] = {}
        #: origin -> why its robots.txt could not be read (network or TLS)
        self.unreadable: dict[str, str] = {}
        self._lock = threading.Lock()

    def _origin(self, url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}", parts.netloc

    def parser_for(self, url: str) -> robotparser.RobotFileParser | None:
        origin, _ = self._origin(url)
        with self._lock:
            if origin in self._parsers:
                return self._parsers[origin]

        parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        robots_url = origin + "/robots.txt"
        try:
            # check_robots=False: consulting robots.txt *about* robots.txt
            # is the recursion this flag exists to break.
            response = self.client.fetch(
                robots_url,
                ttl_seconds=self.settings.cache_ttl_seconds,
                budget=False,
                check_robots=False,
                # RFC 9309: the *status* of robots.txt is the answer. 404 means
                # fully allowed, 401/403 means fully disallowed. So a 4xx here
                # is data, not a failure, and must not raise.
                tolerate_errors=True,
            )
        except FetchError as exc:
            log.warning("could not read %s (%s); treating as disallowed", robots_url, exc)
            self.unreadable[origin] = str(exc)
            parser = None
        else:
            if response.status == 200:
                parser.parse(response.text().splitlines())
            elif response.status in (401, 403):
                log.info("%s returned %s: disallowing all", robots_url, response.status)
                parser = None
            else:
                # RFC 9309: 4xx other than 401/403 means fully allowed. A 5xx
                # is an error, and failing closed is the right default.
                if 400 <= response.status < 500:
                    parser = robotparser.RobotFileParser()
                    parser.allow_all = True
                else:
                    log.warning(
                        "%s returned %s; treating as disallowed", robots_url, response.status
                    )
                    parser = None

        if parser is not None and self.throttle is not None:
            delay = self._crawl_delay(parser)
            if delay:
                self.throttle.request_rate_delay(self._origin(url)[1], min(delay, 120.0))
        with self._lock:
            self._parsers[origin] = parser
        return parser

    def _crawl_delay(self, parser: robotparser.RobotFileParser) -> float | None:
        for agent in (self.user_agent, "*"):
            try:
                delay = parser.crawl_delay(agent)
            except Exception:  # pragma: no cover - stdlib can raise on odd UA
                delay = None
            if delay:
                return float(delay)
        return None

    def allowed(self, url: str) -> bool:
        if not self.settings.respect_robots:
            return True
        parser = self.parser_for(url)
        if parser is None:
            return False
        try:
            return bool(parser.can_fetch(self.user_agent, url))
        except Exception:  # pragma: no cover - defensive
            return False


# --------------------------------------------------------------------------
# Fetcher
# --------------------------------------------------------------------------


@dataclass
class Fetcher:
    """The polite, cached, retrying HTTP client used by everything else."""

    settings: Settings
    cache: DiskCache = field(init=False)
    throttle: HostThrottle = field(init=False)
    client: httpx.Client = field(init=False)
    _host_clients: dict[str, httpx.Client] = field(init=False, default_factory=dict)
    robots: RobotsCache = field(init=False)
    budget_used: int = 0
    stats: dict[str, int] = field(
        init=False,
        default_factory=lambda: {
            "network": 0,
            "cache_hit": 0,
            "not_modified": 0,
            "retries": 0,
            "denied": 0,
            "errors": 0,
        },
    )
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.cache = DiskCache(self.settings.cache_dir)
        self.cache.ensure()
        self.throttle = HostThrottle(
            delay=self.settings.host_delay_seconds,
            max_per_host=self.settings.max_per_host,
        )
        self.client = self._new_client()
        self.robots = RobotsCache(
            self.settings, self, self.settings.user_agent, self.throttle
        )

    # -- lifecycle --------------------------------------------------------

    def _new_client(self, verify: ssl.SSLContext | bool = True) -> httpx.Client:
        return httpx.Client(
            follow_redirects=True,
            verify=verify,
            timeout=httpx.Timeout(
                self.settings.timeout_seconds,
                connect=self.settings.connect_timeout_seconds,
            ),
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )

    def _client_for(self, host: str) -> httpx.Client:
        """The shared client, or one that also trusts the host's extra intermediate."""
        extra = EXTRA_CA_FILES.get(host)
        if extra is None:
            return self.client
        with self._lock:
            if host not in self._host_clients:
                ctx = ssl.create_default_context(cafile=certifi.where())
                ctx.load_verify_locations(cafile=str(extra))
                self._host_clients[host] = self._new_client(verify=ctx)
            return self._host_clients[host]

    def close(self) -> None:
        self.client.close()
        for client in self._host_clients.values():
            client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- core -------------------------------------------------------------

    def _spend(self, budget: bool) -> None:
        with self._lock:
            if not budget:
                return
            if self.budget_used >= self.settings.max_requests:
                raise BudgetExhausted(
                    f"request budget of {self.settings.max_requests} is exhausted; "
                    "raise --max-requests or narrow --source"
                )
            self.budget_used += 1

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.settings.backoff_cap_seconds)
            except ValueError:
                pass
        window = min(
            self.settings.backoff_base_seconds * (2**attempt),
            self.settings.backoff_cap_seconds,
        )
        # Jitter matters: without it, every host we hit at the same moment
        # retries at the same moment and looks like a coordinated attack.
        return window * (0.5 + random.random() / 2)

    def fetch(
        self,
        url: str,
        *,
        ttl_seconds: int | None = None,
        force: bool = False,
        budget: bool = True,
        referer: str | None = None,
        check_robots: bool = True,
        tolerate_errors: bool = False,
    ) -> CachedResponse:
        """Fetch one URL. Returns a :class:`CachedResponse`.

        ``ttl_seconds=None`` uses the default; a negative TTL means "always
        revalidate" (still a conditional GET, so a 304 costs almost nothing).
        """
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            raise FetchError(f"not a fetchable URL: {url!r}")

        if check_robots and not self.robots.allowed(url):
            with self._lock:
                self.stats["denied"] += 1
            origin = f"{urlsplit(url).scheme}://{host}"
            why = self.robots.unreadable.get(origin)
            if why:
                raise RobotsDenied(f"robots.txt could not be read for {host} ({why[:80]}); not fetched")
            raise RobotsDenied(f"robots.txt disallows {url} for our user-agent")

        ttl = self.settings.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        cached = self.cache.get(url)

        now = time.time()
        if cached and not force:
            age = now - float(cached.get("checked", 0))
            if ttl >= 0 and age < ttl:
                return self._from_cache(url, cached, not_modified=False)
            body = self.cache.blob(cached["content_hash"])
            if body is None:  # pragma: no cover - cache pruned under us
                cached = None

        self._spend(budget)
        headers = {"If-None-Match": cached["etag"]} if cached and cached.get("etag") else {}
        if not headers and cached and cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
        if referer:
            headers["Referer"] = referer

        last_error: str = ""
        for attempt in range(self.settings.max_retries + 1):
            self.throttle.wait(host)
            try:
                self._spend(budget if attempt == 0 else False)
                response = self._client_for(host).get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.throttle.done(host)
                if attempt >= self.settings.max_retries:
                    with self._lock:
                        self.stats["errors"] += 1
                    raise FetchError(f"{url}: {last_error}") from exc
                with self._lock:
                    self.stats["retries"] += 1
                time.sleep(self._backoff(attempt, None))
                continue
            self.throttle.done(host)

            if response.status_code in RETRY_STATUSES and attempt < self.settings.max_retries:
                with self._lock:
                    self.stats["retries"] += 1
                retry_after = response.headers.get("retry-after")
                log.info(
                    "%s -> %s, backing off", url, response.status_code
                )
                time.sleep(self._backoff(attempt, retry_after))
                continue

            if response.status_code == 304 and cached:
                with self._lock:
                    self.stats["not_modified"] += 1
                self.cache.touch(url, time.time())
                return self._from_cache(url, self.cache.get(url) or cached, not_modified=True)

            if response.status_code >= 400 and not (
                tolerate_errors and 400 <= response.status_code < 600
            ):
                with self._lock:
                    self.stats["errors"] += 1
                raise FetchError(f"{url}: HTTP {response.status_code}")

            content = response.content
            if len(content) > self.settings.max_body_bytes:
                raise FetchError(
                    f"{url}: body is {len(content)} bytes, over the "
                    f"{self.settings.max_body_bytes} byte cap"
                )
            meta = {
                "url": url,
                "final_url": str(response.url),
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "retrieved": time.time(),
                "checked": time.time(),
            }
            self.cache.put(meta, content)
            with self._lock:
                self.stats["network"] += 1
            return CachedResponse(
                url=url,
                final_url=str(response.url),
                status=response.status_code,
                content_type=meta["content_type"],
                content=content,
                etag=meta["etag"],
                last_modified=meta["last_modified"],
                retrieved=meta["retrieved"],
                checked=meta["checked"],
                from_cache=False,
                not_modified=False,
            )

        raise FetchError(f"{url}: giving up after retries; last error: {last_error}")

    def _from_cache(
        self, url: str, meta: dict[str, Any], *, not_modified: bool
    ) -> CachedResponse:
        body = self.cache.blob(meta["content_hash"]) or b""
        with self._lock:
            self.stats["cache_hit"] += 1
        return CachedResponse(
            url=url,
            final_url=meta.get("final_url", url),
            status=int(meta.get("status", 200)),
            content_type=meta.get("content_type", ""),
            content=body,
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
            retrieved=float(meta.get("retrieved", 0.0)),
            checked=float(meta.get("checked", 0.0)),
            from_cache=True,
            not_modified=not_modified,
        )


def canonical(url: str) -> str:
    """Normalise a URL for cache keys.

    Drops the fragment and the tracking parameters that government portals
    sprinkle on every link. A cache keyed on the raw URL re-downloads the
    same notice once per ``?utm_*``.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    drop = ("utm_", "fbclid", "gclid", "_ga", "ref", "referrer", "source")
    kept = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if any(key == d or key.startswith(d) for d in drop):
            continue
        kept.append(pair)
    query = "&".join(sorted(kept))
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def same_site(a: str, b: str) -> bool:
    """True when two URLs share a registrable-ish host.

    Government sites shard across subdomains (``upsc.gov.in`` vs
    ``www.upsc.gov.in``) and onto a CDN sibling, so a plain equality check on
    the host is too strict to be useful in practice.
    """
    def base(url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        parts = host.split(".")
        if host.endswith(".gov.in") and len(parts) >= 3:
            return ".".join(parts[-3:])
        if host.endswith(".nic.in") and len(parts) >= 3:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:]) if len(parts) > 2 else host

    return base(a) == base(b)
