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
        "%(upload_date>%y%m%d|000101)s_"
        "%(timestamp>%H%M%S|000000)s_"
        "%(id)s"
        ".%(ext)s"
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _base_list_args(self) -> List[str]:
        """Args for listing/info calls: small request sleep, no download interval."""
        args = [str(self.config.yt_dlp_path), "--no-warnings", "--restrict-filenames"]
        if self.config.cookies_file and self.config.cookies_file.exists():
            args.extend(["--cookies", str(self.config.cookies_file)])
        elif self.config.cookies_from_browser:
            args.extend(["--cookies-from-browser", self.config.cookies_from_browser])
        # Keep listing fast but avoid hammering: 1s between requests.
        args.extend(["--sleep-requests", "1"])
        return args

    def _base_args(self) -> List[str]:
        """Args for public video downloads: omit cookies to avoid TikTok challenge failures."""
        args = [str(self.config.yt_dlp_path), "--no-warnings", "--restrict-filenames", "--impersonate", "chrome"]
        if self.config.sleep_requests is not None:
            args.extend(["--sleep-requests", str(self.config.sleep_requests)])
        if self.config.sleep_interval is not None:
            args.extend(["--sleep-interval", str(self.config.sleep_interval)])
        if self.config.max_sleep_interval is not None:
            args.extend(["--max-sleep-interval", str(self.config.max_sleep_interval)])
        return args

    def _run_json_lines(self, args: List[str]) -> List[dict]:
        cmd = self._base_list_args() + args
        logger.debug("running: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1200,
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
        max_items: Optional[int] = None,
    ) -> List[Video]:
        args = ["--flat-playlist", "--dump-json"]
        if dateafter:
            args.extend(["--dateafter", dateafter])
        if max_items:
            args.extend(["--playlist-items", f"1-{max_items}"])
        args.append(url)

        entries = self._run_json_lines(args)
        videos = []
        for entry in entries:
            video = self._extract_video(entry, channel_id)
            if video:
                videos.append(video)
        return videos

    def latest_video_timestamp(self, url: str) -> Optional[int]:
        """Fetch the newest video's timestamp without a full list."""
        args = ["--flat-playlist", "--dump-json", "--playlist-items", "1", url]
        try:
            entries = self._run_json_lines(args)
        except YtDlpError as e:
            logger.warning("failed to check latest video timestamp for %s: %s", url, e)
            return None
        if not entries:
            return None
        entry = entries[0]
        return entry.get("timestamp") or 0

    def _run_stream(self, args: List[str], cwd: Path | None = None, timeout: int | None = None) -> int:
        """Run yt-dlp and stream its output line-by-line to the log."""
        cmd = self._base_args() + args
        logger.debug("running: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(cwd) if cwd else None,
            )
        except FileNotFoundError as e:
            raise YtDlpError(f"yt-dlp not found: {self.config.yt_dlp_path}") from e

        for raw in proc.stdout or []:
            line = raw.rstrip().replace("\r", "")
            if line:
                logger.info("yt-dlp: %s", line)

        try:
            return_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise YtDlpError(f"yt-dlp timed out after {timeout} seconds")
        return return_code

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
        cmd = [
            "--download-archive",
            str(archive_path),
            "-o",
            self.OUTPUT_TEMPLATE,
            "--no-playlist",
            "--ignore-errors",
        ]
        if max_downloads:
            cmd.extend(["--max-downloads", str(max_downloads)])
        cmd.extend(urls)
        logger.debug("downloading: %s", " ".join(cmd))
        return_code = self._run_stream(cmd, cwd=output_dir, timeout=1200)
        if return_code not in (0, 101):
            raise YtDlpError(f"yt-dlp download failed (code {return_code})")

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
        cmd = [
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
        return_code = self._run_stream(cmd, cwd=output_dir, timeout=1800)

        # 101 indicates the run was intentionally cancelled (e.g. break-on-existing or max-downloads).
        if return_code not in (0, 101):
            raise YtDlpError(
                f"yt-dlp channel download failed (code {return_code})"
            )



