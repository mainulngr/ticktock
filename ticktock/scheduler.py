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
        self._stalled_channel_id: str | None = None

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

        channel.last_checked_at = now
        self.state.upsert_channel(channel)

        # Return how many videos were actually downloaded.
        return self.state.get_downloaded_count(channel.id) - before

    def _pending_count(self, channel: Channel) -> int:
        """Return how many videos are still pending for a channel."""
        return self.state.get_pending_count(channel.id)

    def _is_stalled(self, channel: Channel) -> bool:
        return self._stalled_channel_id is not None and self._stalled_channel_id == channel.id

    def _focus_channel(self, channels: List[Channel], now: datetime, force: bool) -> Channel | None:
        if not self._focus_channel_id:
            return None
        for channel in channels:
            if channel.id == self._focus_channel_id and not self._is_stalled(channel) and self._pending_count(channel) > 0:
                if force or self.is_due(channel, now):
                    return channel
        return None

    def _sort_key_last_checked(self, channel: Channel) -> tuple:
        state = self.state.get_channel_state(channel.id)
        return (
            state.last_checked_at is not None,
            state.last_checked_at or datetime.min,
            channel.id,
        )

    def _pick_uninitialized(self, channels: List[Channel], now: datetime, force: bool) -> Channel | None:
        uninitialized = [
            c for c in channels
            if not self._is_stalled(c)
            and (force or self.is_due(c, now))
            and self.state.get_listed_count(c.id) == 0
        ]
        if not uninitialized:
            return None
        return min(uninitialized, key=self._sort_key_last_checked)

    def _pick_next_focus(self, channels: List[Channel], now: datetime, force: bool) -> Channel | None:
        candidates = [
            c for c in channels
            if not self._is_stalled(c)
            and (force or self.is_due(c, now))
            and self._pending_count(c) > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=self._pending_count)

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

        focus = self._focus_channel(channels, now, force)
        if focus is None:
            focus = self._pick_next_focus(channels, now, force)
        if focus is None:
            focus = self._pick_uninitialized(channels, now, force)
        if focus is None:
            focus = next(
                (c for c in channels if not self._is_stalled(c) and (force or self.is_due(c, now))),
                None,
            )
        if focus is None and self._stalled_channel_id:
            # The stalled channel may be the only option left; give it another try.
            stalled = next((c for c in channels if c.id == self._stalled_channel_id), None)
            if stalled and (force or self.is_due(stalled, now)):
                logger.info("retrying stalled channel %s", stalled.id)
                focus = stalled

        if focus is None:
            logger.info("no channels due for listing")
            return

        self._focus_channel_id = focus.id

        if force or self.is_due(focus, now):
            downloaded = self.run_channel(focus, now, max_downloads=max_downloads)
            if self._pending_count(focus) == 0:
                self._focus_channel_id = None
            elif downloaded == 0:
                self._focus_channel_id = None
                self._stalled_channel_id = focus.id
                logger.info("channel %s had pending videos but produced no downloads; treating as stalled", focus.id)
            else:
                # Successful progress; clear any stale stall marker for this channel.
                if self._stalled_channel_id == focus.id:
                    self._stalled_channel_id = None
        else:
            logger.info("focus channel %s checked recently; will retry later", focus.id)
