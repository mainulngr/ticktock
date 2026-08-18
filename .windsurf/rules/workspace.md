---
description: "project workspace rules for ticktock"
trigger: always_on
---
# ticktock

TikTok profile download scheduler. Downloads videos on a schedule with chronological filenames. No playback.

## Stack
- Python 3.11+
- `yt-dlp` for extraction and downloading
- TOML for channel configuration
- SQLite for persistent download state
- `just` for task recipes
- `.env` for secrets/paths

## Directory structure
- `ticktock/`: application source (SRP modules)
- `settings.toml`: channel list with stable ids and usernames
- `justfile`: common commands
- `.env` / `.env.example`: environment and secrets
- `_journal/`: task inbox and post-execution reports
- `downloads/`: default video output (gitignored)
- `data/`: state and cache (gitignored)

## Key commands
- `just setup` — create venv and install dependencies
- `just resolve` — resolve channel ids/names and update settings.toml
- `just run` — one-shot scheduled download
- `just run --force` — start immediately, bypass per-channel interval
- `just run --max-downloads 5` — limit videos per run
- `just run --channel dhdud3516` — run one channel only
- `just watch` — run continuously every 6 hours
- `just verify` — test one download per channel
- `just summary` — list downloaded files
- `just status` — per-channel completion and pending count
- `just refresh-cookies` — export Vivaldi cookies to `cookies.txt`
- `just clean` — remove downloads and state
- `just clean-slate` — remove downloads and state with confirmation

## Architectural notes
- Each channel has a stable `id` (derived from first-known username) plus the mutable `username` and resolved `sec_uid`/`name`.
- `Channel.url()` prefers the stable `sec_uid` over the username, so username changes do not break profile lookups once resolved.
- Downloads are idempotent by video id; state is stored in `data/state.db` and a `data/yt-dlp-archive.txt`.
- Output filenames use `YYMMDD_HHMMSS_<video_id>` for chronological sorting.
- Scheduler respects `min_interval` and per-channel `last_checked_at` to avoid hammering TikTok.
- `.env` supports `TIKTOK_COOKIES_FILE` / `TIKTOK_COOKIES_FROM_BROWSER`, optional `TIKTOK_REFRESH_COOKIES=true` (re-export from browser before each cycle), and yt-dlp sleep options to mitigate 429 rate limits.
- `just refresh-cookies` only keeps TikTok-domain cookies, not the whole browser session.
