"""SOURCE MANIFEST — Prime Directive rule 1 and 5.

Every number displayed on the board must trace to a SourceRecord created
during this run: endpoint, HTTP status, timestamp, row count. Adapters are
required to return a SourceRecord alongside their data. The board header
reports OK/total and flags any failures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SourceRecord:
    name: str                    # e.g. "mlb_schedule"
    endpoint: str                # full URL or "PASTE"/"CACHE:<path>"
    status: str                  # "OK" | "FAIL" | "SKIP" | "STALE"
    http_status: int | None = None
    fetched_at: str = field(default_factory=utcnow_iso)
    rows: int = 0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"


class Manifest:
    """Collects every source touched during a run."""

    def __init__(self) -> None:
        self.records: list[SourceRecord] = []

    def add(self, rec: SourceRecord) -> SourceRecord:
        self.records.append(rec)
        return rec

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.records if r.ok)

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def has_failures(self) -> bool:
        return any(r.status == "FAIL" for r in self.records)

    def failures(self) -> list[SourceRecord]:
        return [r for r in self.records if r.status == "FAIL"]

    def to_markdown(self) -> str:
        lines = [
            "## SOURCE MANIFEST",
            "",
            "| source | endpoint | status | http | fetched (UTC) | rows | note |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.records:
            http = str(r.http_status) if r.http_status is not None else "—"
            lines.append(
                f"| {r.name} | `{r.endpoint}` | {r.status} | {http} "
                f"| {r.fetched_at} | {r.rows} | {r.note} |"
            )
        return "\n".join(lines)
