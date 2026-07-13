"""Pluggable TTS: backend dispatch, defaults, suffix handling — no network."""
from __future__ import annotations

import sys
from pathlib import Path

SHORTS_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "shorts" / "scripts"
sys.path.insert(0, str(SHORTS_SCRIPTS))

import voiceover as vo  # noqa: E402


def test_default_backend_is_free_edge(monkeypatch):
    seen = {}

    def fake_edge(text, out, voice):
        seen["backend"] = "edge"
        return out
    monkeypatch.setattr(vo, "_edge_tts", fake_edge)
    monkeypatch.setattr(vo, "get", lambda k, d=None: d)  # SHORTS_TTS unset -> default
    vo.synthesize("hi", "out.mp3")
    assert seen["backend"] == "edge"


def test_backend_dispatch_routes_each(monkeypatch):
    calls = []
    monkeypatch.setattr(vo, "_edge_tts", lambda t, o, v: calls.append("edge") or o)
    monkeypatch.setattr(vo, "_piper_tts", lambda t, o, v: calls.append("piper") or o)
    monkeypatch.setattr(vo, "_gtts_tts", lambda t, o, v: calls.append("gtts") or o)
    monkeypatch.setattr(vo, "_openai_tts", lambda t, o, v, m: calls.append("openai") or o)
    monkeypatch.setattr(vo, "_elevenlabs_tts", lambda t, o, v, m: calls.append("elevenlabs") or o)
    for b in ("edge", "piper", "gtts", "openai", "elevenlabs"):
        vo.synthesize("hi", "out.mp3", backend=b)
    assert calls == ["edge", "piper", "gtts", "openai", "elevenlabs"]


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setattr(vo, "get", lambda k, d=None: d)
    try:
        vo.synthesize("hi", "out.mp3", backend="robotvoice")
    except SystemExit as exc:
        assert "unknown TTS backend" in str(exc)
    else:
        raise AssertionError("expected SystemExit for unknown backend")


def test_config_backend_is_used_when_arg_omitted(monkeypatch):
    seen = {}
    monkeypatch.setattr(vo, "_gtts_tts", lambda t, o, v: seen.setdefault("b", "gtts") or o)
    monkeypatch.setattr(vo, "get", lambda k, d=None: "gtts" if k == "SHORTS_TTS" else d)
    vo.synthesize("hi", "out.mp3")
    assert seen["b"] == "gtts"


def test_piper_forces_wav_suffix():
    assert vo._swap_suffix("a/b/vo.mp3", ".wav") == str(Path("a/b/vo.wav"))


def test_free_backends_need_no_key(monkeypatch):
    # edge/piper/gtts must never require an API key to be *selected* (they fail
    # later on tool/network, not on a missing key). Guard the classification.
    assert set(vo.FREE_BACKENDS) == {"edge", "piper", "gtts"}
    assert "openai" not in vo.FREE_BACKENDS and "elevenlabs" not in vo.FREE_BACKENDS
