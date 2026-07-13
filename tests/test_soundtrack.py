"""Procedural soundtrack: note math, synthesis, WAV output, non-silence."""
from __future__ import annotations

import sys
import wave
from pathlib import Path

SHORTS_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "shorts" / "scripts"
sys.path.insert(0, str(SHORTS_SCRIPTS))

import soundtrack as st  # noqa: E402


def test_note_frequencies():
    assert abs(st.note("A4") - 440.0) < 1e-6
    assert abs(st.note("A3") - 220.0) < 1e-6      # octave down halves
    assert abs(st.note("A5") - 880.0) < 1e-6
    assert abs(st.note("C4") - 261.6256) < 1e-3
    # Accidentals: A#4 is one semitone above A4.
    assert st.note("A#4") > st.note("A4")
    assert abs(st.note("Bb4") - st.note("A#4")) < 1e-6


def test_synth_length_matches_duration():
    samples = st.synth(2.0, mood="upbeat")
    # ~2s at 44.1kHz, within one bar's rounding.
    assert abs(len(samples) - int(st.SR * 2.0)) < st.SR


def test_synth_is_not_silent_and_bounded():
    samples = st.synth(2.0, mood="upbeat")
    peak = max(abs(x) for x in samples)
    assert peak > 0.3            # actually audible
    assert peak <= 1.0           # normalized, no clipping past full scale


def test_all_moods_render():
    for mood in st.MOODS:
        s = st.synth(1.5, mood=mood)
        assert len(s) > 0
        assert max(abs(x) for x in s) > 0.1


def test_write_wav_is_valid_16bit_mono(tmp_path: Path):
    out = tmp_path / "bed.wav"
    st.write_wav(str(out), st.synth(1.0, mood="chill"))
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == st.SR
        assert w.getnframes() > 0


def test_seed_is_deterministic():
    a = st.synth(1.0, mood="upbeat", seed=42)
    b = st.synth(1.0, mood="upbeat", seed=42)
    assert a == b
