"""Small, reusable helpers."""

import re
from pathlib import Path


def to_slug(text: str) -> str:
    """Convert a string into a filesystem-safe, stable slug."""
    text = text.strip().lower()
    text = text.replace("/", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
