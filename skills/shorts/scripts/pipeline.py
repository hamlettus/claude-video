#!/usr/bin/env python3
"""End-to-end orchestrator for the shorts factory.

The creative step — turning a video's transcript into a punchy stick-figure
storyboard — is done by the model (see SKILL.md), the same way /watch hands
frames to Claude. This module automates everything *around* that judgement:

  discover  -> list fresh trending long-form candidates (skips already-used)
  build     -> render storyboard.json (+ optional voiceover) into a short,
               write per-platform metadata, and log the result to the ledger
  ledger    -> show what's been produced

A fully autonomous daily run is: `discover` -> model watches + writes a
storyboard/meta -> `build` -> `publish.py` (dry-run, or --live once creds and a
public URL exist). Wire it to cron for a hands-off page (see SKILL.md).

Usage:
    python3 pipeline.py discover --max 5
    python3 pipeline.py build --storyboard sb.json --meta meta.json \
        --source-id dQw4 --out out/short.mp4 [--voiceover-script script.txt]
    python3 pipeline.py ledger
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

import animate  # noqa: E402
import trending  # noqa: E402
from shorts_config import get, state_dir  # noqa: E402

LEDGER_FILE = "ledger.json"


def _ledger_path() -> Path:
    return state_dir() / LEDGER_FILE


def load_ledger() -> list[dict]:
    p = _ledger_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_ledger(entry: dict) -> None:
    ledger = load_ledger()
    ledger.append(entry)
    _ledger_path().write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def cmd_discover(args) -> int:
    candidates = trending.discover(
        args.source or get("SHORTS_TRENDING_SOURCE"),
        args.max,
        args.min_seconds or int(get("SHORTS_MIN_SOURCE_SECONDS")),
    )
    print(json.dumps({"count": len(candidates), "candidates": candidates}, indent=2))
    return 0


def cmd_build(args) -> int:
    storyboard = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    problems = animate.validate(storyboard)
    if problems:
        print("Storyboard invalid:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    animate._apply_defaults(storyboard)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    voiceover_path = None
    if args.voiceover_script:
        import voiceover  # local import keeps discover/build usable without TTS deps
        script = Path(args.voiceover_script).read_text(encoding="utf-8").strip()
        voiceover_path = str(out.with_suffix(".vo.mp3"))
        voiceover.synthesize(script, voiceover_path)
        print(f"[shorts] voiceover -> {voiceover_path}", file=sys.stderr)

    animate.render_video(
        storyboard, str(out),
        voiceover=voiceover_path,
        music=args.music,
    )
    # Thumbnail from the opening frame.
    thumb = str(out.with_suffix(".thumb.png"))
    animate.render_thumbnail(storyboard, thumb)

    meta = {}
    if args.meta:
        meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    meta_out = str(out.with_suffix(".meta.json"))
    Path(meta_out).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if args.source_id:
        trending.mark_processed(args.source_id)

    entry = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_id": args.source_id,
        "video": str(out),
        "thumbnail": thumb,
        "meta": meta_out,
        "duration": round(animate.sm.total_duration(storyboard), 2),
        "voiceover": voiceover_path,
    }
    append_ledger(entry)
    print(json.dumps(entry, indent=2))
    return 0


def cmd_ledger(_args) -> int:
    print(json.dumps(load_ledger(), indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="pipeline", description="Shorts factory orchestrator.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="List fresh trending long-form candidates")
    d.add_argument("--source", default=None)
    d.add_argument("--max", type=int, default=5)
    d.add_argument("--min-seconds", type=int, default=None)
    d.set_defaults(func=cmd_discover)

    b = sub.add_parser("build", help="Render a storyboard into a short + metadata, log to ledger")
    b.add_argument("--storyboard", required=True)
    b.add_argument("--meta", default=None)
    b.add_argument("--out", default="out/short.mp4")
    b.add_argument("--source-id", default=None, help="YouTube id of the source video (marked processed)")
    b.add_argument("--voiceover-script", default=None, help="Text file to narrate via TTS")
    b.add_argument("--music", default=None)
    b.set_defaults(func=cmd_build)

    lg = sub.add_parser("ledger", help="Print the production ledger")
    lg.set_defaults(func=cmd_ledger)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
