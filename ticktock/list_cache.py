"""Cache full channel listings to avoid re-fetching them on every run."""

import json
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from .models import Video
from .utils import ensure_dir

logger = logging.getLogger(__name__)


class ListCache:
    """JSON-backed cache of yt-dlp channel listings."""

    def __init__(self, base_dir: Path, ttl: timedelta) -> None:
        self.base_dir = ensure_dir(base_dir / "list_cache")
        self.ttl = ttl

    def _path(self, channel_id: str) -> Path:
        return self.base_dir / f"{channel_id}.json"

    def _is_valid(self, data: dict, dateafter: Optional[str]) -> bool:
        if data.get("dateafter") != dateafter:
            return False
        created = data.get("created_at", 0)
        return (time.time() - created) < self.ttl.total_seconds()

    def get(self, channel_id: str, dateafter: Optional[str]) -> Optional[List[Video]]:
        path = self._path(channel_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("corrupt list cache for %s", channel_id)
            return None
        if not self._is_valid(data, dateafter):
            return None
        return [Video.from_dict(v) for v in data.get("videos", [])]

    def save(self, channel_id: str, dateafter: Optional[str], videos: List[Video]) -> None:
        path = self._path(channel_id)
        data = {
            "dateafter": dateafter,
            "created_at": time.time(),
            "videos": [v.to_dict() for v in videos],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("saved list cache for %s (%d videos)", channel_id, len(videos))

    def invalidate(self, channel_id: str) -> None:
        self._path(channel_id).unlink(missing_ok=True)
