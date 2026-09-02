"""Command-line interface."""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Sequence

from .config import AppConfig, ensure_paths, load_channels, load_env_config
from .cookies import refresh as refresh_cookies
from .downloader import Downloader
from .resolver import Resolver
from .scheduler import Scheduler
from .state import State
from .status import Status
from .thumbnails import Thumbnailer
from .yt_dlp import YtDlp


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _build_scheduler(config: AppConfig) -> Scheduler:
    ensure_paths(config)
    state = State(
        config.state_db_path,
        failed_retry_cooldown=config.failed_retry_cooldown,
        max_failed_retries=config.max_failed_retries,
    )
    ytdlp = YtDlp(config)
    downloader = Downloader(config, state, ytdlp, Thumbnailer(config.thumbnail_ffmpeg_path))
    resolver = Resolver(ytdlp)
    return Scheduler(config, state, downloader, resolver)


def _resolve(args: argparse.Namespace, config: AppConfig) -> int:
    channels = load_channels(args.config)
    resolver = Resolver(YtDlp(config))
    resolver.resolve_and_save(channels, Path(args.config))
    return 0


def _refresh_cookies(args: argparse.Namespace, config: AppConfig) -> int:
    browser = args.browser or config.cookies_from_browser
    if not browser:
        logging.error("no browser configured; set TIKTOK_COOKIES_FROM_BROWSER or pass --browser")
        return 1
    kept = refresh_cookies(browser, Path(args.output))
    logging.info("kept %d TikTok cookies in %s", kept, args.output)
    return 0


def _backfill_thumbnails(args: argparse.Namespace, config: AppConfig) -> int:
    ensure_paths(config)
    Thumbnailer(config.thumbnail_ffmpeg_path).backfill(config.download_base_dir)
    return 0


def _status(args: argparse.Namespace, config: AppConfig) -> int:
    channels = load_channels(args.config)
    Status(config.state_db_path, channels, failed_retry_cooldown=config.failed_retry_cooldown).show()
    return 0


def _run(args: argparse.Namespace, config: AppConfig) -> int:
    scheduler = _build_scheduler(config)
    channels = load_channels(args.config)
    scheduler.run(
        channels,
        force=args.force,
        channel_ids=args.channel or None,
        max_downloads=args.max_downloads,
    )
    return 0


def _recover(args: argparse.Namespace, config: AppConfig) -> int:
    scheduler = _build_scheduler(config)
    channels = load_channels(args.config)
    total_recovered = 0
    total_still_failed = 0
    for channel in channels:
        if args.channel and channel.id not in args.channel:
            continue
        all_videos = scheduler.state.get_videos_for_channel(channel.id)
        missing = [v for v in all_videos if not v.file_path]
        if not missing:
            continue
        with scheduler.state._connection() as conn:
            conn.execute(
                "UPDATE videos SET failed=0, retries=0, failed_at=NULL, error=NULL "
                "WHERE channel_id=? AND (file_path IS NULL OR file_path='')",
                (channel.id,),
            )
        logging.info("recovering %d missing video(s) for %s", len(missing), channel.id)
        recovered = scheduler.downloader.recovery.recover_videos(channel, missing)
        still = [v for v in missing if v.video_id not in recovered]
        for v in still:
            scheduler.state.record_failure(v.video_id, "all recovery strategies failed")
        scheduler.state.update_latest_from_downloaded(channel.id)
        total_recovered += len(recovered)
        total_still_failed += len(still)
        logging.info("%s: %d/%d recovered", channel.id, len(recovered), len(missing))
    logging.info("total: %d recovered, %d still failed", total_recovered, total_still_failed)
    return 0


def _watch(args: argparse.Namespace, config: AppConfig) -> int:
    scheduler = _build_scheduler(config)
    channels = load_channels(args.config)
    settings_path = Path(args.config)
    last_mtime = settings_path.stat().st_mtime
    while True:
        try:
            current_mtime = settings_path.stat().st_mtime
            if current_mtime != last_mtime:
                channels = load_channels(args.config)
                last_mtime = current_mtime
                logging.info("reloaded channels from %s", args.config)
        except Exception:
            logging.exception("failed to reload channels from %s; using existing list", args.config)

        if config.refresh_cookies and config.cookies_from_browser:
            try:
                output = config.cookies_file or Path("cookies.txt")
                refresh_cookies(config.cookies_from_browser, output)
                logging.info("refreshed cookies in %s", output)
            except Exception:
                logging.exception("cookie refresh failed; continuing with existing cookies")
        try:
            scheduler.run(
                channels,
                force=args.force,
                channel_ids=args.channel or None,
                max_downloads=args.max_downloads,
            )
        except Exception:
            logging.exception("scheduler run failed")
        logging.info("sleeping %d seconds", args.interval)
        time.sleep(args.interval)


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--force", action="store_true", help="bypass interval checks")
    p.add_argument("--channel", action="append", help="run only this channel id")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TikTok download scheduler")
    parser.add_argument("-c", "--config", default="settings.toml", help="channel config")

    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one download cycle")
    _add_common_args(run_p)
    run_p.add_argument(
        "-n", "--max-downloads", type=int, default=None, help="download at most N videos total, shared across all channels"
    )
    run_p.set_defaults(func=_run)

    watch_p = sub.add_parser("watch", help="run continuously")
    _add_common_args(watch_p)
    watch_p.add_argument(
        "-i", "--interval", type=int, default=21600, help="seconds between runs (default 21600)"
    )
    watch_p.add_argument(
        "-n", "--max-downloads", type=int, default=None, help="download at most N videos total, shared across all channels"
    )
    watch_p.set_defaults(func=_watch)

    resolve_p = sub.add_parser("resolve", help="resolve channel ids and update config")
    resolve_p.set_defaults(func=_resolve)

    status_p = sub.add_parser("status", help="show download status for all channels")
    status_p.set_defaults(func=_status)

    backfill_p = sub.add_parser("backfill-thumbnails", help="ensure all videos and channel folders have Emby thumbnails")
    backfill_p.set_defaults(func=_backfill_thumbnails)

    refresh_p = sub.add_parser("refresh-cookies", help="export browser cookies to cookies.txt")
    refresh_p.add_argument("-b", "--browser", default=None, help="browser name (default: TIKTOK_COOKIES_FROM_BROWSER)")
    refresh_p.add_argument("-o", "--output", default="cookies.txt", help="output cookie file")
    refresh_p.set_defaults(func=_refresh_cookies)

    recover_p = sub.add_parser("recover", help="recover failed downloads with fallback strategies")
    _add_common_args(recover_p)
    recover_p.set_defaults(func=_recover)

    args = parser.parse_args(argv)
    config = load_env_config()
    _setup_logging(config.log_level)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
