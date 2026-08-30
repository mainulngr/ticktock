import logging
import shutil
import subprocess
from pathlib import Path

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

    def generate(self, video_path: Path) -> bool:
        thumbnail_path = video_path.with_suffix(".jpg")
        if thumbnail_path.exists():
            self._ensure_folder_thumbnail(thumbnail_path)
            return False

        temporary_path = video_path.with_suffix(".tmp.jpg")
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "1",
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
            temporary_path.replace(thumbnail_path)
            self._ensure_folder_thumbnail(thumbnail_path)
        except (OSError, subprocess.SubprocessError) as error:
            temporary_path.unlink(missing_ok=True)
            logger.warning("thumbnail generation failed for %s: %s", video_path, error)
            return False

        logger.info("generated thumbnail: %s", thumbnail_path)
        return True
