#!/usr/bin/env python3
"""Procedural royalty-free soundtrack — pure stdlib, no audio files needed.

Synthesizes a short chiptune-style bed (bass + arpeggio + kick + hats) matched
to a duration and mood, and writes a 16-bit mono WAV via the stdlib `wave`
module. Same ethos as stickman.py: generate the media from scratch so the skill
stays dependency-free and works offline, with nothing to license.

The output is 100% originally generated audio (simple oscillators), so it's
safe to publish under a short with no third-party rights attached.

Usage:
    python3 soundtrack.py --duration 26 -o bed.wav
    python3 soundtrack.py --duration 30 --mood tense --bpm 140 -o bed.wav
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import wave

SR = 44100  # sample rate

# Equal-tempered note frequencies (Hz) for the octaves we use.
_A4 = 440.0


def note(name: str) -> float:
    """'A2', 'C#4', 'Eb3' -> frequency in Hz."""
    steps = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    letter = name[0].upper()
    i = 1
    semis = steps[letter]
    if i < len(name) and name[i] in ("#", "b"):
        semis += 1 if name[i] == "#" else -1
        i += 1
    octave = int(name[i:])
    semis += (octave - 4) * 12
    return _A4 * (2 ** (semis / 12.0))


# mood -> (bpm, chord progression as (bass_note, [arp_notes]), wave, arp_gain)
MOODS = {
    "upbeat": (128, [
        ("A2", ["A3", "C4", "E4", "C4"]),
        ("F2", ["F3", "A3", "C4", "A3"]),
        ("C3", ["C4", "E4", "G4", "E4"]),
        ("G2", ["G3", "B3", "D4", "B3"]),
    ], "square", 0.22),
    "tense": (140, [
        ("A2", ["A3", "E4", "A4", "E4"]),
        ("A2", ["A3", "E4", "A4", "E4"]),
        ("D2", ["D3", "A3", "D4", "A3"]),
        ("E2", ["E3", "B3", "E4", "G4"]),
    ], "square", 0.20),
    "chill": (96, [
        ("A2", ["A3", "C4", "E4", "G4"]),
        ("F2", ["F3", "A3", "C4", "E4"]),
        ("C3", ["C4", "E4", "G4", "B4"]),
        ("G2", ["G3", "B3", "D4", "F4"]),
    ], "triangle", 0.18),
}


def _osc(freq: float, t: float, kind: str) -> float:
    ph = (freq * t) % 1.0
    if kind == "square":
        return 1.0 if ph < 0.5 else -1.0
    if kind == "triangle":
        return 2.0 * abs(2.0 * ph - 1.0) - 1.0
    return math.sin(2 * math.pi * ph)


def _env(i: int, n: int, attack: int = 200, release: int = 900) -> float:
    if i < attack:
        return i / attack
    if i > n - release:
        return max(0.0, (n - i) / release)
    return 1.0


def _add_note(buf: list[float], start: int, freq: float, dur: float, kind: str, amp: float) -> None:
    n = int(SR * dur)
    for i in range(n):
        idx = start + i
        if idx >= len(buf):
            break
        t = i / SR
        buf[idx] += _osc(freq, t, kind) * amp * _env(i, n)


def _add_kick(buf: list[float], start: int, amp: float = 0.9) -> None:
    n = int(SR * 0.12)
    for i in range(n):
        idx = start + i
        if idx >= len(buf):
            break
        t = i / SR
        f = 120.0 * math.exp(-t * 30.0) + 40.0   # pitch drop
        decay = math.exp(-t * 24.0)
        buf[idx] += math.sin(2 * math.pi * f * t) * amp * decay


def _add_hat(buf: list[float], start: int, rng: random.Random, amp: float = 0.12) -> None:
    n = int(SR * 0.04)
    for i in range(n):
        idx = start + i
        if idx >= len(buf):
            break
        decay = math.exp(-i / n * 6.0)
        buf[idx] += (rng.random() * 2 - 1) * amp * decay


def synth(duration: float, mood: str = "upbeat", bpm: int | None = None, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    _bpm, prog, kind, arp_gain = MOODS.get(mood, MOODS["upbeat"])
    bpm = bpm or _bpm
    beat = 60.0 / bpm
    total = int(SR * duration)
    buf = [0.0] * total

    bar = 0
    t = 0.0
    while t < duration:
        bass_note, arp = prog[bar % len(prog)]
        bar_start = int(t * SR)
        # Bass: root on each of 2 beats of the bar.
        for b in range(2):
            s = bar_start + int(b * beat * SR)
            _add_note(buf, s, note(bass_note), beat * 0.95, kind, 0.32)
        # Arp: 4 eighth notes across the bar.
        eighth = beat / 2.0
        for j, an in enumerate(arp):
            s = bar_start + int(j * eighth * SR)
            _add_note(buf, s, note(an), eighth * 0.9, kind, arp_gain)
        # Drums: kick on both beats, hats on the off-eighths.
        for b in range(2):
            _add_kick(buf, bar_start + int(b * beat * SR))
        for j in range(4):
            if j % 2 == 1:
                _add_hat(buf, bar_start + int(j * eighth * SR), rng)
        t += beat * 2.0
        bar += 1

    # Normalize to a comfortable peak (leave headroom).
    peak = max((abs(x) for x in buf), default=1.0) or 1.0
    scale = 0.72 / peak
    return [x * scale for x in buf]


def write_wav(path: str, samples: list[float]) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        for x in samples:
            v = int(max(-1.0, min(1.0, x)) * 32767)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def main() -> int:
    ap = argparse.ArgumentParser(prog="soundtrack", description="Generate a royalty-free chiptune bed (pure stdlib).")
    ap.add_argument("--duration", type=float, required=True, help="Length in seconds")
    ap.add_argument("--mood", choices=list(MOODS), default="upbeat")
    ap.add_argument("--bpm", type=int, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-o", "--out", default="soundtrack.wav")
    args = ap.parse_args()
    write_wav(args.out, synth(args.duration, args.mood, args.bpm, args.seed))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
