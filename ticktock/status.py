"""Read-only status report for the download scheduler."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import Channel


@dataclass
class ChannelStatus:
    id: str
    username: str
    name: str
    last_checked_at: Optional[datetime]
    listed: int
    downloaded: int
    pending: int

    @property
    def percent(self) -> float:
        if not self.listed:
            return 0.0
        if not self.pending:
            return 100.0
        return (self.downloaded / self.listed) * 100

    @property
    def status(self) -> str:
        if not self.listed:
            return "not checked"
        if not self.pending:
            return "done"
        return "in progress"


class Status:
    """Print a human-readable per-channel download status table."""

    def __init__(self, db_path: Path, channels: List[Channel]) -> None:
        self.db_path = db_path
        self.channels = channels

    def _rows(self) -> List[ChannelStatus]:
        by_id: dict[str, ChannelStatus] = {}
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT
                        c.id,
                        c.username,
                        c.name,
                        c.last_checked_at,
                        COUNT(v.video_id) AS listed,
                        COALESCE(SUM(CASE WHEN v.file_path IS NOT NULL AND v.file_path != '' AND (v.failed = 0 OR v.failed IS NULL) THEN 1 ELSE 0 END), 0) AS downloaded,
                        COALESCE(SUM(CASE WHEN (v.file_path IS NULL OR v.file_path = '') AND (v.failed = 0 OR v.failed IS NULL) THEN 1 ELSE 0 END), 0) AS pending
                    FROM channels c
                    LEFT JOIN videos v ON c.id = v.channel_id
                    GROUP BY c.id
                    """
                ).fetchall()
            for r in rows:
                by_id[r["id"]] = ChannelStatus(
                    id=r["id"],
                    username=r["username"] or "",
                    name=r["name"] or "",
                    last_checked_at=datetime.fromisoformat(r["last_checked_at"]) if r["last_checked_at"] else None,
                    listed=r["listed"],
                    downloaded=r["downloaded"],
                    pending=r["pending"],
                )

        statuses: List[ChannelStatus] = []
        for ch in self.channels:
            if ch.id in by_id:
                statuses.append(by_id[ch.id])
            else:
                statuses.append(
                    ChannelStatus(
                        id=ch.id,
                        username=ch.username,
                        name=ch.name,
                        last_checked_at=None,
                        listed=0,
                        downloaded=0,
                        pending=0,
                    )
                )
        return statuses

    @staticmethod
    def _fmt_dt(dt: Optional[datetime]) -> str:
        if dt is None:
            return "never"
        # State stores UTC; show a compact local-like string without TZ.
        return dt.strftime("%Y-%m-%d %H:%M")

    def show(self) -> None:
        rows = self._rows()
        # Completed channels at the bottom; largest remaining at the top.
        rows.sort(key=lambda r: (r.pending == 0, -r.pending, -r.listed))

        if not rows:
            print("No channels configured.")
            return

        name_width = max(len(r.id) for r in rows) + 2
        line_width = name_width + 54

        print(f"{'channel':<{name_width}} {'status':<12} {'listed':>7} {'done':>7} {'pending':>8} {'pct':>6} {'last checked':>16}")
        print("-" * line_width)
        for r in rows:
            print(
                f"{r.id:<{name_width}} {r.status:<12} {r.listed:>7} {r.downloaded:>7} {r.pending:>8} {r.percent:>5.1f}% {self._fmt_dt(r.last_checked_at):>16}"
            )

        total_listed = sum(r.listed for r in rows)
        total_done = sum(r.downloaded for r in rows)
        total_pending = sum(r.pending for r in rows)
        total_pct = (total_done / total_listed * 100) if total_listed else 0.0
        print("-" * line_width)
        print(
            f"{'total':<{name_width}} {'':<12} {total_listed:>7} {total_done:>7} {total_pending:>8} {total_pct:>5.1f}%"
        )
