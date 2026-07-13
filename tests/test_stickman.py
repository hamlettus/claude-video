"""Pure-Python animation engine: canvas, font, rig, storyboard, PNG export.

None of these need ffmpeg — they exercise the frame generator directly.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SHORTS_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "shorts" / "scripts"
sys.path.insert(0, str(SHORTS_SCRIPTS))

import stickman as sm  # noqa: E402


def test_hex_rgb_forms():
    assert sm.hex_rgb("#ffca28") == (255, 202, 40)
    assert sm.hex_rgb("#fff") == (255, 255, 255)
    assert sm.hex_rgb((1, 2, 3)) == (1, 2, 3)


def test_canvas_fill_and_pixel():
    c = sm.Canvas(4, 3, (10, 20, 30))
    assert c.buf[:3] == bytes((10, 20, 30))
    assert len(c.buf) == 4 * 3 * 3
    c.fill_rect(1, 1, 2, 2, (255, 0, 0))
    i = (1 * 4 + 1) * 3
    assert c.buf[i : i + 3] == bytes((255, 0, 0))


def test_fill_rect_clips_to_bounds():
    c = sm.Canvas(5, 5, (0, 0, 0))
    # Fully out of bounds — must not raise or write.
    c.fill_rect(-10, -10, -5, -5, (255, 255, 255))
    assert all(b == 0 for b in c.buf)


def test_disk_draws_center():
    c = sm.Canvas(21, 21, (0, 0, 0))
    c.disk(10, 10, 5, (0, 255, 0))
    i = (10 * 21 + 10) * 3
    assert c.buf[i : i + 3] == bytes((0, 255, 0))
    # A corner outside the radius stays background.
    corner = (0 * 21 + 0) * 3
    assert c.buf[corner : corner + 3] == bytes((0, 0, 0))


def test_text_width_and_draw_marks_pixels():
    c = sm.Canvas(200, 40, (0, 0, 0))
    w = sm.text_width("HI", scale=2)
    assert w == (5 + 1) * 2 * 2 - 1 * 2
    sm.draw_text(c, "HI", 4, 4, 2, (255, 255, 255))
    lit = sum(1 for k in range(0, len(c.buf), 3) if c.buf[k] == 255)
    assert lit > 0


def test_lowercase_maps_to_uppercase_glyph():
    a = sm.Canvas(60, 20, (0, 0, 0))
    b = sm.Canvas(60, 20, (0, 0, 0))
    sm.draw_text(a, "abc", 0, 0, 1, (255, 255, 255))
    sm.draw_text(b, "ABC", 0, 0, 1, (255, 255, 255))
    assert a.buf == b.buf


def test_all_poses_evaluate_to_full_skeletons():
    for name, fn in sm.POSES.items():
        joints = fn(0.3, 2.0)
        for required in sm._IDLE:
            assert required in joints, f"{name} missing joint {required}"
            x, y = joints[required]
            assert isinstance(x, float) and isinstance(y, float)


def test_eval_actor_interpolates_position_and_clamps_ends():
    actor = {
        "keyframes": [
            {"t": 0.0, "x": 0.2, "y": 0.6, "pose": "idle"},
            {"t": 1.0, "x": 0.8, "y": 0.6, "pose": "idle"},
        ]
    }
    _, x0, _ = sm.eval_actor(actor, 0.0)
    _, xmid, _ = sm.eval_actor(actor, 0.5)
    _, x1, _ = sm.eval_actor(actor, 1.0)
    assert abs(x0 - 0.2) < 1e-6
    assert abs(x1 - 0.8) < 1e-6
    assert 0.2 < xmid < 0.8  # smoothstep keeps it strictly between
    # Past the last keyframe it clamps, not extrapolates.
    _, xafter, _ = sm.eval_actor(actor, 5.0)
    assert abs(xafter - 0.8) < 1e-6


def test_unsorted_keyframes_are_handled():
    actor = {
        "keyframes": [
            {"t": 1.0, "x": 0.8, "y": 0.6, "pose": "idle"},
            {"t": 0.0, "x": 0.2, "y": 0.6, "pose": "idle"},
        ]
    }
    _, x0, _ = sm.eval_actor(actor, 0.0)
    assert abs(x0 - 0.2) < 1e-6


def test_frame_and_duration_counts():
    sb = {
        "meta": {"fps": 10},
        "scenes": [{"duration": 1.0}, {"duration": 2.0}],
    }
    assert sm.total_duration(sb) == 3.0
    assert sm.total_frames(sb) == 30


def test_iter_frames_yields_expected_size_and_indices():
    sb = {
        "meta": {"width": 32, "height": 48, "fps": 5},
        "scenes": [{
            "duration": 1.0,
            "caption": "GO",
            "actors": [{"id": "a", "scale": 0.3,
                        "keyframes": [{"t": 0, "x": 0.5, "y": 0.6, "pose": "walk"}]}],
        }],
    }
    frames = list(sm.iter_frames(sb))
    assert len(frames) == 5
    for idx, (canvas, gi) in enumerate(frames):
        assert gi == idx
        assert canvas.w == 32 and canvas.h == 48
        assert len(canvas.buf) == 32 * 48 * 3


def test_actor_pixels_actually_drawn():
    sb = {
        "meta": {"width": 200, "height": 360, "fps": 1, "bg": "#000000"},
        "scenes": [{
            "duration": 1.0,
            "actors": [{"id": "a", "color": "#ffffff", "scale": 0.4,
                        "keyframes": [{"t": 0, "x": 0.5, "y": 0.6, "pose": "idle"}]}],
        }],
    }
    canvas, _ = next(sm.iter_frames(sb))
    white = sum(1 for k in range(0, len(canvas.buf), 3)
                if canvas.buf[k] == 255 and canvas.buf[k + 1] == 255 and canvas.buf[k + 2] == 255)
    assert white > 100  # a whole figure's worth of strokes


def test_write_png_is_valid(tmp_path: Path):
    c = sm.Canvas(8, 8, (12, 34, 56))
    out = tmp_path / "x.png"
    sm.write_png(str(out), c)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR dimensions.
    w, h = struct.unpack(">II", data[16:24])
    assert (w, h) == (8, 8)
    # IDAT decompresses to h*(1 + w*3) bytes (filter byte per row).
    idat_start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[idat_start - 8 : idat_start - 4])[0]
    raw = zlib.decompress(data[idat_start : idat_start + length])
    assert len(raw) == 8 * (1 + 8 * 3)
