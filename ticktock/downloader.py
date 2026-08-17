"""Download videos for a channel, keeping state and idempotency."""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from .config import AppConfig
from .models import Channel, DownloadResult, Video
from .state import State
from .utils import ensure_dir
from .yt_dlp import YtDlp, YtDlpError

logger = logging.getLogger(__name__)


class Downloader:
    """Coordinate listing, filtering, and downloading of channel videos."""

    ARCHIVE_FILENAME = "yt-dlp-archive.txt"

    def __init__(self, config: AppConfig, state: State, ytdlp: YtDlp) -> None:
        self.config = config
        self.state = state
        self.ytdlp = ytdlp

    def _archive_path(self, channel: Channel) -> Path:
        return (ensure_dir(self.config.state_db_path.parent) / self.ARCHIVE_FILENAME).resolve()

    def _output_dir(self, channel: Channel) -> Path:
        return ensure_dir(channel.output_path(self.config.download_base_dir))

    @staticmethod
    def _dateafter(latest_timestamp: int) -> str | None:
        if not latest_timestamp:
            return None
        # One-day buffer to avoid missing videos from the same day.
        buffer = latest_timestamp - 86_400
        dt = datetime.utcfromtimestamp(buffer)
        return dt.strftime("%Y%m%d")

    def list(self, channel: Channel) -> List[Video]:
        latest = self.state.get_latest_upload_timestamp(channel.id)
        dateafter = self._dateafter(latest)
        logger.info("listing %s (dateafter=%s)", channel.username, dateafter or "all")
        try:
            return self.ytdlp.list_videos(channel.url(), channel.id, dateafter)
        except YtDlpError as e:
            logger.error("list failed for %s: %s", channel.id, e)
            return []

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

    def download(self, channel: Channel, max_downloads: int | None = None) -> List[DownloadResult]:
        """Download new videos for a single channel."""
        output_dir = self._output_dir(channel)
        archive_path = self._archive_path(channel)

        videos = self.list(channel)

        if not videos:
            logger.info("no videos found for %s", channel.id)
            return []

        # Track known videos from the list, but only advance the latest timestamp
        # after we confirm the files are actually on disk.
        for video in videos:
            self.state.record_video(video)

        new_videos = [v for v in videos if not self.state.is_downloaded(v.video_id)]

        if not new_videos:
            logger.info("no new videos for %s", channel.id)
            self._sync_state_from_disk(channel)
            return []

        logger.info("downloading %d new video(s) for %s", len(new_videos), channel.id)

        try:
            urls = [v.url for v in new_videos if v.url]
            if urls:
                self.ytdlp.download(urls, output_dir, archive_path, max_downloads=max_downloads)
            else:
                dateafter = self._dateafter(self.state.latest_upload_timestamp(channel.id))
                self.ytdlp.download_channel(channel.url(), output_dir, archive_path, dateafter, max_downloads=max_downloads)
        except YtDlpError as e:
            logger.error("download failed for %s: %s", channel.id, e)
            # Record any files that made it onto disk before the error.
            self._sync_state_from_disk(channel)
            return [DownloadResult(v, error=str(e)) for v in new_videos]

        # Re-scan folder to record final file paths and latest upload times.
        self._sync_state_from_disk(channel)

        return [DownloadResult(v) for v in new_videos]
