"""Resolve channel metadata (sec_uid, display name, current username)."""

import logging
from pathlib import Path
from typing import Optional

from .config import save_channels
from .models import Channel
from .yt_dlp import YtDlp, YtDlpError

logger = logging.getLogger(__name__)


class Resolver:
    """Resolve TikTok channel metadata via yt-dlp."""

    def __init__(self, ytdlp: YtDlp) -> None:
        self.ytdlp = ytdlp

    @staticmethod
    def _first_truthy(*values: Optional[str]) -> str:
        for v in values:
            if v and str(v).strip():
                return str(v).strip()
        return ""

    def resolve(self, channel: Channel) -> Channel:
        url = channel.url()
        logger.info("resolving channel: %s", url)
        try:
            info = self.ytdlp.channel_info(url, channel.id)
        except YtDlpError:
            logger.warning("could not resolve channel: %s", channel.id)
            return channel

        # TikTok fields vary; try the common ones.
        sec_uid = self._first_truthy(
            info.get("channel_id"),
            info.get("uploader_id"),
            info.get("uploader_url"),
        )
        name = self._first_truthy(
            info.get("channel"),
            info.get("uploader"),
        )
        username = self._first_truthy(
            info.get("uploader"),
            info.get("channel"),
        )

        if sec_uid and "/" in sec_uid:
            sec_uid = sec_uid.rsplit("/", 1)[-1]

        if username and username.startswith("@"):
            username = username[1:]

        if username:
            channel.username = username
        if name and name != channel.username:
            channel.name = name
        else:
            channel.name = name or channel.name
        if sec_uid and not channel.sec_uid:
            channel.sec_uid = sec_uid

        return channel

    def resolve_and_save(self, channels: list[Channel], settings_path: Path = Path("settings.toml")) -> list[Channel]:
        resolved = []
        for channel in channels:
            resolved.append(self.resolve(channel))
        save_channels(resolved, settings_path)
        logger.info("updated %s with resolved metadata", settings_path)
        return resolved
