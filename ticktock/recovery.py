"""Fallback strategies for videos that fail the standard download."""

import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set

from .config import AppConfig
from .models import Channel, Video
from .state import State
from .thumbnails import Thumbnailer
from .utils import ensure_dir
from .yt_dlp import YtDlp, YtDlpError

logger = logging.getLogger(__name__)


class Recovery:
    """Try a chain of yt-dlp workarounds for failed videos."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    SLEEP_ARGS = [
        "--sleep-requests", "2",
        "--sleep-interval", "5",
        "--max-sleep-interval", "5",
    ]

    def __init__(
        self,
        config: AppConfig,
        state: State,
        ytdlp: YtDlp,
        thumbnailer: Thumbnailer,
    ) -> None:
        self.config = config
        self.state = state
        self.ytdlp = ytdlp
        self.thumbnailer = thumbnailer

    def recover_videos(self, channel: Channel, videos: List[Video]) -> Set[str]:
        """Run the fallback chain for a list of videos.

        Returns the set of video_ids that were successfully recovered.
        """
        remaining = list(videos)
        recovered: Set[str] = set()
        strategies = [
            ("browser cookies", self._try_browser_cookies),
            ("cookie file", self._try_file_cookies),
            ("embed page", self._try_embed),
        ]
        for name, strategy in strategies:
            if not remaining:
                break
            batch = [v for v in remaining if v.video_id not in recovered]
            if not batch:
                continue
            logger.info("recovery: trying %s for %d video(s)", name, len(batch))
            newly = strategy(channel, batch)
            recovered.update(newly)
            remaining = [v for v in remaining if v.video_id not in recovered]
            if newly:
                time.sleep(1)
        return recovered

    def _temp_archive(self) -> Path:
        fd, path = tempfile.mkstemp(
            prefix="recovery-archive-",
            suffix=".txt",
            dir=str(ensure_dir(self.config.state_db_path.parent)),
        )
        os.close(fd)
        return Path(path)

    def _output_dir(self, channel: Channel) -> Path:
        return ensure_dir(channel.output_path(self.config.download_base_dir))

    def _try_browser_cookies(self, channel: Channel, videos: List[Video]) -> Set[str]:
        if not self.config.cookies_from_browser:
            return set()
        extra = [
            "--cookies-from-browser",
            self.config.cookies_from_browser,
            "--user-agent",
            self.USER_AGENT,
        ] + self.SLEEP_ARGS
        return self._try_batch(channel, videos, extra)

    def _try_file_cookies(self, channel: Channel, videos: List[Video]) -> Set[str]:
        if not self.config.cookies_file or not self.config.cookies_file.exists():
            return set()
        extra = ["--cookies", str(self.config.cookies_file)] + self.SLEEP_ARGS
        return self._try_batch(channel, videos, extra)

    def _try_batch(
        self,
        channel: Channel,
        videos: List[Video],
        extra_base_args: List[str],
    ) -> Set[str]:
        output_dir = self._output_dir(channel)
        archive_path = self._temp_archive()
        urls = [v.url for v in videos if v.url]
        if not urls:
            return set()
        try:
            self.ytdlp.download(
                urls,
                output_dir,
                archive_path,
                extra_base_args=extra_base_args,
            )
        except YtDlpError as e:
            logger.warning("recovery batch failed: %s", e)
        finally:
            archive_path.unlink(missing_ok=True)
        return self._collect_downloaded(channel, videos)

    def _try_embed(self, channel: Channel, videos: List[Video]) -> Set[str]:
        output_dir = self._output_dir(channel)
        archive_path = self._temp_archive()
        urls = [f"https://www.tiktok.com/embed/v2/{v.video_id}" for v in videos]
        output_template = "_embed_%(id)s.%(ext)s"
        extra = self.SLEEP_ARGS
        try:
            self.ytdlp.download(
                urls,
                output_dir,
                archive_path,
                output_template=output_template,
                extra_base_args=extra,
            )
        except YtDlpError as e:
            logger.warning("embed batch failed: %s", e)
        finally:
            archive_path.unlink(missing_ok=True)
        return self._collect_embed_files(channel, videos)

    def _target_path(self, output_dir: Path, video: Video) -> Path:
        ts = video.timestamp or 0
        dt = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.utcnow()
        return output_dir / f"{dt.strftime('%y%m%d_%H%M%S')}_{video.video_id}.mp4"

    def _collect_downloaded(self, channel: Channel, videos: List[Video]) -> Set[str]:
        """Find videos that the standard output template produced."""
        output_dir = self._output_dir(channel)
        found: Set[str] = set()
        for video in videos:
            path = self._find_output_file(output_dir, video.video_id)
            if path:
                self._mark_downloaded(video, path)
                found.add(video.video_id)
        return found

    def _collect_embed_files(self, channel: Channel, videos: List[Video]) -> Set[str]:
        """Find and rename files produced by the embed strategy, preferring a stream with video."""
        output_dir = self._output_dir(channel)
        found: Set[str] = set()
        for video in videos:
            candidates = [
                output_dir / f"_embed_{video.video_id}-1{suffix}"
                for suffix in (".unknown_video", ".mp4", ".m4a")
            ] + [
                output_dir / f"_embed_{video.video_id}-2{suffix}"
                for suffix in (".unknown_video", ".mp4", ".m4a")
            ]
            best = next((p for p in candidates if p.exists() and self._has_video_stream(p)), None)
            if best:
                target = self._target_path(output_dir, video)
                if target.exists():
                    target.unlink()
                best.replace(target)
                self._mark_downloaded(video, target)
                found.add(video.video_id)
            for p in candidates:
                if p.exists():
                    p.unlink(missing_ok=True)
        return found

    def _has_video_stream(self, path: Path) -> bool:
        try:
            result = subprocess.run(
                [
                    self.thumbnailer.ffmpeg_path.replace("ffmpeg", "ffprobe"),
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return "video" in result.stdout.lower()
        except Exception:
            return False

    def _find_output_file(self, output_dir: Path, video_id: str) -> Path | None:
        pattern = re.compile(
            r"^(?P<date>\d{6,8})_(?P<time>\d{6})_(?P<id>[^_.]+)(?:_.*)?\.(?P<ext>\w+)$"
        )
        for path in output_dir.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            match = pattern.match(path.name)
            if not match:
                continue
            if match.group("id") == video_id:
                if self._has_video_stream(path):
                    if path.suffix == ".mp4":
                        return path
                    target = path.with_suffix(".mp4")
                    if target.exists():
                        target.unlink()
                    path.replace(target)
                    return target
                else:
                    # audio-only or unplayable; don't keep it
                    path.unlink(missing_ok=True)
        return None

    def _mark_downloaded(self, video: Video, path: Path) -> None:
        self.state.set_downloaded(video.video_id, path, video.timestamp)
        self.thumbnailer.generate(path)
