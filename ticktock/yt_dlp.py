"""Thin wrapper around the `yt-dlp` CLI."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional

from .config import AppConfig
from .models import Video
from .utils import ensure_dir

logger = logging.getLogger(__name__)


class YtDlpError(Exception):
    pass


class YtDlp:
    """Execute yt-dlp and translate its output into domain objects."""

    OUTPUT_TEMPLATE = (
        "%(upload_date>%Y%m%d|19000101)s_"
        "%(timestamp>%H%M%S|000000)s_"
        "%(id)s_"
        "%(title|Untitled).50B"
        ".%(ext)s"
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _base_args(self) -> List[str]:
        args = [str(self.config.yt_dlp_path), "--no-warnings", "--restrict-filenames"]
        if self.config.cookies_file and self.config.cookies_file.exists():
            args.extend(["--cookies", str(self.config.cookies_file)])
        return args

    def _run_json_lines(self, args: List[str]) -> List[dict]:
        cmd = self._base_args() + args
        logger.debug("running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except FileNotFoundError as e:
            raise YtDlpError(f"yt-dlp not found: {self.config.yt_dlp_path}") from e

        if proc.returncode != 0:
            logger.error("yt-dlp stderr: %s", proc.stderr.strip())
            raise YtDlpError(f"yt-dlp failed (code {proc.returncode}): {proc.stderr.strip()[:200]}")

        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("non-json line: %s", line[:200])
                continue
        return entries

    @staticmethod
    def _extract_video(entry: dict, channel_id: str) -> Optional[Video]:
        video_id = entry.get("id")
        if not video_id:
            return None

        uploader = entry.get("uploader") or entry.get("uploader_id") or ""
        # TikTok flat-playlist webpage_url points to the account, not the video.
        if uploader:
            url = f"https://www.tiktok.com/@{uploader}/video/{video_id}"
        else:
            url = entry.get("url", "")

        return Video(
            video_id=str(video_id),
            channel_id=channel_id,
            title=entry.get("title", ""),
            description=entry.get("description", ""),
            timestamp=entry.get("timestamp") or 0,
            url=url,
            uploader=uploader,
            duration=entry.get("duration"),
            view_count=entry.get("view_count"),
            sec_uid=entry.get("channel_id") or entry.get("uploader_id") or "",
            uploader_display=entry.get("channel") or uploader,
        )

    def list_videos(
        self,
        url: str,
        channel_id: str,
        dateafter: Optional[str] = None,
    ) -> List[Video]:
        args = ["--flat-playlist", "--dump-json"]
        if dateafter:
            args.extend(["--dateafter", dateafter])
        args.append(url)

        entries = self._run_json_lines(args)
        videos = []
        for entry in entries:
            video = self._extract_video(entry, channel_id)
            if video:
                videos.append(video)
        return videos

    def channel_info(self, url: str, channel_id: str) -> dict:
        """Fetch the first video to extract channel/uploader metadata."""
        args = ["--dump-json", "--playlist-items", "1", url]
        entries = self._run_json_lines(args)
        if not entries:
            raise YtDlpError(f"no channel info returned for {url}")
        return entries[0]

    def download(
        self,
        urls: Iterable[str],
        output_dir: Path,
        archive_path: Path,
        max_downloads: int | None = None,
    ) -> None:
        ensure_dir(output_dir)
        cmd = self._base_args() + [
            "--download-archive",
            str(archive_path),
            "-o",
            self.OUTPUT_TEMPLATE,
            "--no-playlist",
        ]
        if max_downloads:
            cmd.extend(["--max-downloads", str(max_downloads)])
        cmd.extend(urls)
        logger.debug("downloading: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1200,
                check=False,
                cwd=str(output_dir),
            )
        except FileNotFoundError as e:
            raise YtDlpError(f"yt-dlp not found: {self.config.yt_dlp_path}") from e

        if proc.returncode not in (0, 101):
            logger.error("yt-dlp download stderr: %s", proc.stderr.strip())
            raise YtDlpError(f"yt-dlp download failed (code {proc.returncode}): {proc.stderr.strip()[:200]}")

    def download_channel(
        self,
        url: str,
        output_dir: Path,
        archive_path: Path,
        dateafter: Optional[str] = None,
        max_downloads: int | None = None,
    ) -> None:
        """Download a whole channel, letting yt-dlp's archive skip known ids."""
        ensure_dir(output_dir)
        cmd = self._base_args() + [
            "--download-archive",
            str(archive_path),
            "-o",
            self.OUTPUT_TEMPLATE,
            "--break-on-existing",
            "--break-per-input",
        ]
        if dateafter:
            cmd.extend(["--dateafter", dateafter])
        if max_downloads:
            cmd.extend(["--max-downloads", str(max_downloads)])
        cmd.append(url)
        logger.info("downloading channel: %s (dateafter=%s)", url, dateafter or "all")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
                cwd=str(output_dir),
            )
        except FileNotFoundError as e:
            raise YtDlpError(f"yt-dlp not found: {self.config.yt_dlp_path}") from e

        # 101 indicates the run was intentionally cancelled (e.g. break-on-existing or max-downloads).
        if proc.returncode not in (0, 101):
            logger.error("yt-dlp channel download stderr: %s", proc.stderr.strip())
            raise YtDlpError(
                f"yt-dlp channel download failed (code {proc.returncode}): {proc.stderr.strip()[:200]}"
            )



