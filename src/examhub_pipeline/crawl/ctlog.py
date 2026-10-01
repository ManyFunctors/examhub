"""Certificate Transparency hosts from crt.sh's public database.

crt.sh's robots.txt bars its web pages to crawlers; for programs it offers
a read-only PostgreSQL database (host crt.sh, user guest, no password).
One query per body domain, current certificates only.

The database is shared and slow (~10 s a domain), so a run spends at most
``budget`` seconds, oldest-queried domains first; the rest wait for the
next run. A failed domain is logged and tried again next run.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Callable

log = logging.getLogger(__name__)

DSN = "host=crt.sh port=5432 dbname=certwatch user=guest connect_timeout=20"
_QUERY = """
select lower(ci.name_value), min(x509_notBefore(ci.certificate))::text
  from certificate_and_identities ci
 where plainto_tsquery('certwatch', %(d)s) @@ identities(ci.certificate)
   and ci.name_value ilike %(like)s
   and coalesce(x509_notAfter(ci.certificate), now()) > now()
 group by 1
"""
#: the key under which a domain's last query date is kept in ct-cursors.json
CURSOR = "crtsh:"


def order(domains: list[str], cursors: dict[str, str]) -> list[str]:
    """Never-queried domains first, then the longest-ago."""
    return sorted(domains, key=lambda d: (cursors.get(CURSOR + d, ""), d))


def lookup(domains: list[str], cursors: dict[str, str], budget: float = 1500,
           connect: Callable | None = None, clock=time.monotonic) -> dict[str, list[dict]]:
    """domain -> [{"name_value", "not_before"}], for as many domains as the budget allows.
    Marks each domain queried in ``cursors``."""
    if connect is None:
        import psycopg
        connect = lambda: psycopg.connect(DSN, autocommit=True)  # noqa: E731
    out: dict[str, list[dict]] = {}
    todo = order(domains, cursors)
    start = clock()
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 - reported; the next run tries again
        log.warning("ct: crt.sh database unreachable: %s", exc)
        return out
    with conn:
        conn.execute("set statement_timeout = 90000")
        for i, d in enumerate(todo):
            if clock() - start > budget:
                log.info("ct: budget spent after %d of %d domains; the rest next run", i, len(todo))
                break
            try:
                rows = conn.execute(_QUERY, {"d": d, "like": f"%.{d}"}).fetchall()
            except Exception as exc:  # noqa: BLE001
                log.warning("ct: %s: %s", d, exc)
                if getattr(conn, "closed", False):
                    break
                continue
            out[d] = [{"name_value": n, "not_before": nb or ""} for n, nb in rows]
            cursors[CURSOR + d] = date.today().isoformat()
            log.info("ct: %s: %d hosts", d, len(rows))
    return out
