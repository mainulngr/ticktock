"""Scheduling logic to avoid hammering TikTok."""

import logging
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

    def run_channel(self, channel: Channel, now: datetime | None = None) -> None:
        now = now or datetime.utcnow()
        logger.info("checking channel: %s", channel.id)

        # Resolve metadata in case the username/display name changed.
        try:
            self.resolver.resolve(channel)
        except Exception:
            logger.exception("resolver failed for %s", channel.id)

        results = self.downloader.download(channel)
        for result in results:
            if result.error:
                logger.warning("error downloading %s: %s", result.video.video_id, result.error)

        self.state.set_last_checked(channel.id, now)
        self.state.upsert_channel(channel)

    def run(
        self,
        channels: List[Channel],
        force: bool = False,
        channel_ids: List[str] | None = None,
    ) -> None:
        now = datetime.utcnow()
        for channel in channels:
            if channel_ids and channel.id not in channel_ids:
                continue
            if force or self.is_due(channel, now):
                self.run_channel(channel, now)
            else:
                logger.info("skipping %s (checked recently)", channel.id)
