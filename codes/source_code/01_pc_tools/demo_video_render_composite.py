#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compose raw/YOLO/topdown/decision panes into 1920x1080 demo frames."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from demo_video_utils import ensure_dir, fit_image, list_images, load_font, placeholder_image

W, H = 1920, 1080
PANE_W, PANE_H = 930, 465
MARGIN = 30
HEADER_H = 70


def open_or_placeholder(paths: list[Path], idx: int, size: tuple[int, int], title: str) -> Image.Image:
    if 0 <= idx < len(paths):
        try:
            return fit_image(Image.open(paths[idx]), size)
        except Exception:
            pass
    return placeholder_image(size, title, "素材缺失时自动占位")


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    font = load_font(26, bold=True)
    x, y = xy
    draw.rounded_rectangle([x, y, x + 420, y + 42], radius=10, fill="#000000AA")
    draw.text((x + 14, y + 7), text, font=font, fill="#f8fafc")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topdown-dir", required=True)
    ap.add_argument("--decision-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", default="")
    ap.add_argument("--yolo-dir", default="")
    ap.add_argument("--pose-label", default="pose")
    args = ap.parse_args()

    topdown = list_images(Path(args.topdown_dir))
    decision = list_images(Path(args.decision_dir))
    raw = list_images(Path(args.raw_dir)) if args.raw_dir else []
    yolo = list_images(Path(args.yolo_dir)) if args.yolo_dir else []
    count = max(len(topdown), len(decision), 1)
    out_dir = ensure_dir(Path(args.out_dir))
    font_title = load_font(34, bold=True)
    font_small = load_font(20)
    for i in range(count):
        canvas = Image.new("RGB", (W, H), "#020617")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, 0, W, HEADER_H], fill="#0f172a")
        draw.text((MARGIN, 18), f"Autonomous Parking Demo · {args.pose_label} · Step {i+1}", font=font_title, fill="#f8fafc")
        draw.text((W-590, 24), "旁路观测 / 离线回放 / 不参与控制闭环", font=font_small, fill="#93c5fd")
        panes = [
            (MARGIN, HEADER_H + MARGIN, open_or_placeholder(raw, i, (PANE_W, PANE_H), "Raw real video frame not available"), "实车画面 / raw"),
            (MARGIN + PANE_W + MARGIN, HEADER_H + MARGIN, open_or_placeholder(yolo, i, (PANE_W, PANE_H), "YOLO frame not available for this step"), "YOLO mask + polygon"),
            (MARGIN, HEADER_H + MARGIN + PANE_H + MARGIN, open_or_placeholder(topdown, i, (PANE_W, PANE_H), "Topdown not available"), "Homography / topdown"),
            (MARGIN + PANE_W + MARGIN, HEADER_H + MARGIN + PANE_H + MARGIN, open_or_placeholder(decision, i, (PANE_W, PANE_H), "Decision card not available"), "判断依据 / candidates"),
        ]
        for x, y, img, name in panes:
            canvas.paste(img, (x, y))
            draw.rectangle([x, y, x + PANE_W, y + PANE_H], outline="#334155", width=3)
            label(draw, (x + 14, y + 12), name)
        canvas.save(out_dir / f"frame_{i+1:04d}.png")
    print("COMPOSITE_DIR", out_dir)
    print("FRAMES", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
