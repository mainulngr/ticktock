"""Scheduling logic to avoid hammering TikTok."""

import logging
from datetime import datetime
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
        self._focus_channel_id: str | None = None

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
        """Return how many videos are still pending for a channel."""
        return self.state.get_pending_count(channel.id)

    def _focus_channel(self, channels: List[Channel]) -> Channel | None:
        if not self._focus_channel_id:
            return None
        for channel in channels:
            if channel.id == self._focus_channel_id and self._pending_count(channel) > 0:
                return channel
        return None

    def _pick_next_focus(self, channels: List[Channel]) -> Channel | None:
        for channel in sorted(channels, key=self._pending_count, reverse=True):
            if self._pending_count(channel) > 0:
                return channel
        return None

    def run(
        self,
        channels: List[Channel],
        force: bool = False,
        channel_ids: List[str] | None = None,
        max_downloads: int | None = None,
    ) -> None:
        now = datetime.utcnow()

        if channel_ids:
            channels = [c for c in channels if c.id in channel_ids]

        focus = self._focus_channel(channels)
        if focus is None:
            focus = self._pick_next_focus(channels)
            self._focus_channel_id = focus.id if focus else None

        if focus is None:
            logger.info("no channels with pending downloads")
            return

        if force or self.is_due(focus, now):
            self.run_channel(focus, now, max_downloads=max_downloads)
            if self._pending_count(focus) == 0:
                self._focus_channel_id = None
        else:
            logger.info("focus channel %s checked recently; will retry later", focus.id)
