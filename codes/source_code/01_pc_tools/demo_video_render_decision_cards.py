#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render per-step decision-card PNGs from normalized demo steps."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from demo_video_utils import ensure_dir, fmt_num, load_font, load_steps, draw_wrapped

W, H = 1280, 720


def concise_reason(cand: dict[str, Any]) -> str:
    status = str(cand.get("status") or "candidate")
    if status == "selected":
        return cand.get("reason") or cand.get("block_reason") or "综合评分最低，满足当前阶段约束"
    if cand.get("hard_block") or "block" in status or "reject" in status:
        return cand.get("block_reason") or cand.get("reason") or "触发硬约束或预测不可行"
    return cand.get("reason") or cand.get("block_reason") or "保留为候选"


def render_card(step: dict[str, Any], out_path: Path, pose_label: str, idx: int) -> None:
    img = Image.new("RGB", (W, H), "#0b1020")
    draw = ImageDraw.Draw(img)
    title = load_font(40, bold=True)
    h2 = load_font(26, bold=True)
    font = load_font(22)
    small = load_font(18)
    draw.rectangle([0, 0, W, 86], fill="#111827")
    draw.text((40, 22), f"{pose_label} · Step {step.get('step_index', idx)} 判断依据", font=title, fill="#f8fafc")
    pose = step.get("current_pose") or {}
    chosen = step.get("chosen_action") or {}
    stm = step.get("stm32_result") or {}
    # left state panel
    draw.rounded_rectangle([40, 110, 600, 345], radius=18, fill="#172033", outline="#334155", width=2)
    draw.text((70, 132), "当前状态", font=h2, fill="#93c5fd")
    y = 178
    for label, value in [
        ("y_dist", f"{fmt_num(pose.get('y_dist_cm'))} cm"),
        ("lateral", f"{fmt_num(pose.get('lateral_cm'))} cm"),
        ("heading", f"{fmt_num(pose.get('heading_deg'))}°"),
        ("confidence", fmt_num(step.get('confidence'), 3)),
        ("line risk", str(step.get('effective_line_risk', step.get('line_risk', 'N/A')))),
    ]:
        draw.text((80, y), f"{label}: ", font=font, fill="#94a3b8")
        draw.text((230, y), value, font=font, fill="#f8fafc")
        y += 34
    # chosen panel
    draw.rounded_rectangle([640, 110, 1240, 345], radius=18, fill="#102516", outline="#22c55e", width=2)
    draw.text((670, 132), "选择动作", font=h2, fill="#86efac")
    draw_wrapped(draw, (675, 178), chosen.get("cmd") or "N/A", font, "#f8fafc", 520, max_lines=2)
    pred = chosen.get("predicted_pose") or {}
    draw.text((675, 245), f"score={fmt_num(chosen.get('score'))}  pred y={fmt_num(pred.get('y_dist_cm'))}  lat={fmt_num(pred.get('lateral_cm'))}  head={fmt_num(pred.get('heading_deg'))}", font=small, fill="#d1fae5")
    draw_wrapped(draw, (675, 280), "选择理由：" + concise_reason(chosen), small, "#d1fae5", 520, max_lines=2)
    # candidates
    draw.rounded_rectangle([40, 375, 1240, 585], radius=18, fill="#111827", outline="#334155", width=2)
    draw.text((70, 395), "Top candidates", font=h2, fill="#e5e7eb")
    cands = sorted(step.get("candidate_actions") or [], key=lambda c: (c.get("status") != "selected", c.get("score") is None, c.get("score") or 1e9))[:5]
    xcols = [70, 160, 555, 670, 790, 925]
    headers = ["#", "cmd", "score", "status", "pred", "reason"]
    for x, header in zip(xcols, headers):
        draw.text((x, 435), header, font=small, fill="#94a3b8")
    yy = 465
    for rank, cand in enumerate(cands, 1):
        pred = cand.get("predicted_pose") or {}
        status = str(cand.get("status") or "candidate")
        color = "#86efac" if status == "selected" else ("#fca5a5" if cand.get("hard_block") or "block" in status or "reject" in status else "#bfdbfe")
        draw.text((xcols[0], yy), str(rank), font=small, fill=color)
        draw_wrapped(draw, (xcols[1], yy), cand.get("cmd") or "", small, color, 370, max_lines=1)
        draw.text((xcols[2], yy), fmt_num(cand.get("score")), font=small, fill=color)
        draw.text((xcols[3], yy), status, font=small, fill=color)
        draw.text((xcols[4], yy), f"{fmt_num(pred.get('y_dist_cm'))}/{fmt_num(pred.get('lateral_cm'))}/{fmt_num(pred.get('heading_deg'))}", font=small, fill=color)
        draw_wrapped(draw, (xcols[5], yy), concise_reason(cand), small, color, 285, max_lines=1)
        yy += 34
    # STM32 feedback
    draw.rounded_rectangle([40, 610, 1240, 695], radius=18, fill="#1f2937", outline="#475569", width=2)
    feedback = (
        f"STM32反馈：ACK={stm.get('ack', 'N/A')}  DONE={stm.get('done', 'N/A')}  "
        f"实际进度={fmt_num(stm.get('odom_progress_cm'))}cm  yawΔ={fmt_num(stm.get('yaw_delta_deg'))}°  "
        f"IMU={stm.get('imu', 'N/A')}  DROP={stm.get('drop', 'N/A')}"
    )
    draw_wrapped(draw, (70, 635), feedback, font, "#e5e7eb", 1130, max_lines=2)
    img.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps-json", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    payload = load_steps(Path(args.steps_json))
    out_dir = ensure_dir(Path(args.out_dir))
    for i, step in enumerate(payload.get("steps") or [], 1):
        render_card(step, out_dir / f"frame_{i:04d}.png", payload.get("pose_label") or "pose", i)
    print("DECISION_DIR", out_dir)
    print("FRAMES", len(payload.get("steps") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
