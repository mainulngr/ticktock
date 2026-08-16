---
description: "project workspace rules for ticktock"
trigger: always_on
---
# ticktock

TikTok profile download scheduler with idempotent, timestamp-sorted videos.

## Stack
- Python 3.11+
- `yt-dlp` for extraction and downloading
- TOML for channel configuration
- SQLite for persistent download state
- `.env` for secrets/paths

## Directory structure
- `ticktock/`: application source (SRP modules)
- `settings.toml`: channel list with stable ids and usernames
- `.env` / `.env.example`: environment and secrets
- `_journal/`: task inbox and post-execution reports
- `downloads/`: default video output (gitignored)
- `data/`: state and cache (gitignored)

## Key commands
- `python -m ticktock --run` — one-shot scheduled download
- `python -m ticktock --watch --interval 21600` — run every 6 hours
- `python -m ticktock --resolve` — resolve channel ids/names and update settings.toml
- `pip install -r requirements.txt` — install dependencies

## Architectural notes
- Each channel has a stable `id` (derived from first-known username) plus the mutable `username` and resolved `sec_uid`/`name`.
- Downloads are idempotent by video id; state is stored in `data/state.db`.
- Output filenames use `YYYYMMDD_HHMMSS_<video_id>` for old-to-new sorting in any player.
- Scheduler respects `min_interval` and per-channel `last_checked_at` to avoid hammering TikTok.
