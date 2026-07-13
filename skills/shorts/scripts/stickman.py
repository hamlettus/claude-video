#!/usr/bin/env python3
"""Pure-stdlib stick-figure animation engine.

No third-party libraries. Renders a JSON *storyboard* into a stream of raw
`rgb24` frames (bytes), which animate.py pipes straight into ffmpeg. Also
exports single frames as PNG (a tiny zlib-based encoder) so the engine can be
inspected and unit-tested without ffmpeg installed.

Pipeline role: `/watch` tells the model what a trending video is about; the
model authors a storyboard; this module draws it. The whole visual style is
stick figures + bold captions, which is exactly what pure vector rasterizing
does well and cheaply.

Storyboard schema (see SKILL.md for the authoring contract)::

    {
      "meta":   {"width":1080,"height":1920,"fps":30,"bg":"#0e1116",
                 "fg":"#f5f5f5","accent":"#ffca28"},
      "scenes": [
        {
          "duration": 2.5,
          "bg": "#101826",                       # optional per-scene override
          "caption": "POV: 3AM fridge raid",      # optional bottom caption
          "title":   "THE PLAN",                  # optional big centered title
          "props":   [{"type":"rect","x":0.1,"y":0.8,"w":0.8,"h":0.02}],
          "actors":  [
            {"id":"a","color":"#ffca28","scale":0.34,"cadence":2.0,
             "keyframes":[
               {"t":0.0,"x":0.30,"y":0.60,"pose":"idle"},
               {"t":1.0,"x":0.50,"y":0.60,"pose":"walk"},
               {"t":2.0,"x":0.50,"y":0.60,"pose":"point"}
             ]}
          ]
        }
      ]
    }

Coordinates are canvas fractions (0..1). Actor `scale` is the figure height as
a fraction of canvas height. Poses are limb configurations in figure-local
units (hip at origin, y points down); the renderer blends between the poses on
adjacent keyframes and interpolates the (x,y) travel.
"""
from __future__ import annotations

import math
import struct
import zlib
from typing import Callable

# --------------------------------------------------------------------------- #
# Colors
# --------------------------------------------------------------------------- #


