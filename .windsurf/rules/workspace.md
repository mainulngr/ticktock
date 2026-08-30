---
description: "project workspace rules for ticktock"
trigger: always_on
---
# ticktock

TikTok profile download scheduler. Downloads videos on a schedule with chronological filenames. No playback.

## Stack
- Python 3.11+
- `yt-dlp` 2026.8.19 for extraction and downloading
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
- `DOWNLOAD_BASE_DIR` (currently `/mega/sata/tocks/`): video output (configured in `.env`)
- `data/`: state and cache (gitignored)

## Key commands
- `just setup` — create venv and install dependencies
- `just resolve` — resolve channel ids/names and update settings.toml
- `just run` — one-shot scheduled download
- `just run --force` — start immediately, bypass per-channel interval
- `just run --max-downloads 5` — limit videos per run
- `just run --channel dhdud3516` — run one channel only
- `just watch` — run continuously every `MIN_INTERVAL_SECONDS`
- `just log-trim` — keep only the last 10,000 lines of `data/scheduler.log`
- `just log-clear` — empty `data/scheduler.log`
- `just stop` — stop the running scheduler and any orphaned yt-dlp child processes
- `just restart` — stop and restart the scheduler (trims log and sleeps 2 minutes between cycles)
- `just verify` — test one download per channel
- `just summary` — list downloaded files
- `just status` — per-channel completion, pending, and failed count
- `just refresh-cookies` — export Vivaldi cookies to `cookies.txt`
- `just clean` — remove downloads and state
- `just clean-slate` — remove downloads and state with confirmation

## Architectural notes
- Each channel has a stable `id` (derived from first-known username) plus the mutable `username` and resolved `sec_uid`/`name`.
- `Channel.url()` prefers the stable `sec_uid` over the username, so username changes do not break profile lookups once resolved.
- Downloads are idempotent by video id; state is stored in `data/state.db` and a `data/yt-dlp-archive.txt`.
- Output filenames use `YYMMDD_HHMMSS_<video_id>` for chronological sorting.
- Scheduler respects `min_interval` and per-channel `last_checked_at` to avoid hammering TikTok.
- `.env` supports `DOWNLOAD_BASE_DIR`, `TIKTOK_COOKIES_FILE` / `TIKTOK_COOKIES_FROM_BROWSER`, optional `TIKTOK_REFRESH_COOKIES=true` (re-export from browser before each cycle), `MIN_INTERVAL_SECONDS` (per-channel due interval), `LIST_CACHE_TTL` (cache channel listings), `LIST_MAX_ITEMS` (cap channel listings, default no limit), `SLEEP_BETWEEN_CHANNELS` (pause between channels), yt-dlp sleep options, `FAILED_RETRY_COOLDOWN_SECONDS` (default 21600 = 6h), and `MAX_FAILED_RETRIES` (default 3) for cooldown-based failed download retry.
- `just refresh-cookies` only keeps TikTok-domain cookies, not the whole browser session. Cookies are used for profile listing but omitted from public video downloads because they can invalidate TikTok challenge responses.
- Actual download batches retry the complete yt-dlp command up to three times to tolerate intermittent malformed TikTok challenge pages; archived successes are skipped on retry.
- Channel listings are cached under `data/list_cache/` so `max-downloads` runs do not re-list the whole channel every time.
- Download order is oldest-first: the scheduler backfills the oldest pending video for the most-backlogged channel each run, then moves forward in time.
- The `videos` table tracks `failed`, `retries`, and `failed_at` to retry transient failures with a cooldown, and mark permanently unavailable videos as failed after `MAX_FAILED_RETRIES`.
- `just status` shows `listed`, `done`, `pending`, and `failed`; percent is `done / listed`, and a channel with only failed entries is shown as `blocked`, not `done`.
- The `TIKTOK_COOKIES_FILE` path is resolved to absolute so yt-dlp does not create stray `cookies.txt` files inside channel output folders.
- The scheduler is sticky: it picks the due channel with the most pending videos and keeps downloading from that same channel across cycles until its pending count reaches zero, then moves to the next most-backlogged channel. When a focus channel has pending videos but produces no downloads, it is marked stalled and skipped for one interval so the scheduler does not loop on a broken/stale channel. When no pending backlog is due, the scheduler checks the oldest due never-listed channel to initialize new profiles and then falls back to caught-up profiles to discover new uploads.
- The downloader merges DB pending videos with fresh/cached listings, so older pending videos that are missing from a stale list cache are still attempted.
