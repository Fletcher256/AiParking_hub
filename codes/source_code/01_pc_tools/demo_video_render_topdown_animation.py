#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render homography/topdown motion animation frames with live plan paths.

Each step is expanded into several frames: the car interpolates from current_pose
to pose_after while the same step's candidate trajectories, chosen action,
selection reason, and STM32 feedback remain visible.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from demo_video_utils import (
    SLOT_HALF_WIDTH_CM, SLOT_Y_FAR_CM, SLOT_Y_NEAR_CM, TARGET_POSE,
    as_float, candidate_color, draw_wrapped, ensure_dir, fmt_num, load_font, load_steps,
)

W, H = 1920, 1080
PLOT = (70, 90, 1220, 1000)
PANEL = (1260, 90, 1870, 1000)
X_MIN, X_MAX = -34.0, 34.0
Y_MIN, Y_MAX = -8.0, 64.0


def xy(x_cm: float, y_cm: float) -> tuple[float, float]:
    x0, y0, x1, y1 = PLOT
    sx = x0 + (x_cm - X_MIN) / (X_MAX - X_MIN) * (x1 - x0)
    sy = y1 - (y_cm - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0)
    return sx, sy


def interp(a: Any, b: Any, t: float) -> float | None:
    aa = as_float(a); bb = as_float(b)
    if aa is None and bb is None:
        return None
    if aa is None:
        return bb
    if bb is None:
        return aa
    return aa + (bb - aa) * t


def interp_pose(a: dict[str, Any] | None, b: dict[str, Any] | None, t: float) -> dict[str, float | None]:
    a = a or {}; b = b or a
    return {
        "y_dist_cm": interp(a.get("y_dist_cm"), b.get("y_dist_cm"), t),
        "lateral_cm": interp(a.get("lateral_cm"), b.get("lateral_cm"), t),
        "heading_deg": interp(a.get("heading_deg"), b.get("heading_deg"), t),
    }