def hex_rgb(value: str | tuple[int, int, int]) -> tuple[int, int, int]:
    """'#rrggbb' / '#rgb' / (r,g,b) -> (r,g,b)."""
    if isinstance(value, (tuple, list)):
        r, g, b = value
        return (int(r) & 255, int(g) & 255, int(b) & 255)
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad color: {value!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


# --------------------------------------------------------------------------- #
# Framebuffer canvas
# --------------------------------------------------------------------------- #


class Canvas:
    """RGB24 framebuffer with the handful of primitives stick figures need."""

    def __init__(self, width: int, height: int, bg: tuple[int, int, int]) -> None:
        self.w = int(width)
        self.h = int(height)
        self.buf = bytearray(self.w * self.h * 3)
        self.fill(bg)

    def fill(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        self.buf[:] = bytes((r, g, b)) * (self.w * self.h)

    def _px(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = color[0]
            self.buf[i + 1] = color[1]
            self.buf[i + 2] = color[2]

    def fill_rect(self, x0: float, y0: float, x1: float, y1: float, color: tuple[int, int, int]) -> None:
        xa, xb = sorted((int(x0), int(x1)))
        ya, yb = sorted((int(y0), int(y1)))
        xa = max(0, xa)
        ya = max(0, ya)
        xb = min(self.w - 1, xb)
        yb = min(self.h - 1, yb)
        if xa > xb or ya > yb:
            return
        row = bytes(color) * (xb - xa + 1)
        for y in range(ya, yb + 1):
            i = (y * self.w + xa) * 3
            self.buf[i : i + len(row)] = row

    def disk(self, cx: float, cy: float, r: float, color: tuple[int, int, int]) -> None:
        r = max(0.5, r)
        cx_i, cy_i = int(round(cx)), int(round(cy))
        ri = int(math.ceil(r))
        r2 = r * r
        for dy in range(-ri, ri + 1):
            span2 = r2 - dy * dy
            if span2 < 0:
                continue
            dx = int(math.sqrt(span2))
            self.fill_rect(cx_i - dx, cy_i + dy, cx_i + dx, cy_i + dy, color)

    def ring(self, cx: float, cy: float, r: float, thickness: float, color: tuple[int, int, int]) -> None:
        self.disk(cx, cy, r, color)

    def hollow_ring(
        self,
        cx: float,
        cy: float,
        r: float,
        thickness: float,
        color: tuple[int, int, int],
        inner: tuple[int, int, int],
    ) -> None:
        self.disk(cx, cy, r, color)
        self.disk(cx, cy, max(0.5, r - thickness), inner)

    def thick_line(
        self, x0: float, y0: float, x1: float, y1: float, thickness: float, color: tuple[int, int, int]
    ) -> None:
        """Rounded thick segment: stamp disks along p0->p1."""
        r = max(0.5, thickness / 2.0)
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        steps = max(1, int(length))
        for s in range(steps + 1):
            t = s / steps
            self.disk(x0 + dx * t, y0 + dy * t, r, color)


# --------------------------------------------------------------------------- #
# PNG export (single frame; used for tests / thumbnails)
# --------------------------------------------------------------------------- #


def write_png(path: str, canvas: Canvas) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    w, h = canvas.w, canvas.h
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filter type 0 (none)
        start = y * stride
        raw += canvas.buf[start : start + stride]
    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(out)


# --------------------------------------------------------------------------- #
# Bitmap font (5x7) — uppercase, digits, common punctuation. Lowercase maps up.
# --------------------------------------------------------------------------- #

_FONT: dict[str, list[str]] = {
    " ": ["     "] * 7,
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "11110", "10001", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "11110", "10000", "10000", "10000", "11111"],
    "F": ["11111", "10000", "11110", "10000", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    '"': ["01010", "01010", "01010", "00000", "00000", "00000", "00000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "&": ["01100", "10010", "10100", "01000", "10101", "10010", "01101"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "$": ["00100", "01111", "10100", "01110", "00101", "11110", "00100"],
    "#": ["01010", "11111", "01010", "01010", "01010", "11111", "01010"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
}

FONT_W, FONT_H = 5, 7


def _glyph(ch: str) -> list[str]:
    up = ch.upper()
    return _FONT.get(up, _FONT.get(ch, _FONT["?"]))


def text_width(text: str, scale: int, spacing: int = 1) -> int:
    if not text:
        return 0
    per = (FONT_W + spacing) * scale
    return per * len(text) - spacing * scale


def draw_text(
    canvas: Canvas,
    text: str,
    x: int,
    y: int,
    scale: int,
    color: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    spacing: int = 1,
) -> None:
    """Draw `text` with top-left at (x,y). Each font pixel is a scale×scale block.

    When `outline` is given, an 8-neighbour halo is painted first for contrast
    over busy backgrounds — the reason captions stay legible on any scene.
    """
    cursor = x
    for ch in text:
        glyph = _glyph(ch)
        for ry, row in enumerate(glyph):
            for rx, bit in enumerate(row):
                if bit != "1":
                    continue
                px = cursor + rx * scale
                py = y + ry * scale
                if outline is not None:
                    for ox in (-1, 0, 1):
                        for oy in (-1, 0, 1):
                            if ox or oy:
                                canvas.fill_rect(
                                    px + ox, py + oy,
                                    px + ox + scale - 1, py + oy + scale - 1,
                                    outline,
                                )
        # second pass so the fill sits on top of every glyph's outline
        for ry, row in enumerate(glyph):
            for rx, bit in enumerate(row):
                if bit == "1":
                    px = cursor + rx * scale
                    py = y + ry * scale
                    canvas.fill_rect(px, py, px + scale - 1, py + scale - 1, color)
        cursor += (FONT_W + spacing) * scale


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        cand = word if not cur else cur + " " + word
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_caption_block(
    canvas: Canvas,
    text: str,
    center_y: int,
    scale: int,
    color: tuple[int, int, int],
    outline: tuple[int, int, int],
) -> None:
    """Auto-wrapped, centered caption block anchored around center_y."""
    if not text:
        return
    max_chars = max(6, int((canvas.w * 0.9) / ((FONT_W + 1) * scale)))
    lines = _wrap(text, max_chars)
    line_h = (FONT_H + 3) * scale
    total = line_h * len(lines)
    y = center_y - total // 2
    for line in lines:
        w = text_width(line, scale)
        x = (canvas.w - w) // 2
        draw_text(canvas, line, x, y, scale, color, outline=outline)
        y += line_h


# --------------------------------------------------------------------------- #
# Stick-figure rig
# --------------------------------------------------------------------------- #

# Joint positions in figure-local units. Hip at origin (0,0); y grows downward.
# A standing figure spans roughly y=-0.52 (head top) to y=+0.42 (feet) ~= 1 unit.
HEAD_R = 0.10

_IDLE: dict[str, tuple[float, float]] = {
    "hip": (0.0, 0.0),
    "neck": (0.0, -0.30),
    "head": (0.0, -0.42),
    "elbow_l": (-0.10, -0.15),
    "hand_l": (-0.13, 0.00),
    "elbow_r": (0.10, -0.15),
    "hand_r": (0.13, 0.00),
    "knee_l": (-0.06, 0.20),
    "foot_l": (-0.08, 0.42),
    "knee_r": (0.06, 0.20),
    "foot_r": (0.08, 0.42),
}


def _static(overrides: dict[str, tuple[float, float]]) -> Callable[[float, float], dict]:
    base = dict(_IDLE)
    base.update(overrides)

    def pose(_t: float, _cad: float) -> dict:
        return dict(base)

    return pose


def _pose_idle(t: float, cad: float) -> dict:
    j = dict(_IDLE)
    bob = math.sin(t * 2.0) * 0.008  # gentle breathing
    j["neck"] = (0.0, -0.30 + bob)
    j["head"] = (0.0, -0.42 + bob)
    return j


def _pose_walk(t: float, cad: float) -> dict:
    ph = math.sin(2 * math.pi * cad * t)
    j = dict(_IDLE)
    j["foot_l"] = (0.10 * ph, 0.42)
    j["knee_l"] = (0.05 * ph, 0.21)
    j["foot_r"] = (-0.10 * ph, 0.42)
    j["knee_r"] = (-0.05 * ph, 0.21)
    j["hand_l"] = (-0.13, 0.00 - 0.06 * ph)
    j["elbow_l"] = (-0.10, -0.15 - 0.03 * ph)
    j["hand_r"] = (0.13, 0.00 + 0.06 * ph)
    j["elbow_r"] = (0.10, -0.15 + 0.03 * ph)
    bob = abs(ph) * 0.015
    j["hip"] = (0.0, -bob)
    return j


def _pose_run(t: float, cad: float) -> dict:
    ph = math.sin(2 * math.pi * max(cad, 3.0) * t)
    j = dict(_IDLE)
    lean = 0.06
    j["neck"] = (lean, -0.29)
    j["head"] = (lean + 0.01, -0.41)
    j["foot_l"] = (0.16 * ph + lean, 0.40)
    j["knee_l"] = (0.09 * ph + lean, 0.20)
    j["foot_r"] = (-0.16 * ph + lean, 0.40)
    j["knee_r"] = (-0.09 * ph + lean, 0.20)
    j["hand_l"] = (-0.08, -0.18 + 0.10 * ph)
    j["elbow_l"] = (-0.09, -0.20 + 0.05 * ph)
    j["hand_r"] = (0.14, -0.20 - 0.10 * ph)
    j["elbow_r"] = (0.11, -0.19 - 0.05 * ph)
    j["hip"] = (0.0, -abs(ph) * 0.02)
    return j


def _pose_wave(t: float, cad: float) -> dict:
    j = dict(_IDLE)
    sway = math.sin(t * 8.0) * 0.05
    j["elbow_r"] = (0.13, -0.38)
    j["hand_r"] = (0.16 + sway, -0.55)
    return j


def _pose_talk(t: float, cad: float) -> dict:
    j = dict(_IDLE)
    g = math.sin(t * 6.0) * 0.03
    j["elbow_r"] = (0.13, -0.16)
    j["hand_r"] = (0.20, -0.10 + g)
    j["elbow_l"] = (-0.13, -0.16)
    j["hand_l"] = (-0.20, -0.06 - g)
    return j


def _pose_jump(t: float, cad: float) -> dict:
    j = dict(_IDLE)
    j["hand_l"] = (-0.16, -0.52)
    j["elbow_l"] = (-0.13, -0.34)
    j["hand_r"] = (0.16, -0.52)
    j["elbow_r"] = (0.13, -0.34)
    j["knee_l"] = (-0.09, 0.14)
    j["foot_l"] = (-0.12, 0.30)
    j["knee_r"] = (0.09, 0.14)
    j["foot_r"] = (0.12, 0.30)
    return j


def _pose_celebrate(t: float, cad: float) -> dict:
    j = _pose_jump(t, cad)
    pump = math.sin(t * 9.0) * 0.03
    j["hand_l"] = (-0.16, -0.52 + pump)
    j["hand_r"] = (0.16, -0.52 - pump)
    return j


def _pose_think(t: float, cad: float) -> dict:
    j = dict(_IDLE)
    j["elbow_r"] = (0.15, -0.18)
    j["hand_r"] = (0.05, -0.38)
    tap = math.sin(t * 3.0) * 0.01
    j["hand_r"] = (0.05 + tap, -0.38)
    return j


def _pose_shrug(t: float, cad: float) -> dict:
    return _static({
        "elbow_l": (-0.16, -0.24),
        "hand_l": (-0.22, -0.30),
        "elbow_r": (0.16, -0.24),
        "hand_r": (0.22, -0.30),
        "neck": (0.0, -0.27),
        "head": (0.0, -0.39),
    })(t, cad)


def _pose_point(t: float, cad: float) -> dict:
    return _static({
        "elbow_r": (0.15, -0.26),
        "hand_r": (0.32, -0.30),
    })(t, cad)


def _pose_fall(t: float, cad: float) -> dict:
    # figure tipped: whole rig rotated by drawing offsets (cheap 'lying' look)
    return _static({
        "neck": (0.22, -0.05),
        "head": (0.33, -0.05),
        "elbow_l": (0.10, 0.10),
        "hand_l": (0.05, 0.20),
        "elbow_r": (0.12, -0.18),
        "hand_r": (0.20, -0.22),
        "knee_l": (-0.18, 0.10),
        "foot_l": (-0.34, 0.10),
        "knee_r": (-0.18, 0.18),
        "foot_r": (-0.34, 0.20),
    })(t, cad)


def _pose_sit(t: float, cad: float) -> dict:
    return _static({
        "hip": (0.0, 0.12),
        "neck": (0.0, -0.18),
        "head": (0.0, -0.30),
        "knee_l": (-0.14, 0.14),
        "foot_l": (-0.14, 0.34),
        "knee_r": (0.14, 0.14),
        "foot_r": (0.14, 0.34),
        "hand_l": (-0.13, 0.12),
        "hand_r": (0.13, 0.12),
    })(t, cad)


POSES: dict[str, Callable[[float, float], dict]] = {
    "idle": _pose_idle,
    "walk": _pose_walk,
    "run": _pose_run,
    "wave": _pose_wave,
    "talk": _pose_talk,
    "jump": _pose_jump,
    "celebrate": _pose_celebrate,
    "think": _pose_think,
    "shrug": _pose_shrug,
    "point": _pose_point,
    "fall": _pose_fall,
    "sit": _pose_sit,
}


def _ease(t: float) -> float:
    """Smoothstep for pleasant keyframe transitions."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def _blend_joints(a: dict, b: dict, t: float) -> dict:
    out = {}
    for name in _IDLE:
        ax, ay = a.get(name, _IDLE[name])
        bx, by = b.get(name, _IDLE[name])
        out[name] = (ax + (bx - ax) * t, ay + (by - ay) * t)
    return out


def eval_actor(actor: dict, scene_t: float) -> tuple[dict, float, float]:
    """Return (local joints, x-fraction, y-fraction) for an actor at scene_t."""
    kfs = actor.get("keyframes") or [{"t": 0.0, "x": 0.5, "y": 0.6, "pose": "idle"}]
    kfs = sorted(kfs, key=lambda k: k.get("t", 0.0))
    cadence = float(actor.get("cadence", 2.0))

    if scene_t <= kfs[0].get("t", 0.0):
        lo = hi = kfs[0]
        w = 0.0
    elif scene_t >= kfs[-1].get("t", 0.0):
        lo = hi = kfs[-1]
        w = 1.0
    else:
        lo = kfs[0]
        hi = kfs[-1]
        for i in range(len(kfs) - 1):
            if kfs[i].get("t", 0.0) <= scene_t <= kfs[i + 1].get("t", 0.0):
                lo, hi = kfs[i], kfs[i + 1]
                break
        span = max(1e-6, hi.get("t", 0.0) - lo.get("t", 0.0))
        w = _ease((scene_t - lo.get("t", 0.0)) / span)

    pose_lo = POSES.get(lo.get("pose", "idle"), _pose_idle)
    pose_hi = POSES.get(hi.get("pose", "idle"), _pose_idle)
    joints = _blend_joints(pose_lo(scene_t, cadence), pose_hi(scene_t, cadence), w)

    x = lo.get("x", 0.5) + (hi.get("x", 0.5) - lo.get("x", 0.5)) * w
    y = lo.get("y", 0.6) + (hi.get("y", 0.6) - lo.get("y", 0.6)) * w
    return joints, x, y


def draw_actor(canvas: Canvas, actor: dict, joints: dict, xf: float, yf: float) -> None:
    color = hex_rgb(actor.get("color", "#f5f5f5"))
    scale = float(actor.get("scale", 0.34))
    ppu = scale * canvas.h  # pixels per figure unit
    ox = xf * canvas.w
    oy = yf * canvas.h

    def wp(name: str) -> tuple[float, float]:
        jx, jy = joints[name]
        return ox + jx * ppu, oy + jy * ppu

    limb = max(3.0, ppu * 0.028)

    hip = wp("hip")
    neck = wp("neck")
    # legs
    canvas.thick_line(*hip, *wp("knee_l"), limb, color)
    canvas.thick_line(*wp("knee_l"), *wp("foot_l"), limb, color)
    canvas.thick_line(*hip, *wp("knee_r"), limb, color)
    canvas.thick_line(*wp("knee_r"), *wp("foot_r"), limb, color)
    # spine
    canvas.thick_line(*hip, *neck, limb, color)
    # arms
    canvas.thick_line(*neck, *wp("elbow_l"), limb, color)
    canvas.thick_line(*wp("elbow_l"), *wp("hand_l"), limb, color)
    canvas.thick_line(*neck, *wp("elbow_r"), limb, color)
    canvas.thick_line(*wp("elbow_r"), *wp("hand_r"), limb, color)
    # head (open circle)
    hx, hy = wp("head")
    head_r = HEAD_R * ppu
    bg = getattr(canvas, "_bg", (14, 17, 22))
    canvas.hollow_ring(hx, hy, head_r, max(3.0, limb * 0.9), color, bg)


# --------------------------------------------------------------------------- #
# Props
# --------------------------------------------------------------------------- #


def draw_prop(canvas: Canvas, prop: dict, accent: tuple[int, int, int]) -> None:
    kind = prop.get("type", "rect")
    color = hex_rgb(prop["color"]) if "color" in prop else accent
    if kind == "rect":
        x = prop.get("x", 0.0) * canvas.w
        y = prop.get("y", 0.0) * canvas.h
        w = prop.get("w", 0.1) * canvas.w
        h = prop.get("h", 0.1) * canvas.h
        canvas.fill_rect(x, y, x + w, y + h, color)
    elif kind == "line":
        canvas.thick_line(
            prop.get("x0", 0) * canvas.w, prop.get("y0", 0) * canvas.h,
            prop.get("x1", 1) * canvas.w, prop.get("y1", 0) * canvas.h,
            prop.get("thickness", 6), color,
        )
    elif kind == "disk":
        canvas.disk(
            prop.get("x", 0.5) * canvas.w, prop.get("y", 0.5) * canvas.h,
            prop.get("r", 0.05) * canvas.h, color,
        )
    elif kind == "ground":
        y = prop.get("y", 0.9) * canvas.h
        canvas.fill_rect(0, y, canvas.w, y + max(4, canvas.h * 0.006), color)


# --------------------------------------------------------------------------- #
# Storyboard rendering
# --------------------------------------------------------------------------- #


def _scene_frame_count(scene: dict, fps: int) -> int:
    return max(1, int(round(float(scene.get("duration", 2.0)) * fps)))


def render_scene_frame(meta: dict, scene: dict, frame_index: int, fps: int) -> Canvas:
    w = int(meta.get("width", 1080))
    h = int(meta.get("height", 1920))
    bg = hex_rgb(scene.get("bg", meta.get("bg", "#0e1116")))
    fg = hex_rgb(meta.get("fg", "#f5f5f5"))
    accent = hex_rgb(meta.get("accent", "#ffca28"))
    outline = hex_rgb(meta.get("outline", "#0a0d12"))

    canvas = Canvas(w, h, bg)
    canvas._bg = bg  # noqa: SLF001 — head hole needs the true background color
    t = frame_index / fps

    for prop in scene.get("props", []) or []:
        draw_prop(canvas, prop, accent)

    for actor in scene.get("actors", []) or []:
        joints, xf, yf = eval_actor(actor, t)
        draw_actor(canvas, actor, joints, xf, yf)

    title = scene.get("title")
    if title:
        tscale = max(6, int(w / 130))
        draw_caption_block(canvas, title, int(h * 0.28), tscale, accent, outline)

    caption = scene.get("caption")
    if caption:
        cscale = max(5, int(w / 165))
        draw_caption_block(canvas, caption, int(h * 0.82), cscale, fg, outline)

    return canvas


def iter_frames(storyboard: dict):
    """Yield (canvas, global_frame_index) for the whole storyboard."""
    meta = storyboard.get("meta", {})
    fps = int(meta.get("fps", 30))
    gi = 0
    for scene in storyboard.get("scenes", []):
        for fi in range(_scene_frame_count(scene, fps)):
            yield render_scene_frame(meta, scene, fi, fps), gi
            gi += 1


def total_frames(storyboard: dict) -> int:
    meta = storyboard.get("meta", {})
    fps = int(meta.get("fps", 30))
    return sum(_scene_frame_count(s, fps) for s in storyboard.get("scenes", []))


def total_duration(storyboard: dict) -> float:
    return sum(float(s.get("duration", 2.0)) for s in storyboard.get("scenes", []))
