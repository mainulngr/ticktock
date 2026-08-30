"""Read-only status report for the download scheduler."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    failed: int

    @property
    def percent(self) -> float:
        if not self.listed:
            return 0.0
        return (self.downloaded / self.listed) * 100

    @property
    def status(self) -> str:
        if not self.listed:
            return "not checked"
        if self.pending:
            return "in progress"
        if self.failed:
            return "blocked"
        return "done"


class Status:
    """Print a human-readable per-channel download status table."""

    def __init__(
        self,
        db_path: Path,
        channels: List[Channel],
        failed_retry_cooldown: timedelta = timedelta(hours=6),
    ) -> None:
        self.db_path = db_path
        self.channels = channels
        self.failed_retry_cooldown = failed_retry_cooldown

    def _cutoff(self) -> str:
        return (datetime.now(timezone.utc) - self.failed_retry_cooldown).replace(tzinfo=None).isoformat()

    def _has_retry_columns(self, conn: sqlite3.Connection) -> bool:
        info = conn.execute("PRAGMA table_info(videos)").fetchall()
        names = {row["name"] for row in info}
        return "retries" in names and "failed_at" in names

    def _rows(self) -> List[ChannelStatus]:
        by_id: dict[str, ChannelStatus] = {}
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                has_retry = self._has_retry_columns(conn)
                if has_retry:
                    cutoff = self._cutoff()
                    rows = conn.execute(
                        f"""
                        SELECT
                            c.id,
                            c.username,
                            c.name,
                            c.last_checked_at,
                            COUNT(v.video_id) AS listed,
                            COALESCE(SUM(CASE WHEN v.file_path IS NOT NULL AND v.file_path != '' AND (v.failed = 0 OR v.failed IS NULL) THEN 1 ELSE 0 END), 0) AS downloaded,
                            COALESCE(SUM(CASE
                                WHEN v.video_id IS NOT NULL
                                     AND (v.file_path IS NULL OR v.file_path = '')
                                     AND (v.failed = 0 OR v.failed IS NULL)
                                     AND (v.retries = 0 OR v.retries IS NULL OR v.failed_at IS NULL OR v.failed_at <= '{cutoff}')
                                THEN 1 ELSE 0 END), 0) AS pending,
                            COALESCE(SUM(CASE
                                WHEN v.video_id IS NOT NULL
                                     AND (v.file_path IS NULL OR v.file_path = '')
                                     AND (
                                         v.failed = 1
                                         OR (v.retries > 0 AND v.failed_at IS NOT NULL AND v.failed_at > '{cutoff}')
                                     )
                                THEN 1 ELSE 0 END), 0) AS failed
                        FROM channels c
                        LEFT JOIN videos v ON c.id = v.channel_id
                        GROUP BY c.id
                        """
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT
                            c.id,
                            c.username,
                            c.name,
                            c.last_checked_at,
                            COUNT(v.video_id) AS listed,
                            COALESCE(SUM(CASE WHEN v.file_path IS NOT NULL AND v.file_path != '' AND (v.failed = 0 OR v.failed IS NULL) THEN 1 ELSE 0 END), 0) AS downloaded,
                            COALESCE(SUM(CASE WHEN v.video_id IS NOT NULL AND (v.file_path IS NULL OR v.file_path = '') AND (v.failed = 0 OR v.failed IS NULL) THEN 1 ELSE 0 END), 0) AS pending,
                            COALESCE(SUM(CASE WHEN v.video_id IS NOT NULL AND v.failed = 1 THEN 1 ELSE 0 END), 0) AS failed
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
                    failed=r["failed"],
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
                        failed=0,
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
        # In-progress at the top, then blocked, then done.
        rows.sort(key=lambda r: (-r.pending, -r.failed, -r.listed))

        if not rows:
            print("No channels configured.")
            return

        name_width = max(len(r.id) for r in rows) + 2
        line_width = name_width + 64

        print(f"{'channel':<{name_width}} {'status':<12} {'listed':>7} {'done':>7} {'pending':>8} {'failed':>8} {'pct':>6} {'last checked':>16}")
        print("-" * line_width)
        for r in rows:
            print(
                f"{r.id:<{name_width}} {r.status:<12} {r.listed:>7} {r.downloaded:>7} {r.pending:>8} {r.failed:>8} {r.percent:>5.1f}% {self._fmt_dt(r.last_checked_at):>16}"
            )

        total_listed = sum(r.listed for r in rows)
        total_done = sum(r.downloaded for r in rows)
        total_pending = sum(r.pending for r in rows)
        total_failed = sum(r.failed for r in rows)
        total_pct = (total_done / total_listed * 100) if total_listed else 0.0
        print("-" * line_width)
        print(
            f"{'total':<{name_width}} {'':<12} {total_listed:>7} {total_done:>7} {total_pending:>8} {total_failed:>8} {total_pct:>5.1f}%"
        )
