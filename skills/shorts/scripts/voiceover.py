#!/usr/bin/env python3
"""Optional narration for a short — free by default, pluggable backends.

Turns a script into a speech audio file. TTS can't be pure-stdlib (it needs
either a local model or a network call), but it CAN be free. So this defaults
to a free backend and only touches a paid API if you explicitly pick one.

Backends (choose via SHORTS_TTS or --backend):
  edge        FREE, no key. Microsoft Edge neural voices via the `edge-tts`
              package. Best quality-for-free; needs internet. (default)
  piper       FREE, offline. Local neural TTS via the `piper` binary + a voice
              model (.onnx). No key, no network after the one-time model
              download. Set SHORTS_PIPER_MODEL (and optionally SHORTS_PIPER_BIN).
  gtts        FREE, no key. Google Translate TTS via the `gtts` package. Simple,
              a little flat; needs internet.
  openai      PAID. OPENAI_API_KEY. /v1/audio/speech.
  elevenlabs  PAID. ELEVENLABS_API_KEY (+ optional ELEVENLABS_VOICE_ID). Best
              cloning, but overkill for most shorts.

`synthesize()` returns the actual output path written (the extension may differ
from what you requested — e.g. piper emits WAV — so always use the return value).

Usage:
    python3 voiceover.py "Here's why nobody noticed." -o vo.mp3
    python3 voiceover.py --file script.txt --backend piper -o vo.wav
    python3 voiceover.py --file script.txt --backend edge --voice en-US-AriaNeural
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from shorts_config import get  # noqa: E402

BACKENDS = ("edge", "piper", "gtts", "openai", "elevenlabs")
FREE_BACKENDS = ("edge", "piper", "gtts")


def _swap_suffix(out_path: str, suffix: str) -> str:
    return str(Path(out_path).with_suffix(suffix))


# --------------------------------------------------------------------------- #
# Free backends
# --------------------------------------------------------------------------- #


def _edge_tts(text: str, out_path: str, voice: str | None) -> str:
    """Microsoft Edge neural voices — free, no key, needs internet."""
    voice = voice or get("SHORTS_TTS_VOICE", "en-US-GuyNeural")
    out = _swap_suffix(out_path, ".mp3")
    if shutil.which("edge-tts"):
        cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", out]
    else:
        cmd = [sys.executable, "-m", "edge_tts", "--voice", voice, "--text", text, "--write-media", out]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            "edge-tts failed (install with `pip install edge-tts`, needs internet):\n"
            + (proc.stderr.strip() or proc.stdout.strip())[:600]
        )
    return out


def _piper_tts(text: str, out_path: str, voice: str | None) -> str:
    """Local neural TTS — free, offline. Needs the piper binary + a model."""
    binary = get("SHORTS_PIPER_BIN", "piper")
    if shutil.which(binary) is None:
        raise SystemExit(
            "piper binary not found. Install piper (https://github.com/rhasspy/piper) "
            "and set SHORTS_PIPER_BIN if it's not on PATH."
        )
    model = voice or get("SHORTS_PIPER_MODEL")
    if not model:
        raise SystemExit(
            "piper needs a voice model. Download one (e.g. en_US-amy-medium.onnx) and set "
            "SHORTS_PIPER_MODEL=/path/to/model.onnx (or pass it via --voice)."
        )
    out = _swap_suffix(out_path, ".wav")
    proc = subprocess.run(
        [binary, "--model", model, "--output_file", out],
        input=text, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit("piper failed:\n" + (proc.stderr.strip() or proc.stdout.strip())[:600])
    return out


def _gtts_tts(text: str, out_path: str, voice: str | None) -> str:
    """Google Translate TTS — free, no key, needs internet."""
    lang = voice or get("SHORTS_TTS_VOICE", "en")
    out = _swap_suffix(out_path, ".mp3")
    if shutil.which("gtts-cli") is None:
        raise SystemExit("gtts-cli not found. Install with `pip install gTTS` (needs internet).")
    proc = subprocess.run(["gtts-cli", text, "--lang", lang, "--output", out], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("gtts failed:\n" + (proc.stderr.strip() or proc.stdout.strip())[:600])
    return out


# --------------------------------------------------------------------------- #
# Paid backends
# --------------------------------------------------------------------------- #


def _openai_tts(text: str, out_path: str, voice: str | None, model: str) -> str:
    api_key = get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not set — use a free backend (edge/piper/gtts) or add the key.")
    out = _swap_suffix(out_path, ".mp3")
    body = json.dumps({
        "model": model, "voice": voice or "onyx", "input": text, "response_format": "mp3",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        Path(out).write_bytes(resp.read())
    return out


def _elevenlabs_tts(text: str, out_path: str, voice: str | None, model: str) -> str:
    api_key = get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY not set — use a free backend (edge/piper/gtts) or add the key.")
    voice_id = voice or get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # 'Rachel'
    out = _swap_suffix(out_path, ".mp3")
    body = json.dumps({
        "text": text,
        "model_id": model if model != "tts-1" else "eleven_multilingual_v2",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=body,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        Path(out).write_bytes(resp.read())
    return out


def synthesize(
    text: str,
    out_path: str,
    backend: str | None = None,
    voice: str | None = None,
    model: str = "tts-1",
) -> str:
    """Synthesize `text` to speech. Returns the real path written."""
    backend = (backend or get("SHORTS_TTS", "edge")).lower()
    if backend == "edge":
        return _edge_tts(text, out_path, voice)
    if backend == "piper":
        return _piper_tts(text, out_path, voice)
    if backend == "gtts":
        return _gtts_tts(text, out_path, voice)
    if backend == "openai":
        return _openai_tts(text, out_path, voice, model)
    if backend == "elevenlabs":
        return _elevenlabs_tts(text, out_path, voice, model)
    raise SystemExit(f"unknown TTS backend: {backend!r} (choose from {', '.join(BACKENDS)})")


def main() -> int:
    ap = argparse.ArgumentParser(prog="voiceover", description="Synthesize narration (free by default).")
    ap.add_argument("text", nargs="?", help="Script text (or use --file / stdin)")
    ap.add_argument("--file", default=None, help="Read script from a file")
    ap.add_argument("-o", "--out", default="voiceover.mp3", help="Output path (extension may adjust per backend)")
    ap.add_argument("--backend", default=None, choices=BACKENDS,
                    help="TTS backend (default from SHORTS_TTS, or 'edge' — free)")
    ap.add_argument("--voice", default=None,
                    help="Voice/model/lang for the backend (e.g. edge: en-US-AriaNeural; piper: model path; gtts: en)")
    ap.add_argument("--model", default="tts-1", help="Model id for paid backends")
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("no script text provided")

    out = synthesize(text, args.out, backend=args.backend, voice=args.voice, model=args.model)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
