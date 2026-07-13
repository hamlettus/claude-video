#!/usr/bin/env python3
"""Discover trending long-form YouTube videos as raw material for shorts.

Uses yt-dlp to enumerate a trending feed (or any playlist/channel URL) without
downloading, filters to genuine long-form clips, and drops anything already in
the processed-state file so an autonomous loop never re-uses the same source.

Only public metadata is read — no login, no cookies, no posting.

Usage:
    python3 trending.py                       # default trending feed as JSON
    python3 trending.py --max 5 --min-seconds 300
    python3 trending.py --source "<playlist-or-channel-url>"
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from shorts_config import get, state_dir  # noqa: E402

PROCESSED_FILE = "processed.json"


def load_processed() -> set[str]:
    path = state_dir() / PROCESSED_FILE
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def mark_processed(video_id: str) -> None:
    path = state_dir() / PROCESSED_FILE
    ids = load_processed()
    ids.add(video_id)
    path.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def discover(source: str, limit: int, min_seconds: int) -> list[dict]:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Run setup.py (brew/apt install yt-dlp).")

    # --flat-playlist keeps this to one network round-trip; -J emits a JSON tree.
    cmd = [
        "yt-dlp",
        "-J",
        "--flat-playlist",
        "--no-warnings",
        "--playlist-end", str(max(limit * 6, 30)),
        "--",
        source,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise SystemExit(f"yt-dlp trending fetch failed:\n{proc.stderr.strip()[:800]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit("yt-dlp did not return JSON for the trending source")

    entries = data.get("entries") or []
    processed = load_processed()
    out: list[dict] = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id")
        if not vid or vid in processed:
            continue
        duration = entry.get("duration") or 0
        # Flat playlists sometimes omit duration; keep those (verified downstream).
        if duration and duration < min_seconds:
            continue
        out.append({
            "id": vid,
            "title": entry.get("title"),
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "duration": duration,
            "uploader": entry.get("uploader") or entry.get("channel"),
            "view_count": entry.get("view_count"),
        })
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="trending", description="List trending long-form videos as JSON.")
    ap.add_argument("--source", default=get("SHORTS_TRENDING_SOURCE"), help="Trending feed / playlist / channel URL")
    ap.add_argument("--max", type=int, default=8, help="Max candidates to return")
    ap.add_argument("--min-seconds", type=int, default=int(get("SHORTS_MIN_SOURCE_SECONDS")),
                    help="Minimum source duration to count as long-form")
    ap.add_argument("--mark", default=None, help="Mark a video id as processed and exit")
    args = ap.parse_args()

    if args.mark:
        mark_processed(args.mark)
        print(f"marked {args.mark} processed")
        return 0

    candidates = discover(args.source, args.max, args.min_seconds)
    print(json.dumps({"source": args.source, "count": len(candidates), "candidates": candidates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
