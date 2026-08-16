# ticktock

Idempotent TikTok profile download scheduler with timestamped filenames and stable channel ids.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

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
```

Resolve names and ids:

```bash
python -m ticktock resolve
```

## Run

One-shot:

```bash
python -m ticktock run
```

Watch mode (every 6 hours by default):

```bash
python -m ticktock watch --interval 21600
```

Check a single channel:

```bash
python -m ticktock run --channel dhdud3516
```

## How it works

- Downloads are stored under `downloads/<channel_id>/`.
- Filenames start with the upload date and time: `YYYYMMDD_HHMMSS_<video_id>_<title>.mp4`.
- State is kept in `data/state.db` and `data/yt-dlp-archive.txt`; reruns skip already-downloaded videos.
- Scheduler respects `MIN_INTERVAL_SECONDS` (default 1 hour) per channel.
