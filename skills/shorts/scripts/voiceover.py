#!/usr/bin/env python3
"""Optional narration for a short.

Turns a script into an MP3 via a text-to-speech API when a key is configured.
Pure stdlib (urllib). If no key is set, the short is simply rendered silent —
captions still carry the message, so a voiceover is an enhancement, not a
requirement.

Supported backends (choose via SHORTS_TTS or --backend):
  - openai   : OpenAI /v1/audio/speech   (OPENAI_API_KEY)

Usage:
    python3 voiceover.py "Here's why nobody noticed." -o vo.mp3
    python3 voiceover.py --file script.txt -o vo.mp3 --voice onyx
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from shorts_config import get  # noqa: E402


def _openai_tts(text: str, out_path: str, voice: str, model: str) -> None:
    api_key = get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not set — add it to ~/.config/shorts/.env or run silent.")
    body = json.dumps({
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": "mp3",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    Path(out_path).write_bytes(data)


def synthesize(text: str, out_path: str, backend: str | None = None, voice: str = "onyx", model: str = "tts-1") -> str:
    backend = backend or get("SHORTS_TTS", "openai")
    if backend == "openai":
        _openai_tts(text, out_path, voice, model)
    else:
        raise SystemExit(f"unknown TTS backend: {backend}")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(prog="voiceover", description="Synthesize narration audio for a short.")
    ap.add_argument("text", nargs="?", help="Script text (or use --file)")
    ap.add_argument("--file", default=None, help="Read script from a file")
    ap.add_argument("-o", "--out", default="voiceover.mp3", help="Output MP3 path")
    ap.add_argument("--backend", default=None, help="TTS backend (default from SHORTS_TTS or 'openai')")
    ap.add_argument("--voice", default="onyx", help="Voice name")
    ap.add_argument("--model", default="tts-1", help="TTS model")
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("no script text provided")

    synthesize(text, args.out, backend=args.backend, voice=args.voice, model=args.model)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
