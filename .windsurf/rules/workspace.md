---
description: "project workspace rules for ticktock"
trigger: always_on
---
# ticktock

TikTok profile download scheduler. Downloads videos on a schedule with chronological filenames. No playback.

## Stack
- Python 3.11+
- `yt-dlp` 2026.8.19 for extraction and downloading
- `curl-cffi` 0.15.0 for Chrome TLS/browser impersonation on TikTok downloads
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
- `DOWNLOAD_BASE_DIR` (currently `/mega/media/tocks/`): video output (configured in `.env`)
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
- `just recover` — recover failed downloads for all channels with fallback strategies
- `just backfill-thumbnails` — ensure every downloaded video and channel folder has a JPEG thumbnail for Emby
- `just refresh-cookies` — export Vivaldi cookies to `cookies.txt`
- `just clean` — remove downloads and state
- `just clean-slate` — remove downloads and state with confirmation

## Architectural notes
- Each channel has a stable `id` (derived from first-known username) plus the mutable `username` and resolved `sec_uid`/`name`.
- `Channel.url()` prefers the stable `sec_uid` over the username, so username changes do not break profile lookups once resolved.
- Downloads are idempotent by video id; state is stored in `data/state.db` and a `data/yt-dlp-archive.txt`.
- Output filenames use `YYMMDD_HHMMSS_<video_id>` for chronological sorting.
- Scheduler respects `min_interval` and per-channel `last_checked_at` to avoid hammering TikTok.
- `.env` supports `DOWNLOAD_BASE_DIR`, `TIKTOK_COOKIES_FILE` / `TIKTOK_COOKIES_FROM_BROWSER`, optional `TIKTOK_REFRESH_COOKIES=true` (re-export from browser before each cycle), `THUMBNAIL_FFMPEG_PATH` (local JPEG thumbnail extraction, default `ffmpeg`), `MIN_INTERVAL_SECONDS` (per-channel due interval), `LIST_CACHE_TTL` (cache channel listings), `LIST_MAX_ITEMS` (cap channel listings, default no limit), `SLEEP_BETWEEN_CHANNELS` (pause between channels), yt-dlp sleep options, `YT_DLP_PROXY` (proxy only download requests through e.g. a local SOCKS5 gateway), `FAILED_RETRY_COOLDOWN_SECONDS` (default 21600 = 6h), and `MAX_FAILED_RETRIES` (default 3) for cooldown-based failed download retry.
- `just refresh-cookies` only keeps TikTok-domain cookies, not the whole browser session. Cookies are used for profile listing but omitted from public video downloads because they can invalidate TikTok challenge responses.
- Actual download batches use the project virtualenv yt-dlp with Chrome impersonation and pass `--ignore-errors`, so one malformed/unavailable video does not abort the rest of the batch; failed videos are retried later by the scheduler instead of immediately.
- The downloader now runs a `Recovery` fallback after a failed batch: browser cookies, the TikTok `cookies.txt` file, and the embed page URL (`/embed/v2/{video_id}`) are tried before giving up.
- `just recover` resets and re-attempts all missing downloads across every channel using the same fallback chain.
- Channel listings are cached under `data/list_cache/` so `max-downloads` runs do not re-list the whole channel every time.
- Download order is oldest-first: the scheduler backfills the oldest fresh pending video for the due channel with the oldest `last_checked_at` each run, then moves forward in time.
- The `videos` table tracks `failed`, `retries`, and `failed_at` to retry transient failures with a cooldown, and mark permanently unavailable videos as failed after `MAX_FAILED_RETRIES`.
- `just status` shows `listed`, `done`, `pending`, and `failed`; percent is `done / listed`, and a channel with only failed entries is shown as `blocked`, not `done`.
- The `TIKTOK_COOKIES_FILE` path is resolved to absolute so yt-dlp does not create stray `cookies.txt` files inside channel output folders.
- The scheduler rotates through due channels: it first initializes never-listed profiles, then downloads the oldest fresh pending videos for the due channel with the oldest `last_checked_at` each run, then falls back to cooldown-retry pending videos only when no fresh pending remains. A channel with fresh pending videos that produces no downloads is marked stalled and skipped for one interval. When no pending work exists, the fallback picks the least-recently-checked due channel instead of the first channel in the list.
- `watch` mode checks `settings.toml` for changes on each cycle and reloads the channel list without a process restart, so newly added profiles are picked up while the scheduler is running.
- The downloader merges fresh DB pending videos with fresh/cached listings, so older pending videos that are missing from a stale list cache are still attempted.
- Emby exposes `Tocks` as a native home-videos library with real-time monitoring. Channel directories are browsed directly as folders; there are no custom collections or scheduler/API integration.
- After each successful download, `Thumbnailer` extracts a frame at 1 second to an atomic matching `.jpg` sidecar. Emby uses this `{video-name}.jpg` file as the video's primary image, and the first available thumbnail is copied atomically to `folder.jpg` for the channel card.
- A systemd user service at `~/.config/systemd/user/ticktock.service` runs `ticktock watch --interval 120` and is enabled to start on boot; user-linger is enabled so it survives logout/reboot.
