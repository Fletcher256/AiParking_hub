#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render top-down parking pose/candidate trajectory PNGs from steps.json."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from demo_video_utils import (
    SLOT_HALF_WIDTH_CM, SLOT_Y_FAR_CM, SLOT_Y_NEAR_CM, TARGET_POSE,
    as_float, candidate_color, ensure_dir, fmt_num, load_font, load_steps,
    pose_to_point,
)

W, H = 1280, 720
PLOT = (80, 70, 1180, 650)
X_MIN, X_MAX = -32.0, 32.0
Y_MIN, Y_MAX = -8.0, 62.0


def xy(x_cm: float, y_cm: float) -> tuple[float, float]:
    x0, y0, x1, y1 = PLOT
    sx = x0 + (x_cm - X_MIN) / (X_MAX - X_MIN) * (x1 - x0)
    sy = y1 - (y_cm - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0)
    return sx, sy


def draw_pose(draw: ImageDraw.ImageDraw, pose: dict[str, Any] | None, label: str, color: str) -> None:
    if not isinstance(pose, dict):
        return
    y = as_float(pose.get("y_dist_cm")); x = as_float(pose.get("lateral_cm")); h = as_float(pose.get("heading_deg"), 0.0) or 0.0
    if x is None or y is None:
        return
    px, py = xy(x, y)
    draw.ellipse([px-8, py-8, px+8, py+8], fill=color, outline="white", width=2)
    angle = math.radians(90.0 - h)
    ex = px + math.sin(math.radians(h)) * 34
    ey = py - math.cos(math.radians(h)) * 34
    draw.line([px, py, ex, ey], fill=color, width=5)
    draw.polygon([(ex, ey), (ex-6, ey+10), (ex+6, ey+10)], fill=color)
    font = load_font(20, bold=True)
    draw.text((px+12, py-24), label, font=font, fill=color)


def draw_grid(draw: ImageDraw.ImageDraw) -> None:
    font = load_font(16)
    draw.rectangle(PLOT, fill="#08111f", outline="#334155", width=2)
    for x in range(-30, 31, 10):
        p0 = xy(x, Y_MIN); p1 = xy(x, Y_MAX)
        draw.line([p0, p1], fill="#1f2937", width=1)
        draw.text((p0[0]-10, PLOT[3]+8), str(x), font=font, fill="#94a3b8")
    for y in range(0, 61, 10):
        p0 = xy(X_MIN, y); p1 = xy(X_MAX, y)
        draw.line([p0, p1], fill="#1f2937", width=1)
        draw.text((PLOT[0]-45, p0[1]-8), str(y), font=font, fill="#94a3b8")
    # slot rectangle
    a = xy(-SLOT_HALF_WIDTH_CM, SLOT_Y_NEAR_CM); b = xy(SLOT_HALF_WIDTH_CM, SLOT_Y_FAR_CM)
    draw.rectangle([a[0], b[1], b[0], a[1]], fill="#3b2f0b", outline="#facc15", width=4)
    c0 = xy(0, Y_MIN); c1 = xy(0, Y_MAX)
    draw.line([c0, c1], fill="#e5e7eb", width=2)
    draw.text((PLOT[0], 22), "Top-down coordinate view: x=lateral_cm, y=y_dist_cm", font=load_font(28, bold=True), fill="#e5e7eb")


def draw_candidate(draw: ImageDraw.ImageDraw, cand: dict[str, Any]) -> None:
    pts = []
    for p in cand.get("trajectory") or []:
        x = as_float(p.get("x_cm")); y = as_float(p.get("y_cm"))
        if x is not None and y is not None:
            pts.append(xy(x, y))
    if len(pts) < 2:
        return
    color = candidate_color(cand)
    width = 6 if str(cand.get("status")) == "selected" else 3
    for a, b in zip(pts, pts[1:]):
        draw.line([a, b], fill=color, width=width)
    end = pts[-1]
    draw.ellipse([end[0]-4, end[1]-4, end[0]+4, end[1]+4], fill=color)


def render_step(step: dict[str, Any], out_path: Path, pose_label: str, idx: int) -> None:
    img = Image.new("RGB", (W, H), "#020617")
    draw = ImageDraw.Draw(img)
    draw_grid(draw)
    for cand in step.get("candidate_actions") or []:
        draw_candidate(draw, cand)
    draw_pose(draw, step.get("locked_initial_pose"), "initial", "#a78bfa")
    draw_pose(draw, TARGET_POSE, "target", "#facc15")
    draw_pose(draw, step.get("current_pose") or step.get("pose_after"), "current", "#22c55e")
    font = load_font(22, bold=True)
    pose = step.get("current_pose") or {}
    chosen = step.get("chosen_action") or {}
    info = f"{pose_label}  Step {step.get('step_index', idx)}   y={fmt_num(pose.get('y_dist_cm'))}  lat={fmt_num(pose.get('lateral_cm'))}  head={fmt_num(pose.get('heading_deg'))}   chosen={chosen.get('cmd') or 'N/A'}"
    draw.rectangle([80, 655, 1180, 705], fill="#111827", outline="#374151", width=2)
    draw.text((100, 667), info, font=font, fill="#e5e7eb")
    img.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ground-homography-json", default="", help="accepted for traceability; rendering uses normalized ground pose fields")
    args = ap.parse_args()
    payload = load_steps(Path(args.steps_json))
    out_dir = ensure_dir(Path(args.out_dir))
    for i, step in enumerate(payload.get("steps") or [], 1):
        render_step(step, out_dir / f"frame_{i:04d}.png", payload.get("pose_label") or "pose", i)
    print("TOPDOWN_DIR", out_dir)
    print("FRAMES", len(payload.get("steps") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
