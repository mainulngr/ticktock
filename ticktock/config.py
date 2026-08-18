"""Configuration loading and persistence."""

import os
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from .models import Channel
from .utils import ensure_dir, to_slug


@dataclass
class AppConfig:
    download_base_dir: Path
    state_db_path: Path
    min_interval: timedelta
    log_level: str
    cookies_file: Path | None
    cookies_from_browser: str | None
    refresh_cookies: bool
    sleep_requests: float | None
    sleep_interval: float | None
    max_sleep_interval: float | None
    yt_dlp_path: str


def load_env() -> None:
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path, override=True)


def _float_env(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default).lower())
    return value.lower() in ("1", "true", "yes", "on")


def load_env_config() -> AppConfig:
    load_env()
    return AppConfig(
        download_base_dir=Path(os.getenv("DOWNLOAD_BASE_DIR", "downloads")),
        state_db_path=Path(os.getenv("STATE_DB_PATH", "data/state.db")),
        min_interval=timedelta(seconds=int(os.getenv("MIN_INTERVAL_SECONDS", "3600"))),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cookies_file=Path(c) if (c := os.getenv("TIKTOK_COOKIES_FILE")) else None,
        cookies_from_browser=os.getenv("TIKTOK_COOKIES_FROM_BROWSER") or None,
        refresh_cookies=_bool_env("TIKTOK_REFRESH_COOKIES"),
        sleep_requests=_float_env("YT_DLP_SLEEP_REQUESTS"),
        sleep_interval=_float_env("YT_DLP_SLEEP_INTERVAL"),
        max_sleep_interval=_float_env("YT_DLP_MAX_SLEEP_INTERVAL"),
        yt_dlp_path=os.getenv("YT_DLP_PATH", "yt-dlp"),
    )


def _parse_channels(raw: list[dict]) -> List[Channel]:
    channels = []
    for item in raw:
        cid = item.get("id", "").strip() or to_slug(item.get("username", ""))
        username = item.get("username", "").strip()
        output_dir = item.get("output_dir", "").strip()
        if not output_dir:
            output_dir = cid
        channels.append(
            Channel(
                id=cid,
                username=username,
                name=item.get("name", "").strip(),
                sec_uid=item.get("sec_uid", "").strip(),
                output_dir=output_dir,
            )
        )
    return channels


def load_channels(path: Path | str = "settings.toml") -> List[Channel]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _parse_channels(data.get("channel", []))


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def save_channels(channels: List[Channel], path: Path | str = "settings.toml") -> None:
    lines = [
        "# TikTok channel list",
        "# Each channel has a stable `id` (never changes) plus the current `username`,",
        "# resolved `sec_uid`, and display `name`. The resolver updates username/name/sec_uid",
        "# in place while leaving `id` untouched.",
        "",
    ]
    for c in channels:
        lines.append("[[channel]]")
        lines.append(f'id = "{_escape_toml_string(c.id)}"')
        lines.append(f'username = "{_escape_toml_string(c.username)}"')
        lines.append(f'name = "{_escape_toml_string(c.name)}"')
        lines.append(f'sec_uid = "{_escape_toml_string(c.sec_uid)}"')
        lines.append(f'output_dir = "{_escape_toml_string(c.output_dir)}"')
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def ensure_paths(config: AppConfig) -> AppConfig:
    ensure_dir(config.download_base_dir)
    ensure_dir(config.state_db_path.parent)
    return config
