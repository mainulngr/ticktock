import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


class Thumbnailer:
    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self.ffmpeg_path = ffmpeg_path

    def _ensure_folder_thumbnail(self, thumbnail_path: Path) -> None:
        folder_thumbnail = thumbnail_path.parent / "folder.jpg"
        if folder_thumbnail.exists():
            return
        temporary_path = thumbnail_path.parent / "folder.tmp.jpg"
        shutil.copyfile(thumbnail_path, temporary_path)
        temporary_path.replace(folder_thumbnail)

    def _extract_frame(self, video_path: Path, temporary_path: Path, seek: str) -> bool:
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            seek,
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(temporary_path),
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError):
            return False
        return temporary_path.exists() and temporary_path.stat().st_size > 0

    def generate(self, video_path: Path) -> bool:
        thumbnail_path = video_path.with_suffix(".jpg")
        if thumbnail_path.exists():
            self._ensure_folder_thumbnail(thumbnail_path)
            return False

        temporary_path = video_path.with_suffix(".tmp.jpg")
        try:
            if not self._extract_frame(video_path, temporary_path, "1"):
                if not self._extract_frame(video_path, temporary_path, "0"):
                    temporary_path.unlink(missing_ok=True)
                    logger.warning("thumbnail generation failed for %s: no frame at ss 0 or 1", video_path)
                    return False
            temporary_path.replace(thumbnail_path)
            self._ensure_folder_thumbnail(thumbnail_path)
        except (OSError, subprocess.SubprocessError) as error:
            temporary_path.unlink(missing_ok=True)
            logger.warning("thumbnail generation failed for %s: %s", video_path, error)
            return False

        logger.info("generated thumbnail: %s", thumbnail_path)
        return True

    def backfill(self, base_dir: Path) -> None:
        """Ensure every video has a sidecar .jpg and every channel has a folder.jpg."""
        if not base_dir.exists():
            logger.warning("download base dir does not exist: %s", base_dir)
            return

        channel_dirs = [p for p in base_dir.iterdir() if p.is_dir()]
        generated = 0
        missing_folders = 0
        for channel_dir in channel_dirs:
            jpgs = sorted(channel_dir.glob("*.jpg"))
            folder_jpg = channel_dir / "folder.jpg"
            if not folder_jpg.exists() and jpgs:
                # pick the lexicographically first (oldest) video thumbnail
                source = jpgs[0]
                temporary = channel_dir / "folder.tmp.jpg"
                shutil.copyfile(source, temporary)
                temporary.replace(folder_jpg)
                missing_folders += 1
                logger.info("created folder thumbnail: %s", folder_jpg)

            for video_path in channel_dir.glob("*.mp4"):
                thumb = video_path.with_suffix(".jpg")
                if thumb.exists() and thumb.stat().st_size > 0:
                    continue
                if self.generate(video_path):
                    generated += 1

        logger.info(
            "thumbnail backfill complete: %d channels got folder.jpg, %d video thumbnails generated",
            missing_folders,
            generated,
        )
