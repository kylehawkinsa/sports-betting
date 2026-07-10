"""HTTP fetch wrapper. Every network call goes through fetch_json so the
endpoint, status and timestamp always land in the source manifest.

Failure contract (Prime Directive rule 2): on any error this returns
(None, SourceRecord(status="FAIL")). Callers must treat None as "field is
missing": display `—` and exclude from the model. Never substitute a guess.
"""
from __future__ import annotations

from typing import Any

import httpx

from core.manifest import SourceRecord, utcnow_iso

DEFAULT_TIMEOUT = 20.0


def fetch_json(
    name: str,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    row_counter=None,
) -> tuple[Any | None, SourceRecord]:
    """GET url, parse JSON. Returns (data, SourceRecord). data is None on failure.

    row_counter: optional callable(data) -> int used for the manifest row count.
    """
    logged_url = url  # never log query params that may contain API keys
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return None, SourceRecord(
                name=name, endpoint=logged_url, status="FAIL",
                http_status=resp.status_code, note=f"HTTP {resp.status_code}",
            )
        data = resp.json()
        rows = 0
        if row_counter is not None:
            try:
                rows = int(row_counter(data))
            except Exception:
                rows = 0
        elif isinstance(data, list):
            rows = len(data)
        return data, SourceRecord(
            name=name, endpoint=logged_url, status="OK",
            http_status=resp.status_code, rows=rows,
        )
    except Exception as exc:  # network, timeout, JSON decode — all FAIL loudly
        return None, SourceRecord(
            name=name, endpoint=logged_url, status="FAIL",
            http_status=None, note=f"{type(exc).__name__}: {exc}",
            fetched_at=utcnow_iso(),
        )
