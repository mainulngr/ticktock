"""Scheduling logic to avoid hammering TikTok."""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List

from .config import AppConfig
from .downloader import Downloader
from .models import Channel
from .resolver import Resolver
from .state import State

logger = logging.getLogger(__name__)


class Scheduler:
    """Decide which channels are due for a download and run them."""

    def __init__(
        self,
        config: AppConfig,
        state: State,
        downloader: Downloader,
        resolver: Resolver,
    ) -> None:
        self.config = config
        self.state = state
        self.downloader = downloader
        self.resolver = resolver

    def is_due(self, channel: Channel, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        channel_state = self.state.get_channel_state(channel.id)
        if channel_state.last_checked_at is None:
            return True
        elapsed = now - channel_state.last_checked_at
        return elapsed >= self.config.min_interval

    def run_channel(self, channel: Channel, now: datetime | None = None, max_downloads: int | None = None) -> int:
        now = now or datetime.utcnow()
        logger.info("checking channel: %s", channel.id)

        # Resolve metadata in case the username/display name changed.
        # Once a stable sec_uid is known, re-resolving is usually unnecessary
        # and can trigger rate limits, so we skip it unless the sec_uid is missing.
        if not channel.sec_uid:
            try:
                self.resolver.resolve(channel)
            except Exception:
                logger.exception("resolver failed for %s", channel.id)

        before = self.state.get_downloaded_count(channel.id)
        results = self.downloader.download(channel, max_downloads=max_downloads)
        for result in results:
            if result.error:
                logger.warning("error downloading %s: %s", result.video.video_id, result.error)

        self.state.set_last_checked(channel.id, now)
        self.state.upsert_channel(channel)

        # Return how many videos were actually downloaded.
        return self.state.get_downloaded_count(channel.id) - before

    def _pending_count(self, channel: Channel) -> int:
        """Use the list cache to know how many videos are pending. -1 means unknown."""
        return self.downloader.pending_count(channel)

    def run(
        self,
        channels: List[Channel],
        force: bool = False,
        channel_ids: List[str] | None = None,
        max_downloads: int | None = None,
    ) -> None:
        now = datetime.utcnow()
        remaining = max_downloads

        if channel_ids:
            channels = [c for c in channels if c.id in channel_ids]

        # Process channels with the most pending downloads first, so channels
        # with 0 known remaining are checked last (or skipped if budget runs out).
        channels = sorted(channels, key=self._pending_count, reverse=True)

        for index, channel in enumerate(channels):
            if force or self.is_due(channel, now):
                downloaded = self.run_channel(channel, now, max_downloads=remaining)
                if remaining is not None:
                    remaining -= downloaded
                    if remaining <= 0:
                        logger.info("global download budget exhausted")
                        break
            else:
                logger.info("skipping %s (checked recently)", channel.id)

            # Pause between channels to avoid request bursts.
            if (
                self.config.sleep_between_channels
                and index < len(channels) - 1
                and (remaining is None or remaining > 0)
            ):
                logger.info("sleeping %.1f seconds before next channel", self.config.sleep_between_channels)
                time.sleep(self.config.sleep_between_channels)
