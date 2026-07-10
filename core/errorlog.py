"""ERRORS.md appender — Prime Directive rule 6.

Errors are appended, timestamped, and never rewritten. Pre-game numbers are
never edited after results are known; a wrong number gets a log line here,
not a correction in the report.
"""
from __future__ import annotations

from pathlib import Path

from core.manifest import utcnow_iso

ROOT = Path(__file__).resolve().parent.parent
ERRORS_PATH = ROOT / "ERRORS.md"


def log_error(context: str, message: str, path: Path | None = None) -> None:
    p = path or ERRORS_PATH
    line = f"- `{utcnow_iso()}` **{context}** — {message}\n"
    with open(p, "a") as f:
        f.write(line)
