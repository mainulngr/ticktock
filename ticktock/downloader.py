"""Download videos for a channel, keeping state and idempotency."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List

from .config import AppConfig
from .list_cache import ListCache
from .models import Channel, DownloadResult, Video
from .recovery import Recovery
from .state import State
from .thumbnails import Thumbnailer
from .utils import ensure_dir
from .yt_dlp import YtDlp, YtDlpError

logger = logging.getLogger(__name__)


class Downloader:
    """Coordinate listing, filtering, and downloading of channel videos."""

    ARCHIVE_FILENAME = "yt-dlp-archive.txt"

    def __init__(self, config: AppConfig, state: State, ytdlp: YtDlp, thumbnailer: Thumbnailer) -> None:
        self.config = config
        self.state = state
        self.ytdlp = ytdlp
        self.thumbnailer = thumbnailer
        self.recovery = Recovery(config, state, ytdlp, thumbnailer)
        self.list_cache = (
            ListCache(config.state_db_path.parent, config.list_cache_ttl)
            if config.list_cache_ttl.total_seconds() > 0
            else None
        )

    def _archive_path(self, channel: Channel) -> Path:
        return (ensure_dir(self.config.state_db_path.parent) / self.ARCHIVE_FILENAME).resolve()

    def _output_dir(self, channel: Channel) -> Path:
        return ensure_dir(channel.output_path(self.config.download_base_dir))

    def _video_path(self, output_dir: Path, video_id: str) -> Path | None:
        for suffix in (".mp4", ".webm", ".mkv", ".mov"):
            path = next(output_dir.glob(f"*_{video_id}{suffix}"), None)
            if path:
                return path
        return None

    def list(self, channel: Channel) -> List[Video]:
        if self.list_cache:
            cached = self.list_cache.get(channel.id)
            newest_cached = max((v.timestamp for v in cached), default=0) if cached is not None else 0
            latest_server = self.ytdlp.latest_video_timestamp(channel.url())

            if cached is not None:
                if latest_server and latest_server <= newest_cached:
                    logger.info("using cached list for %s (%d videos)", channel.id, len(cached))
                    return cached
                if latest_server is None:
                    logger.warning("could not check latest video for %s; using cached list", channel.id)
                    return cached

            logger.info("cache stale for %s (server ts %s > cache ts %s), re-listing", channel.id, latest_server, newest_cached)

        max_items = self.config.list_max_items
        logger.info("listing %s (max_items=%s)", channel.id, max_items or "all")
        try:
            videos = self.ytdlp.list_videos(channel.url(), channel.id, max_items=max_items)
        except YtDlpError as e:
            logger.error("list failed for %s: %s", channel.id, e)
            return []

        if self.list_cache:
            self.list_cache.save(channel.id, None, videos)

        return videos

    def _sync_state_from_disk(self, channel: Channel) -> None:
        """Scan the output folder and update state with found videos."""
        output_dir = self._output_dir(channel)
        pattern = re.compile(
            r"^(?P<date>\d{6,8})_(?P<time>\d{6})_(?P<id>[^_\.]+)(?:_.*)?\.(?P<ext>\w+)$"
        )
        if not output_dir.exists():
            return
        for path in output_dir.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            match = pattern.match(path.name)
            if not match:
                continue
            video_id = match.group("id")
            date_str = match.group("date")
            ts_str = date_str + match.group("time")
            date_fmt = "%y%m%d%H%M%S" if len(date_str) == 6 else "%Y%m%d%H%M%S"
            try:
                ts = int(datetime.strptime(ts_str, date_fmt).timestamp())
            except ValueError:
                ts = 0
            self.state.set_downloaded(video_id, path, ts)

        self.state.update_latest_from_downloaded(channel.id)

    def _pending_from_list(self, videos: List[Video]) -> dict[str, Video]:
        """Return fresh pending videos from a fresh/cached list, keyed by video id."""
        return {v.video_id: v for v in videos if self.state.is_fresh_pending(v.video_id)}

    def _merge_db_pending(self, videos: dict[str, Video], channel_id: str) -> List[Video]:
        """Ensure any fresh pending videos that no longer appear in the list are still attempted."""
        for db_video in self.state.get_fresh_pending_videos(channel_id, limit=None):
            if db_video.video_id not in videos:
                videos[db_video.video_id] = db_video
        return list(videos.values())

    def _download_videos(self, channel: Channel, pending: List[Video], max_downloads: int | None = None) -> List[DownloadResult]:
        """Download a given list of videos and record results."""
        output_dir = self._output_dir(channel)
        archive_path = self._archive_path(channel)

        if max_downloads is not None:
            pending = pending[:max_downloads]

        if not pending:
            self._sync_state_from_disk(channel)
            return []

        logger.info("downloading %d pending video(s) for %s", len(pending), channel.id)

        urls = [v.url for v in pending if v.url]
        error: str | None = None
        if urls:
            try:
                self.ytdlp.download(urls, output_dir, archive_path, max_downloads=None)
            except YtDlpError as e:
                error = str(e)
        else:
            error = "no video url"

        self._sync_state_from_disk(channel)

        # Try a chain of fallback strategies for anything the standard batch missed.
        failed_videos = [v for v in pending if not self.state.is_downloaded(v.video_id)]
        if failed_videos:
            self.recovery.recover_videos(channel, failed_videos)
            self._sync_state_from_disk(channel)

        results: List[DownloadResult] = []
        for video in pending:
            if self.state.is_downloaded(video.video_id):
                video_path = self._video_path(output_dir, video.video_id)
                if video_path:
                    self.thumbnailer.generate(video_path)
                results.append(DownloadResult(video))
            else:
                if not error:
                    error = "download did not produce file"
                self.state.record_failure(video.video_id, error)
                results.append(DownloadResult(video, error=error))

        return results

    def download(self, channel: Channel, max_downloads: int | None = None) -> List[DownloadResult]:
        """Download the oldest fresh pending videos for a single channel."""
        videos = self.list(channel)

        if videos:
            for video in videos:
                self.state.record_video(video)

        pending_by_id = self._pending_from_list(videos)
        pending = self._merge_db_pending(pending_by_id, channel.id)

        if not pending:
            logger.info("no fresh pending videos for %s", channel.id)
            self._sync_state_from_disk(channel)
            return []

        return self._download_videos(channel, sorted(pending, key=lambda v: v.timestamp), max_downloads=max_downloads)

    def retry(self, channel: Channel, max_downloads: int | None = None) -> List[DownloadResult]:
        """Download the oldest retry-pending videos for a single channel."""
        pending = self.state.get_retry_pending_videos(channel.id)
        if not pending:
            logger.info("no retry pending videos for %s", channel.id)
            return []

        logger.info("retrying %d video(s) for %s", len(pending), channel.id)
        return self._download_videos(channel, pending, max_downloads=max_downloads)
