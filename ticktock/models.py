"""Domain models."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Channel:
    """A TikTok channel with a stable id and mutable metadata."""

    id: str
    username: str
    name: str = ""
    sec_uid: str = ""
    output_dir: str = ""
    last_checked_at: Optional[datetime] = None

    def url(self) -> str:
        """Return a profile URL; prefer the stable sec_uid over username."""
        if self.sec_uid:
            return f"https://www.tiktok.com/@{self.sec_uid}"
        return f"https://www.tiktok.com/@{self.username}"

    def output_path(self, base_dir: Path) -> Path:
        return base_dir / (self.output_dir or self.id)


@dataclass
class Video:
    """A TikTok video with enough metadata for idempotent storage."""

    video_id: str
    channel_id: str
    title: str = ""
    description: str = ""
    timestamp: int = 0
    url: str = ""
    uploader: str = ""
    duration: Optional[int] = None
    view_count: Optional[int] = None
    file_path: Optional[Path] = None
    sec_uid: str = ""
    uploader_display: str = ""

    @property
    def upload_datetime(self) -> Optional[datetime]:
        if not self.timestamp:
            return None
        return datetime.fromtimestamp(self.timestamp)

    def sortable_filename(self, ext: str = "%(ext)s") -> str:
        """Return an old-to-new sortable filename prefix."""
        if self.timestamp:
            dt = datetime.fromtimestamp(self.timestamp)
            prefix = dt.strftime("%Y%m%d_%H%M%S")
        else:
            prefix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in self.title).strip()
        if safe_title:
            return f"{prefix}_{self.video_id}_{safe_title[:40]}.{ext}"
        return f"{prefix}_{self.video_id}.{ext}"


@dataclass
class DownloadResult:
    """Outcome of a single video download."""

    video: Video
    file_path: Optional[Path] = None
    skipped: bool = False
    error: Optional[str] = None
