"""Persistent SQLite state for channels and downloaded videos."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import Channel, Video
from .utils import ensure_dir


@dataclass
class ChannelState:
    id: str
    username: str
    name: str
    sec_uid: str
    last_checked_at: Optional[datetime]
    latest_upload_timestamp: int


class State:
    """SQLite-backed state store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        ensure_dir(self.db_path.parent)
        self._init_db()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    name TEXT,
                    sec_uid TEXT,
                    last_checked_at TEXT,
                    latest_upload_timestamp INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    title TEXT,
                    upload_timestamp INTEGER DEFAULT 0,
                    file_path TEXT,
                    downloaded_at TEXT,
                    metadata TEXT,
                    failed INTEGER DEFAULT 0,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_videos_channel
                    ON videos(channel_id);
                """
            )
            # SQLite pre-3.24 doesn't ignore repeated ADD COLUMN, so catch errors.
            for column, ddl in (
                ("failed", "ALTER TABLE videos ADD COLUMN failed INTEGER DEFAULT 0"),
                ("error", "ALTER TABLE videos ADD COLUMN error TEXT"),
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise

    def upsert_channel(self, channel: Channel) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO channels (id, username, name, sec_uid, last_checked_at, latest_upload_timestamp)
                VALUES (:id, :username, :name, :sec_uid, :last_checked_at, :latest_upload_timestamp)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    name = excluded.name,
                    sec_uid = excluded.sec_uid,
                    last_checked_at = COALESCE(excluded.last_checked_at, channels.last_checked_at),
                    latest_upload_timestamp = MAX(excluded.latest_upload_timestamp, channels.latest_upload_timestamp)
                """,
                {
                    "id": channel.id,
                    "username": channel.username,
                    "name": channel.name,
                    "sec_uid": channel.sec_uid,
                    "last_checked_at": channel.last_checked_at.isoformat() if channel.last_checked_at else None,
                    "latest_upload_timestamp": 0,
                },
            )

    def get_channel_state(self, channel_id: str) -> ChannelState:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
        if not row:
            return ChannelState(
                id=channel_id,
                username="",
                name="",
                sec_uid="",
                last_checked_at=None,
                latest_upload_timestamp=0,
            )
        return ChannelState(
            id=row["id"],
            username=row["username"],
            name=row["name"] or "",
            sec_uid=row["sec_uid"] or "",
            last_checked_at=datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None,
            latest_upload_timestamp=row["latest_upload_timestamp"] or 0,
        )

    def set_last_checked(self, channel_id: str, dt: datetime) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE channels SET last_checked_at = ? WHERE id = ?",
                (dt.isoformat(), channel_id),
            )

    def update_latest_upload_timestamp(self, channel_id: str, timestamp: int) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE channels
                SET latest_upload_timestamp = MAX(latest_upload_timestamp, ?)
                WHERE id = ?
                """,
                (timestamp, channel_id),
            )

    def update_latest_from_downloaded(self, channel_id: str) -> None:
        """Set latest_upload_timestamp to the newest actually downloaded video."""
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE channels
                SET latest_upload_timestamp = (
                    SELECT COALESCE(MAX(upload_timestamp), 0)
                    FROM videos
                    WHERE channel_id = ? AND file_path IS NOT NULL AND file_path != '' AND (failed = 0 OR failed IS NULL)
                )
                WHERE id = ?
                """,
                (channel_id, channel_id),
            )

    def is_downloaded(self, video_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM videos WHERE video_id = ? AND file_path IS NOT NULL AND file_path != '' AND (failed = 0 OR failed IS NULL)",
                (video_id,),
            ).fetchone()
        return row is not None

    def is_pending(self, video_id: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM videos WHERE video_id = ? AND (file_path IS NULL OR file_path = '') AND (failed = 0 OR failed IS NULL)",
                (video_id,),
            ).fetchone()
        return row is not None

    def get_downloaded_count(self, channel_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE channel_id = ? AND file_path IS NOT NULL AND file_path != '' AND (failed = 0 OR failed IS NULL)",
                (channel_id,),
            ).fetchone()
        return row[0] if row else 0

    def get_pending_count(self, channel_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE channel_id = ? AND (file_path IS NULL OR file_path = '') AND (failed = 0 OR failed IS NULL)",
                (channel_id,),
            ).fetchone()
        return row[0] if row else 0

    def get_pending_videos(self, channel_id: str, limit: int | None = None) -> List[Video]:
        with self._connection() as conn:
            sql = (
                "SELECT * FROM videos WHERE channel_id = ? "
                "AND (file_path IS NULL OR file_path = '') "
                "AND (failed = 0 OR failed IS NULL) "
                "ORDER BY upload_timestamp"
            )
            params: list = [channel_id]
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return self._rows_to_videos(rows)

    def get_listed_count(self, channel_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] if row else 0

    def record_video(self, video: Video, file_path: Optional[Path] = None) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO videos (video_id, channel_id, title, upload_timestamp, file_path, downloaded_at, metadata, failed, error)
                VALUES (:video_id, :channel_id, :title, :upload_timestamp, :file_path, :downloaded_at, :metadata, :failed, :error)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    title = COALESCE(NULLIF(excluded.title, ''), videos.title),
                    upload_timestamp = excluded.upload_timestamp,
                    file_path = COALESCE(excluded.file_path, videos.file_path),
                    downloaded_at = COALESCE(excluded.downloaded_at, videos.downloaded_at),
                    metadata = COALESCE(NULLIF(excluded.metadata, '{}'), videos.metadata),
                    failed = COALESCE(videos.failed, excluded.failed),
                    error = COALESCE(videos.error, excluded.error)
                """,
                {
                    "video_id": video.video_id,
                    "channel_id": video.channel_id,
                    "title": video.title,
                    "upload_timestamp": video.timestamp,
                    "file_path": str(file_path) if file_path else None,
                    "downloaded_at": datetime.utcnow().isoformat() if file_path else None,
                    "metadata": json.dumps(
                        {
                            "description": video.description,
                            "url": video.url,
                            "uploader": video.uploader,
                            "duration": video.duration,
                            "view_count": video.view_count,
                        },
                        default=str,
                    ),
                    "failed": 0,
                    "error": None,
                },
            )

    def set_downloaded(self, video_id: str, file_path: Path, timestamp: int = 0) -> None:
        """Mark a video as downloaded without overwriting title/metadata."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO videos (video_id, channel_id, title, upload_timestamp, file_path, downloaded_at, metadata, failed, error)
                VALUES (:video_id, '', '', :upload_timestamp, :file_path, :downloaded_at, '{}', :failed, :error)
                ON CONFLICT(video_id) DO UPDATE SET
                    file_path = COALESCE(excluded.file_path, videos.file_path),
                    downloaded_at = COALESCE(excluded.downloaded_at, videos.downloaded_at),
                    upload_timestamp = MAX(excluded.upload_timestamp, videos.upload_timestamp),
                    failed = COALESCE(excluded.failed, videos.failed),
                    error = COALESCE(excluded.error, videos.error)
                """,
                {
                    "video_id": video_id,
                    "upload_timestamp": timestamp,
                    "file_path": str(file_path),
                    "downloaded_at": datetime.utcnow().isoformat(),
                    "failed": 0,
                    "error": None,
                },
            )

    def _rows_to_videos(self, rows: list[sqlite3.Row]) -> List[Video]:
        videos = []
        for r in rows:
            meta = json.loads(r["metadata"] or "{}")
            file_path = r["file_path"]
            videos.append(
                Video(
                    video_id=r["video_id"],
                    channel_id=r["channel_id"],
                    title=r["title"] or "",
                    description=meta.get("description", ""),
                    timestamp=r["upload_timestamp"] or 0,
                    url=meta.get("url", ""),
                    uploader=meta.get("uploader", ""),
                    duration=meta.get("duration"),
                    view_count=meta.get("view_count"),
                    file_path=Path(file_path) if file_path else None,
                )
            )
        return videos

    def get_videos_for_channel(self, channel_id: str) -> List[Video]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE channel_id = ? ORDER BY upload_timestamp",
                (channel_id,),
            ).fetchall()
        return self._rows_to_videos(rows)

    def record_failure(self, video_id: str, error: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE videos SET failed = 1, error = ? WHERE video_id = ?",
                (error, video_id),
            )

    def get_latest_upload_timestamp(self, channel_id: str) -> int:
        return self.get_channel_state(channel_id).latest_upload_timestamp

    def latest_video_timestamp(self, channel_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT MAX(upload_timestamp) FROM videos WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row[0] or 0
