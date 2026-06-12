#!/usr/bin/env python
"""Compose a captioned demo screencast MP4 from scene screenshots.

Reads a scene manifest (list of {image, caption, seconds}) and renders a
1920×1080 MP4 with a lower-third caption bar on each scene. Uses the
imageio-ffmpeg static binary — no system ffmpeg required.

Usage:
    .venv/bin/python scripts/make_screencast.py \
        --manifest docs/submission/screencast_scenes.json \
        --out docs/submission/curator_demo.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FPS = 30
BG = (11, 16, 32)          # #0b1020 — Curator background
ACCENT = (118, 185, 0)     # #76b900 — NVIDIA green
TEXT = (216, 225, 238)     # #d8e1ee
BAR = (5, 10, 20)          # caption bar

# Title-card and caption fonts. Fall back to default if DejaVu missing.
def _font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


CAPTION_FONT = _font(34)
TITLE_FONT = _font(72)
SUB_FONT = _font(40)


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _letterbox(img: Image.Image) -> Image.Image:
    """Fit img into WxH on the Curator background, preserving aspect."""
    canvas = Image.new("RGB", (W, H), BG)
    iw, ih = img.size
    scale = min(W / iw, (H - 160) / ih)  # leave room for caption bar
    nw, nh = int(iw * scale), int(ih * scale)
    img2 = img.resize((nw, nh), Image.LANCZOS)
    canvas.paste(img2, ((W - nw) // 2, (H - 160 - nh) // 2 + 20))
    return canvas


def _draw_caption(canvas: Image.Image, caption: str, scene_no: int, total: int):
    draw = ImageDraw.Draw(canvas, "RGBA")
    # bottom caption bar
    draw.rectangle([(0, H - 140), (W, H)], fill=BAR + (235,))
    draw.rectangle([(0, H - 140), (W, H - 136)], fill=ACCENT)
    lines = _wrap(draw, caption, CAPTION_FONT, W - 240)
    y = H - 120
    for ln in lines[:2]:
        draw.text((60, y), ln, font=CAPTION_FONT, fill=TEXT)
        y += 42
    # scene counter + brand
    draw.text((W - 180, H - 120), f"{scene_no}/{total}", font=CAPTION_FONT, fill=ACCENT)
    draw.text((60, 30), "CURATOR", font=_font(28), fill=ACCENT)
    return canvas


def _title_card(title: str, subtitle: str) -> Image.Image:
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    tlines = _wrap(draw, title, TITLE_FONT, W - 300)
    total_h = len(tlines) * 84 + 80
    y = (H - total_h) // 2
    for ln in tlines:
        tw = draw.textlength(ln, font=TITLE_FONT)
        draw.text(((W - tw) // 2, y), ln, font=TITLE_FONT, fill=ACCENT)
        y += 84
    y += 24
    slines = _wrap(draw, subtitle, SUB_FONT, W - 400)
    for ln in slines:
        sw = draw.textlength(ln, font=SUB_FONT)
        draw.text(((W - sw) // 2, y), ln, font=SUB_FONT, fill=TEXT)
        y += 52
    return canvas


def build(manifest_path: str, out_path: str) -> None:
    scenes = json.loads(Path(manifest_path).read_text())
    total = sum(1 for s in scenes if s.get("image"))
    writer = imageio.get_writer(
        out_path, fps=FPS, codec="libx264", quality=8,
        macro_block_size=None, ffmpeg_log_level="error",
    )
    scene_no = 0
    for s in scenes:
        secs = float(s.get("seconds", 4))
        if s.get("title"):
            frame = _title_card(s["title"], s.get("subtitle", ""))
        else:
            scene_no += 1
            img = Image.open(s["image"]).convert("RGB")
            frame = _letterbox(img)
            frame = _draw_caption(frame, s.get("caption", ""), scene_no, total)
        arr = np.asarray(frame)
        for _ in range(int(secs * FPS)):
            writer.append_data(arr)
    writer.close()
    dur = sum(float(s.get("seconds", 4)) for s in scenes)
    print(f"wrote {out_path} — {dur:.0f}s, {len(scenes)} scenes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(args.manifest, args.out)
