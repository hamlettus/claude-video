"""Storyboard validation, config precedence, trending dedup, publish dry-run."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SHORTS_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "shorts" / "scripts"
sys.path.insert(0, str(SHORTS_SCRIPTS))

import animate  # noqa: E402
import shorts_config as config  # noqa: E402
import publish  # noqa: E402
import trending  # noqa: E402


def test_validate_accepts_good_storyboard():
    sb = {"scenes": [{
        "duration": 2.0,
        "actors": [{"keyframes": [
            {"t": 0, "x": 0.5, "y": 0.6, "pose": "idle"},
            {"t": 2, "x": 0.5, "y": 0.6, "pose": "wave"},
        ]}],
    }]}
    assert animate.validate(sb) == []


def test_validate_flags_unknown_pose_bad_coord_and_duration():
    sb = {"scenes": [{
        "duration": 0,
        "actors": [{"keyframes": [{"t": 0, "x": 2.0, "y": 0.6, "pose": "floss"}]}],
    }]}
    problems = animate.validate(sb)
    assert any("duration" in p for p in problems)
    assert any("unknown pose" in p for p in problems)
    assert any("out of" in p for p in problems)


def test_validate_allows_offscreen_staging():
    # x=1.05 (enter from the right) / x=-0.2 (exit left) are legal.
    sb = {"scenes": [{
        "duration": 2.0,
        "actors": [{"keyframes": [
            {"t": 0, "x": 1.05, "y": 0.6, "pose": "walk"},
            {"t": 2, "x": -0.2, "y": 0.6, "pose": "walk"},
        ]}],
    }]}
    assert animate.validate(sb) == []


def test_validate_empty_scenes():
    assert animate.validate({"scenes": []}) == ["storyboard has no 'scenes'"]


def test_apply_defaults_fills_meta():
    sb = {"scenes": [{"duration": 1.0}]}
    animate._apply_defaults(sb)
    for key in ("width", "height", "fps", "bg", "fg", "accent"):
        assert key in sb["meta"]


def test_config_precedence_env_over_file(monkeypatch, tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("SHORTS_FPS=24\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", envfile)
    # File value wins over the built-in default...
    assert config.get("SHORTS_FPS") == "24"
    # ...and the process env wins over the file.
    monkeypatch.setenv("SHORTS_FPS", "60")
    assert config.get("SHORTS_FPS") == "60"


def test_config_inline_comment_stripped(monkeypatch, tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("SHORTS_BG=#101010  # dark\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", envfile)
    monkeypatch.delenv("SHORTS_BG", raising=False)
    assert config.get("SHORTS_BG") == "#101010"


def test_trending_dedup_filters_processed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "get", lambda k, d=None: str(tmp_path) if k == "SHORTS_STATE_DIR" else config.DEFAULTS.get(k, d))
    monkeypatch.setattr(trending, "state_dir", lambda: tmp_path)
    trending.mark_processed("seen1")

    entries = [
        {"id": "seen1", "title": "old", "duration": 600},
        {"id": "fresh", "title": "new", "duration": 600},
        {"id": "tooshort", "title": "clip", "duration": 30},
    ]

    class FakeProc:
        returncode = 0
        stdout = json.dumps({"entries": entries})
        stderr = ""

    monkeypatch.setattr(trending.shutil, "which", lambda _n: "/usr/bin/yt-dlp")
    monkeypatch.setattr(trending.subprocess, "run", lambda *a, **k: FakeProc())

    out = trending.discover("https://example/trending", limit=10, min_seconds=180)
    ids = [c["id"] for c in out]
    assert ids == ["fresh"]  # seen1 deduped, tooshort filtered


def test_publish_dry_run_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "get", lambda k, d=None: None)  # no creds anywhere
    meta = {"title": "Hook", "description": "d", "hashtags": ["shorts"]}
    video = tmp_path / "s.mp4"
    video.write_bytes(b"\x00")

    yt = publish.publish_youtube(str(video), meta, live=False)
    assert yt["status"] == "skipped" and "YT_ACCESS_TOKEN" in yt["reason"]

    ig = publish.publish_instagram(str(video), meta, live=False, video_url=None)
    assert ig["status"] == "skipped"


def test_publish_youtube_dry_run_with_token(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "get", lambda k, d=None: "tok" if k == "YT_ACCESS_TOKEN" else None)
    meta = {"title": "Hook", "tags": ["a"]}
    video = tmp_path / "s.mp4"
    video.write_bytes(b"\x00")
    res = publish.publish_youtube(str(video), meta, live=False)
    assert res["status"] == "dry-run"
    assert res["would_upload"] == str(video)


def test_compose_caption_builds_hashtags():
    meta = {"title": "T", "description": "D", "hashtags": ["shorts", "#reels"]}
    cap = publish._compose_caption(meta)
    assert "#shorts" in cap and "#reels" in cap and "T" in cap and "D" in cap
