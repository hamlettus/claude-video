#!/usr/bin/env python3
"""Shared /shorts configuration.

Config + credentials live in ~/.config/shorts/.env (mode 0600). Nothing here
is ever printed; publish.py reads tokens straight from this file.
"""
from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "shorts"
CONFIG_FILE = CONFIG_DIR / ".env"

# Vertical 9:16 defaults tuned for Reels / Shorts / IG.
DEFAULTS = {
    "SHORTS_WIDTH": "1080",
    "SHORTS_HEIGHT": "1920",
    "SHORTS_FPS": "30",
    "SHORTS_BG": "#0e1116",
    "SHORTS_FG": "#f5f5f5",
    "SHORTS_ACCENT": "#ffca28",
    "SHORTS_MIN_SOURCE_SECONDS": "180",   # "long form" trending threshold
    "SHORTS_MAX_SHORT_SECONDS": "60",
    "SHORTS_TRENDING_SOURCE": "https://www.youtube.com/feed/trending",
    "SHORTS_PUBLISH": "dry-run",          # dry-run | live  (never auto-live)
}


def read_env_file(path: Path | None = None) -> dict[str, str]:
    if path is None:
        path = CONFIG_FILE
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            for i, ch in enumerate(value):
                if ch == "#" and i > 0 and value[i - 1] in " \t":
                    value = value[:i].rstrip()
                    break
        values[key.strip()] = value
    return values


def get(key: str, default: str | None = None) -> str | None:
    """Precedence: process env > config file > built-in default > `default`."""
    if key in os.environ:
        return os.environ[key]
    file_values = read_env_file()
    if key in file_values:
        return file_values[key]
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default


def meta_defaults() -> dict:
    return {
        "width": int(get("SHORTS_WIDTH")),
        "height": int(get("SHORTS_HEIGHT")),
        "fps": int(get("SHORTS_FPS")),
        "bg": get("SHORTS_BG"),
        "fg": get("SHORTS_FG"),
        "accent": get("SHORTS_ACCENT"),
    }


def state_dir() -> Path:
    d = Path(get("SHORTS_STATE_DIR", str(CONFIG_DIR / "state")))
    d.mkdir(parents=True, exist_ok=True)
    return d