def draw_grid(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle(PLOT, fill="#07111f", outline="#475569", width=3)
    font = load_font(18)
    for x in range(-30, 31, 10):
        a = xy(x, Y_MIN); b = xy(x, Y_MAX)
        draw.line([a, b], fill="#1f2937", width=1)
        draw.text((a[0] - 12, PLOT[3] + 12), str(x), font=font, fill="#94a3b8")
    for y in range(0, 61, 10):
        a = xy(X_MIN, y); b = xy(X_MAX, y)
        draw.line([a, b], fill="#1f2937", width=1)
        draw.text((PLOT[0] - 52, a[1] - 10), str(y), font=font, fill="#94a3b8")
    a = xy(-SLOT_HALF_WIDTH_CM, SLOT_Y_NEAR_CM); b = xy(SLOT_HALF_WIDTH_CM, SLOT_Y_FAR_CM)
    draw.rectangle([a[0], b[1], b[0], a[1]], fill="#3a2f0a", outline="#facc15", width=5)
    c0 = xy(0, Y_MIN); c1 = xy(0, Y_MAX)
    draw.line([c0, c1], fill="#e5e7eb", width=2)
    draw.text((PLOT[0], 35), "Homography/topdown motion animation  (x=lateral, y=y_dist)", font=load_font(34, bold=True), fill="#f8fafc")


def draw_pose(draw: ImageDraw.ImageDraw, pose: dict[str, Any] | None, label: str, color: str, ghost: bool = False) -> None:
    if not isinstance(pose, dict):
        return
    y = as_float(pose.get("y_dist_cm")); x = as_float(pose.get("lateral_cm")); h = as_float(pose.get("heading_deg"), 0.0) or 0.0
    if x is None or y is None:
        return
    px, py = xy(x, y)
    r = 13 if not ghost else 9
    width = 5 if not ghost else 2
    fill = color if not ghost else "#111827"
    draw.ellipse([px-r, py-r, px+r, py+r], fill=fill, outline=color, width=width)
    ex = px + math.sin(math.radians(h)) * 52
    ey = py - math.cos(math.radians(h)) * 52
    draw.line([px, py, ex, ey], fill=color, width=width)
    draw.text((px + 16, py - 25), label, font=load_font(20, bold=True), fill=color)


def draw_candidates(draw: ImageDraw.ImageDraw, step: dict[str, Any]) -> None:
    for cand in step.get("candidate_actions") or []:
        pts = []
        for p in cand.get("trajectory") or []:
            x = as_float(p.get("x_cm")); y = as_float(p.get("y_cm"))
            if x is not None and y is not None:
                pts.append(xy(x, y))
        if len(pts) < 2:
            pred = cand.get("predicted_pose") or {}
            cur = step.get("current_pose") or {}
            x0 = as_float(cur.get("lateral_cm")); y0 = as_float(cur.get("y_dist_cm"))
            x1 = as_float(pred.get("lateral_cm")); y1 = as_float(pred.get("y_dist_cm"))
            if None not in (x0, y0, x1, y1):
                pts = [xy(float(x0), float(y0)), xy(float(x1), float(y1))]
        if len(pts) < 2:
            continue
        color = candidate_color(cand)
        status = str(cand.get("status") or "")
        draw.line(pts, fill=color, width=7 if status == "selected" else 3)
        for p in pts[-1:]:
            draw.ellipse([p[0]-5, p[1]-5, p[0]+5, p[1]+5], fill=color)


def draw_panel(draw: ImageDraw.ImageDraw, step: dict[str, Any], pose: dict[str, Any], pose_label: str, step_frame: int, frames_per_step: int) -> None:
    x0, y0, x1, y1 = PANEL
    draw.rounded_rectangle(PANEL, radius=22, fill="#111827", outline="#334155", width=3)
    title = load_font(32, bold=True); font = load_font(22); small = load_font(18)
    draw.text((x0 + 28, y0 + 24), f"{pose_label} · Step {step.get('step_index')}", font=title, fill="#f8fafc")
    draw.text((x0 + 28, y0 + 64), f"motion frame {step_frame}/{frames_per_step}", font=small, fill="#93c5fd")
    yy = y0 + 112
    for name, value in [
        ("y_dist", f"{fmt_num(pose.get('y_dist_cm'))} cm"),
        ("lateral", f"{fmt_num(pose.get('lateral_cm'))} cm"),
        ("heading", f"{fmt_num(pose.get('heading_deg'))}°"),
    ]:
        draw.text((x0 + 35, yy), name, font=font, fill="#94a3b8")
        draw.text((x0 + 200, yy), value, font=font, fill="#f8fafc")
        yy += 34
    chosen = step.get("chosen_action") or {}
    draw.rounded_rectangle([x0 + 28, yy + 20, x1 - 28, yy + 178], radius=16, fill="#052e16", outline="#22c55e", width=2)
    draw.text((x0 + 50, yy + 38), "Selected action", font=font, fill="#86efac")
    draw_wrapped(draw, (x0 + 50, yy + 74), chosen.get("cmd") or "N/A", font, "#f8fafc", x1 - x0 - 105, max_lines=2)
    pred = chosen.get("predicted_pose") or {}
    draw.text((x0 + 50, yy + 138), f"score={fmt_num(chosen.get('score'))}  pred={fmt_num(pred.get('y_dist_cm'))}/{fmt_num(pred.get('lateral_cm'))}/{fmt_num(pred.get('heading_deg'))}", font=small, fill="#d1fae5")
    yy += 220
    draw.text((x0 + 35, yy), "Decision basis", font=font, fill="#bfdbfe")
    yy = draw_wrapped(draw, (x0 + 35, yy + 38), chosen.get("reason") or chosen.get("block_reason") or "综合评分最低并满足约束", small, "#e5e7eb", x1 - x0 - 70, max_lines=3)
    yy += 18
    draw.text((x0 + 35, yy), "Top candidates", font=font, fill="#bfdbfe")
    yy += 36
    cands = sorted(step.get("candidate_actions") or [], key=lambda c: (c.get("status") != "selected", c.get("score") is None, c.get("score") or 1e9))[:4]
    for i, cand in enumerate(cands, 1):
        color = candidate_color(cand)
        line = f"{i}. {cand.get('status','candidate')}  score={fmt_num(cand.get('score'))}  {cand.get('cmd','')}"
        draw_wrapped(draw, (x0 + 45, yy), line, small, color, x1 - x0 - 90, max_lines=1)
        yy += 30
    yy += 18
    stm = step.get("stm32_result") or {}
    draw.rounded_rectangle([x0 + 28, y1 - 150, x1 - 28, y1 - 28], radius=16, fill="#1f2937", outline="#475569", width=2)
    feedback = f"STM32: ACK={stm.get('ack','N/A')} DONE={stm.get('done','N/A')} progress={fmt_num(stm.get('odom_progress_cm'))}cm yawΔ={fmt_num(stm.get('yaw_delta_deg'))}° IMU={stm.get('imu','N/A')} DROP={stm.get('drop','N/A')}"
    draw_wrapped(draw, (x0 + 50, y1 - 118), feedback, font, "#e5e7eb", x1 - x0 - 100, max_lines=3)


def render_frame(step: dict[str, Any], pose_label: str, t: float, frame_no: int, step_frame: int, frames_per_step: int, out_path: Path) -> None:
    img = Image.new("RGB", (W, H), "#020617")
    draw = ImageDraw.Draw(img)
    draw_grid(draw)
    draw_candidates(draw, step)
    draw_pose(draw, step.get("locked_initial_pose"), "initial", "#a78bfa", ghost=True)
    draw_pose(draw, TARGET_POSE, "target", "#facc15", ghost=True)
    before = step.get("current_pose")
    after = step.get("pose_after") or (step.get("chosen_action") or {}).get("predicted_pose") or before
    pose = interp_pose(before, after, t)
    draw_pose(draw, before, "before", "#38bdf8", ghost=True)
    draw_pose(draw, after, "after", "#f97316", ghost=True)
    draw_pose(draw, pose, "vehicle", "#22c55e")
    draw_panel(draw, step, pose, pose_label, step_frame, frames_per_step)
    draw.text((70, 1018), f"animation frame {frame_no:04d} · selected path green · blocked red · candidates blue/yellow", font=load_font(22), fill="#cbd5e1")
    img.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frames-per-step", type=int, default=10)
    args = ap.parse_args()
    payload = load_steps(Path(args.steps_json))
    out_dir = ensure_dir(Path(args.out_dir))
    n = max(2, int(args.frames_per_step))
    frame_no = 1
    for step in payload.get("steps") or []:
        for j in range(n):
            t = j / (n - 1)
            render_frame(step, payload.get("pose_label") or "pose", t, frame_no, j + 1, n, out_dir / f"frame_{frame_no:04d}.png")
            frame_no += 1
    print("TOPDOWN_ANIMATION_DIR", out_dir)
    print("FRAMES", frame_no - 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
