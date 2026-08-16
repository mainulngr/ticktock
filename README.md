# ticktock

TikTok profile download scheduler. Downloads videos on a schedule, stores them with chronological filenames, and skips already-downloaded content. No playback — use your own video player.

## Setup

```bash
just setup
# or manually:
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Optional: copy .env.example and fill in
# cp .env.example .env
```

## Configure channels

Edit `settings.toml`. Each channel has a stable `id` (never changes) and the current `username`.

```toml
[[channel]]
id = "dhdud3516"
username = "dhdud3516"
name = ""
sec_uid = ""
output_dir = "dhdud3516"
```

Resolve names and stable ids (`sec_uid`) from TikTok:

```bash
just resolve
# or: .venv/bin/python -m ticktock resolve
```

Once `sec_uid` is resolved, the scheduler uses `https://www.tiktok.com/@<sec_uid>` instead of the username, so username changes do not break downloads.

## Run

One-shot:

```bash
just run
# or: .venv/bin/python -m ticktock run
```

Watch mode (every 6 hours by default):

```bash
just watch
# or: .venv/bin/python -m ticktock watch --interval 21600
```

Test one download per channel:

```bash
just verify
# or: .venv/bin/python -m ticktock --force run --max-downloads 1
```

Check a single channel:

```bash
just run -- --channel dhdud3516
```

Limit how many videos to pull in a single run:

```bash
just run -- --max-downloads 5
```

## Just recipes

```
just setup    # create venv and install deps
just resolve  # resolve channel names/sec_uids
just run      # one-shot download
just watch    # continuous download
just verify   # one download per channel
just summary  # list downloaded files
just clean    # remove downloads and state
```

## How it works

- Downloads are stored under `downloads/<channel_id>/`.
- Filenames start with the upload date and time: `YYMMDD_HHMMSS_<video_id>.mp4` for chronological sorting.
- State is kept in `data/state.db` and `data/yt-dlp-archive.txt`; reruns skip already-downloaded videos.
- Scheduler respects `MIN_INTERVAL_SECONDS` (default 1 hour) per channel.
- Use `TIKTOK_COOKIES_FILE` in `.env` if TikTok blocks unauthenticated requests.
