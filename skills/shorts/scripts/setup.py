#!/usr/bin/env python3
"""Setup / preflight for /shorts.

Modes:
  setup.py --check   Silent preflight. Exit 0 if ready, 2 if binaries missing.
  setup.py --json    Machine-readable status.
  setup.py           Installer: auto-install deps (brew on macOS), scaffold .env.

Only ffmpeg + yt-dlp are hard requirements (frame encoding + trending fetch).
TTS and publishing credentials are optional — the factory renders silent,
caption-only shorts and dry-run publishes without any keys. So unlike /watch,
there is no "needs key" gate: exit 0 as soon as the binaries are present.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "shorts"
CONFIG_FILE = CONFIG_DIR / ".env"
REQUIRED_BINARIES = ["ffmpeg", "ffprobe", "yt-dlp"]

ENV_TEMPLATE = """# /shorts configuration — autonomous stick-figure shorts factory
#
# All keys below are OPTIONAL. With none set, /shorts renders silent,
# caption-only shorts and every publish is a dry-run. Add credentials only for
# the platforms/features you want to go live.

# --- Rendering defaults (safe to leave as-is) ---
# SHORTS_WIDTH=1080
# SHORTS_HEIGHT=1920
# SHORTS_FPS=30
# SHORTS_BG=#0e1116
# SHORTS_FG=#f5f5f5
# SHORTS_ACCENT=#ffca28
# SHORTS_MIN_SOURCE_SECONDS=180
# SHORTS_TRENDING_SOURCE=https://www.youtube.com/feed/trending

# --- Optional narration (text-to-speech) ---
# OPENAI_API_KEY=

# --- Optional publishing credentials (dry-run until you pass --live) ---
# YouTube Data API v3 (OAuth access token with youtube.upload scope):
# YT_ACCESS_TOKEN=
# Instagram Graph API (Reels) — needs a public MP4 URL at publish time:
# IG_USER_ID=
# IG_ACCESS_TOKEN=
# Facebook Graph API (Page Reels):
# FB_PAGE_ID=
# FB_ACCESS_TOKEN=
"""


def _check_binaries() -> list[str]:
    return [b for b in REQUIRED_BINARIES if shutil.which(b) is None]


def _scaffold_env() -> bool:
    if CONFIG_FILE.exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass
    return True


def _status() -> dict:
    missing = _check_binaries()
    return {
        "status": "ready" if not missing else "needs_install",
        "can_proceed": not missing,
        "missing_binaries": missing,
        "config_file": str(CONFIG_FILE),
        "config_exists": CONFIG_FILE.exists(),
        "platform": platform.system(),
    }


def cmd_check() -> int:
    s = _status()
    if s["can_proceed"]:
        return 0
    installer = Path(__file__).resolve()
    sys.stderr.write(
        f"[shorts] setup incomplete (missing: {', '.join(s['missing_binaries'])}). "
        f"Run: python3 {installer}\n"
    )
    return 2


def cmd_json() -> int:
    json.dump(_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _install_macos(missing: list[str]) -> tuple[bool, str]:
    if shutil.which("brew") is None:
        return False, "Homebrew not found — install from https://brew.sh then re-run."
    pkgs = sorted({"ffmpeg" if b in ("ffmpeg", "ffprobe") else b for b in missing})
    print(f"[setup] running: brew install {' '.join(pkgs)}", file=sys.stderr)
    result = subprocess.run(["brew", "install", *pkgs])
    return (result.returncode == 0), ("installed" if result.returncode == 0 else "brew install failed")


def cmd_install() -> int:
    missing = _check_binaries()
    if missing:
        system = platform.system()
        if system == "Darwin":
            ok, msg = _install_macos(missing)
            print(f"[setup] {msg}", file=sys.stderr)
            if not ok or _check_binaries():
                return 2
        elif system == "Linux":
            print("[setup] install the missing binaries:", file=sys.stderr)
            print("  ffmpeg: `sudo apt install ffmpeg` (or dnf)", file=sys.stderr)
            print("  yt-dlp: `pipx install yt-dlp` (or pip install --user yt-dlp)", file=sys.stderr)
            return 2
        elif system == "Windows":
            print("[setup] install the missing binaries:", file=sys.stderr)
            print("  ffmpeg: `winget install Gyan.FFmpeg`", file=sys.stderr)
            print("  yt-dlp: `winget install yt-dlp.yt-dlp`", file=sys.stderr)
            return 2
        else:
            print(f"[setup] install manually: {', '.join(missing)}", file=sys.stderr)
            return 2

    created = _scaffold_env()
    print(f"[setup] {'created' if created else 'exists'}: {CONFIG_FILE}")
    print("[setup] ready — /shorts can render. Publishing/TTS keys are optional (edit the .env to enable).")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] == "--check":
            return cmd_check()
        if sys.argv[1] == "--json":
            return cmd_json()
    return cmd_install()


if __name__ == "__main__":
    raise SystemExit(main())
