#!/usr/bin/env python3
"""Render a storyboard JSON into a 9:16 MP4 short.

Frames are generated in pure Python (stickman.py) and streamed as raw rgb24
into ffmpeg over a pipe — no giant intermediate frame files, so a 60s/30fps
short never touches more than a few MB of disk at a time.

Usage:
    python3 animate.py storyboard.json -o short.mp4
    python3 animate.py storyboard.json -o short.mp4 --voiceover vo.mp3
    python3 animate.py storyboard.json --thumbnail thumb.png   # first frame only
    python3 animate.py --validate storyboard.json              # lint, no render
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

import stickman as sm  # noqa: E402
from shorts_config import meta_defaults  # noqa: E402

VALID_POSES = set(sm.POSES.keys())


def validate(storyboard: dict) -> list[str]:
    """Return a list of human-readable problems (empty == valid)."""
    problems: list[str] = []
    scenes = storyboard.get("scenes")
    if not scenes:
        problems.append("storyboard has no 'scenes'")
        return problems
    for si, scene in enumerate(scenes):
        if float(scene.get("duration", 0)) <= 0:
            problems.append(f"scene {si}: duration must be > 0")
        for ai, actor in enumerate(scene.get("actors", []) or []):
            kfs = actor.get("keyframes") or []
            if not kfs:
                problems.append(f"scene {si} actor {ai}: no keyframes")
            for ki, kf in enumerate(kfs):
                pose = kf.get("pose", "idle")
                if pose not in VALID_POSES:
                    problems.append(
                        f"scene {si} actor {ai} kf {ki}: unknown pose '{pose}' "
                        f"(valid: {', '.join(sorted(VALID_POSES))})"
                    )
                # Allow a generous off-canvas margin so actors can walk in from
                # or exit past the edges (e.g. x=1.05 to enter from the right).
                for coord in ("x", "y"):
                    v = kf.get(coord, 0.5)
                    if not (-0.5 <= float(v) <= 1.5):
                        problems.append(
                            f"scene {si} actor {ai} kf {ki}: {coord}={v} out of -0.5..1.5"
                        )
    return problems


def _apply_defaults(storyboard: dict) -> dict:
    meta = storyboard.setdefault("meta", {})
    for k, v in meta_defaults().items():
        meta.setdefault(k, v)
    return storyboard


def render_thumbnail(storyboard: dict, out_path: str) -> None:
    for canvas, _gi in sm.iter_frames(storyboard):
        sm.write_png(out_path, canvas)
        return


def render_video(
    storyboard: dict,
    out_path: str,
    voiceover: str | None = None,
    music: str | None = None,
    music_gain_db: float = -18.0,
    crf: int = 20,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg is not installed. Run setup.py first "
            "(brew install ffmpeg / apt install ffmpeg)."
        )
    meta = storyboard.get("meta", {})
    w = int(meta.get("width", 1080))
    h = int(meta.get("height", 1920))
    fps = int(meta.get("fps", 30))
    n_frames = sm.total_frames(storyboard)
    duration = sm.total_duration(storyboard)

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgb24",
        "-video_size", f"{w}x{h}",
        "-framerate", str(fps),
        "-i", "-",  # video frames on stdin
    ]

    audio_inputs = 0
    filter_parts: list[str] = []
    if voiceover:
        cmd += ["-i", voiceover]
        audio_inputs += 1
    if music:
        cmd += ["-i", music]
        audio_inputs += 1

    # Build an audio graph if we have any audio, else silent short.
    map_args: list[str] = ["-map", "0:v:0"]
    if audio_inputs == 2:
        filter_parts.append(
            f"[2:a]volume={music_gain_db}dB[bg];"
            f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        map_args += ["-map", "[aout]"]
    elif audio_inputs == 1:
        map_args += ["-map", "1:a:0"]

    if filter_parts:
        cmd += ["-filter_complex", ";".join(filter_parts)]

    cmd += map_args
    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", f"{duration:.3f}",
    ]
    if audio_inputs:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [out_path]

    print(
        f"[shorts] encoding {n_frames} frames ({duration:.1f}s @ {fps}fps, {w}x{h}) -> {out_path}",
        file=sys.stderr,
    )
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=sys.stderr, stderr=sys.stderr)
    assert proc.stdin is not None
    try:
        written = 0
        for canvas, _gi in sm.iter_frames(storyboard):
            proc.stdin.write(bytes(canvas.buf))
            written += 1
            if written % fps == 0:
                print(f"[shorts]   {written}/{n_frames} frames", file=sys.stderr)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    ret = proc.wait()
    if ret != 0:
        raise SystemExit(f"ffmpeg exited {ret}")
    print(f"[shorts] done: {out_path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(prog="animate", description="Render a stick-figure short from a storyboard.")
    ap.add_argument("storyboard", help="Path to storyboard JSON")
    ap.add_argument("-o", "--out", default="short.mp4", help="Output MP4 path")
    ap.add_argument("--voiceover", default=None, help="Voiceover audio file to mux (mp3/m4a/wav)")
    ap.add_argument("--music", default=None, help="Background music file (ducked under voiceover)")
    ap.add_argument(
        "--soundtrack",
        nargs="?",
        const="upbeat",
        default=None,
        choices=["upbeat", "tense", "chill"],
        help="Generate a royalty-free chiptune bed (pure stdlib) matched to the "
             "short's length and mux it in. Optional mood (default: upbeat). "
             "Ignored if --music is given.",
    )
    ap.add_argument("--music-gain", type=float, default=-18.0, help="Music gain in dB (default -18)")
    ap.add_argument("--crf", type=int, default=20, help="x264 CRF quality (lower = better, default 20)")
    ap.add_argument("--thumbnail", default=None, help="Write the first frame as PNG here and exit")
    ap.add_argument("--validate", action="store_true", help="Validate the storyboard and exit")
    args = ap.parse_args()

    storyboard = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))

    problems = validate(storyboard)
    if problems:
        print("Storyboard validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if args.validate:
        print(
            f"OK: {len(storyboard['scenes'])} scenes, "
            f"{sm.total_duration(storyboard):.1f}s, {sm.total_frames(storyboard)} frames"
        )
        return 0

    _apply_defaults(storyboard)

    if args.thumbnail:
        render_thumbnail(storyboard, args.thumbnail)
        print(args.thumbnail)
        return 0

    music = args.music
    if music is None and args.soundtrack:
        import soundtrack  # stdlib-only; imported lazily so silent renders skip it
        bed = str(Path(args.out).with_suffix(".bed.wav"))
        soundtrack.write_wav(bed, soundtrack.synth(sm.total_duration(storyboard), mood=args.soundtrack))
        print(f"[shorts] soundtrack ({args.soundtrack}) -> {bed}", file=sys.stderr)
        music = bed

    render_video(
        storyboard,
        args.out,
        voiceover=args.voiceover,
        music=music,
        music_gain_db=args.music_gain,
        crf=args.crf,
    )
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
