"""Polite HTTP: one shared session, per-host throttling, on-disk cache, retries.

Every source module goes through `get()` so that rate limits and caching are
handled in one place. Failures never raise to the caller: they return None and
are recorded in `LOG`, which the CLI writes to `sources_log.csv`.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from pathlib import Path

import requests

from . import config

# Minimum seconds between requests to the same host. Greek university hosts
# block clients that go faster than about one request every 2 s.
HOST_DELAY = {
    "api.gbif.org": 0.3,
    "api.inaturalist.org": 1.1,
    "dissco-gr.nhmc.uoc.gr": 1.1,
    "nominatim.openstreetmap.org": 1.1,
    "www.openarchives.gr": 2.5,
    "www.didaktorika.gr": 2.5,
}
DEFAULT_DELAY = 1.0
GREEK_ACADEMIC_DELAY = 3.0  # *.gr hosts not listed above

CACHE_TTL_DAYS = 14

_session: requests.Session | None = None
_last_hit: dict[str, float] = {}
LOG: list[dict] = []


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = config.user_agent()
    return _session


def _delay_for(host: str) -> float:
    if host in HOST_DELAY:
        return HOST_DELAY[host]
    if host.endswith(".gr"):
        return GREEK_ACADEMIC_DELAY
    return DEFAULT_DELAY


def _throttle(host: str) -> None:
    wait = _delay_for(host) - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _cache_path(key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()
    return config.cache_dir() / "http" / h[:2] / h


def log(source: str, status: str, detail: str = "", n: int | None = None) -> None:
    LOG.append({"source": source, "status": status, "n": "" if n is None else n, "detail": detail[:300]})


def get(url: str, params: dict | None = None, *, source: str, as_json: bool = True,
        headers: dict | None = None, timeout: int = 40, retries: int = 2,
        cache: bool = True, method: str = "GET", data=None):
    """Fetch a URL; returns parsed JSON, text, or None on failure."""
    full = url if not params else url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    key = f"{method} {full} {json.dumps(data, sort_keys=True) if data else ''}"
    cp = _cache_path(key)
    if cache and cp.exists() and (time.time() - cp.stat().st_mtime) < CACHE_TTL_DAYS * 86400:
        text = cp.read_text(encoding="utf-8")
        return json.loads(text) if as_json else text

    host = urllib.parse.urlparse(full).netloc
    last_err = ""
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            r = session().request(method, full, headers=headers, timeout=timeout, data=data)
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last_err = f"HTTP {r.status_code}"
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code >= 400:
            log(source, "error", f"HTTP {r.status_code} {full}")
            return None
        if "Making sure you're not a bot" in r.text[:5000]:
            log(source, "blocked", f"Anubis bot wall at {host}")
            return None
        r.encoding = r.encoding or "utf-8"
        text = r.text
        try:
            out = json.loads(text) if as_json else text
        except ValueError:
            log(source, "error", f"non-JSON response from {full}")
            return None
        if cache:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(text, encoding="utf-8")
        return out
    log(source, "error", f"{last_err} {full}")
    return None
