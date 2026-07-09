#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot offline package builder for parking demo-video assets.

It orchestrates only local read/render steps.  No board or actuator command is
sent by this script.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from demo_video_utils import ROOT, ensure_dir

OUT_ROOT = ROOT / "artifacts" / "demo_video_package"
TOOLS = ROOT / "tools"


def demo_events(label: str, lateral0: float, heading0: float, terminal: bool = False) -> list[dict[str, Any]]:
    y0 = 34.0 if terminal else 46.0
    poses = [
        {"y_dist_cm": y0, "lateral_cm": lateral0, "heading_deg": heading0},
        {"y_dist_cm": y0 - 7.0, "lateral_cm": lateral0 * 0.68, "heading_deg": heading0 * 0.62},
        {"y_dist_cm": y0 - 14.0, "lateral_cm": lateral0 * 0.35, "heading_deg": heading0 * 0.28},
        {"y_dist_cm": 5.2 if not terminal else 4.2, "lateral_cm": lateral0 * 0.12, "heading_deg": 2.0},
    ]
    events: list[dict[str, Any]] = []
    for i in range(3):
        cur, nxt = poses[i], poses[i + 1]
        y_shift = i * 12
        demo_poly = [[178, 185 + y_shift], [462, 185 + y_shift], [545, 555], [95, 555]]
        demo_mask = [[178, 185 + y_shift], [300, 170 + y_shift], [462, 185 + y_shift], [545, 555], [95, 555]]
        demo_edges = {
            "back": [demo_poly[0], demo_poly[1]],
            "right": [demo_poly[1], demo_poly[2]],
            "entrance": [demo_poly[3], demo_poly[2]],
            "left": [demo_poly[0], demo_poly[3]],
        }
        candidates = []
        for ste, mult, status in [(60, 0.9, "candidate"), (100, 1.2, "blocked" if i == 0 else "candidate"), (120, 0.7, "selected"), (140, 1.05, "rejected")]:
            pred = {"y_dist_cm": max(0.0, cur["y_dist_cm"] - 6.0), "lateral_cm": cur["lateral_cm"] * mult, "heading_deg": cur["heading_deg"] * (0.55 if ste >= 120 else 0.9)}
            candidates.append({
                "cmd": f"ARC D=-6.0 STE={ste} V=1",
                "ste": ste,
                "signed_distance_cm": -6.0,
                "distance_cm": 6.0,
                "score": round(abs(pred["lateral_cm"]) * 3 + abs(pred["heading_deg"]) * 2 + abs(pred["y_dist_cm"] - 5), 3),
                "status": status,
                "hard_block": status in ("blocked", "rejected"),
                "block_reason": "横向/航向收益不足" if status != "selected" else "ok",
                "predicted_pose": pred,
                "trajectory": [
                    {"x_cm": cur["lateral_cm"], "y_cm": cur["y_dist_cm"], "heading_deg": cur["heading_deg"]},
                    {"x_cm": (cur["lateral_cm"] + pred["lateral_cm"]) / 2, "y_cm": (cur["y_dist_cm"] + pred["y_dist_cm"]) / 2, "heading_deg": (cur["heading_deg"] + pred["heading_deg"]) / 2},
                    {"x_cm": pred["lateral_cm"], "y_cm": pred["y_dist_cm"], "heading_deg": pred["heading_deg"]},
                ],
                "reason": "预计综合收敛更均衡" if status == "selected" else "保留/拒绝用于对比",
            })
        chosen = candidates[2]
        events.append({
            "timestamp": f"2026-07-03T17:00:{i*2:02d}",
            "event": "diy_path_replan",
            "locked_initial_pose": poses[0],
            "current_pose": cur,
            "confidence": 0.92 - i * 0.03,
            "min_margin_px": 32 - i * 3,
            "effective_line_risk": False,
            "mask_polygon": demo_mask,
            "slot_polygon_px": demo_poly,
            "slot_edges_px": demo_edges,
            "new_plan": {"planned_actions": candidates, "chosen_action": chosen},
        })
        events.append({
            "timestamp": f"2026-07-03T17:00:{i*2+1:02d}",
            "event": "diy_path_step",
            "step_index": i + 1,
            "locked_initial_pose": poses[0],
            "estimated_pose_before": cur,
            "chosen_action": chosen,
            "estimated_pose_after_odom": nxt,
            "visual_pose": nxt,
            "confidence": 0.9 - i * 0.02,
            "effective_line_risk": False,
            "mask_polygon": demo_mask,
            "slot_polygon_px": demo_poly,
            "slot_edges_px": demo_edges,
            "odom_delta": {"progress_cm": 6.0, "yaw_delta_deg": round(nxt["heading_deg"] - cur["heading_deg"], 2)},
            "stm32_result": {"ack_seen": True, "done_seen": True, "odom_progress_cm": 6.0, "yaw_delta_deg": round(nxt["heading_deg"] - cur["heading_deg"], 2), "stat_after": "STAT YAW=0.0 D=6.0 VEL=0 DROP=0 IMU=OK"},
            "total_reverse_cm": (i + 1) * 6.0,
        })
    events.append({"timestamp": "2026-07-03T17:00:08", "event": "diy_path_stop", "reason": "terminal_observed_success", "state": {"pose": poses[-1]}, "stop_review": {"success": True, "pose": poses[-1]}})
    events.append({"timestamp": "2026-07-03T17:00:09", "event": "diy_path_success", "reason": f"demo_{label}_success", "estimated_pose_after": poses[-1]})
    return events


def write_demo_logs(base: Path) -> dict[str, Path]:
    demo_dir = ensure_dir(base / "demo_logs")
    specs = {
        "pose_A": demo_events("pose_A", lateral0=-10.0, heading0=-18.0),
        "pose_B": demo_events("pose_B", lateral0=2.5, heading0=22.0),
        "pose_C": demo_events("pose_C", lateral0=5.5, heading0=-9.0, terminal=True),
    }
    out: dict[str, Path] = {}
    for label, events in specs.items():
        path = demo_dir / f"demo_{label}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
        out[label] = path
    return out


def run(cmd: list[str]) -> None:
    print("RUN", " ".join(str(x) for x in cmd))
    cp = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    print(cp.stdout)
    if cp.returncode != 0:
        raise SystemExit(cp.returncode)


def process_pose(label: str, log: Path, out_root: Path, yolo_dir: str = "", raw_dir: str = "",
                 fps: float = 2.0, hold_sec: float = 0.0, frames_per_step: int = 10) -> dict[str, Any]:
    pose_dir = ensure_dir(out_root / label)
    for sub in ("raw", "frames", "overlays", "topdown", "topdown_animation", "decision", "composite"):
        ensure_dir(pose_dir / sub)
    py = sys.executable
    run([py, str(TOOLS / "demo_video_log_extract.py"), "--log-jsonl", str(log), "--out-dir", str(pose_dir), "--pose-label", label])
    yolo_cmd = [py, str(TOOLS / "demo_video_render_yolo_overlay.py"), "--steps-json", str(pose_dir / "steps.json"), "--out-dir", str(pose_dir / "overlays")]
    if yolo_dir:
        yolo_cmd += ["--frame-dir", yolo_dir]
    run(yolo_cmd)
    run([py, str(TOOLS / "demo_video_render_topdown.py"), "--steps-json", str(pose_dir / "steps.json"), "--out-dir", str(pose_dir / "topdown")])
    run([py, str(TOOLS / "demo_video_render_topdown_animation.py"), "--steps-json", str(pose_dir / "steps.json"), "--out-dir", str(pose_dir / "topdown_animation"), "--frames-per-step", str(frames_per_step)])
    run([py, str(TOOLS / "demo_video_render_decision_cards.py"), "--steps-json", str(pose_dir / "steps.json"), "--out-dir", str(pose_dir / "decision")])
    cmd = [py, str(TOOLS / "demo_video_render_composite.py"), "--topdown-dir", str(pose_dir / "topdown"), "--decision-dir", str(pose_dir / "decision"), "--out-dir", str(pose_dir / "composite"), "--pose-label", label, "--yolo-dir", str(pose_dir / "overlays")]
    if raw_dir:
        cmd += ["--raw-dir", raw_dir]
    run(cmd)
    clip = out_root / "final_assets" / f"{label}_clip.mp4"
    anim_clip = out_root / "final_assets" / f"{label}_topdown_animation.mp4"
    ensure_dir(clip.parent)
    run([py, str(TOOLS / "demo_video_make_clip.py"), "--frames-dir", str(pose_dir / "composite"), "--out", str(clip), "--fps", str(fps), "--hold-sec", str(hold_sec)])
    run([py, str(TOOLS / "demo_video_make_clip.py"), "--frames-dir", str(pose_dir / "topdown_animation"), "--out", str(anim_clip), "--fps", str(max(6.0, fps)), "--hold-sec", "0"])
    summary = json.loads((pose_dir / "summary.json").read_text(encoding="utf-8"))
    return {"label": label, "log": str(log), "pose_dir": str(pose_dir), "clip": str(clip), "topdown_animation_clip": str(anim_clip), "summary": summary}


def write_package_readme(out_dir: Path, results: list[dict[str, Any]], demo: bool) -> None:
    lines = [
        "# Parking demo video package",
        "",
        f"- generated_at: `{dt.datetime.now().isoformat(timespec='seconds')}`",
        f"- demo_data: `{demo}`",
        "- safety: offline/read-only rendering only; no board/STM32 commands.",
        "",
        "## Pose summary",
        "",
        "| pose | steps | final pose | stop | success | composite clip | topdown animation |",
        "|---|---:|---|---|---|---|---|",
    ]
    for r in results:
        s = r["summary"]
        fp = s.get("final_pose") or {}
        lines.append(f"| {r['label']} | {s.get('step_count')} | y={fp.get('y_dist_cm')}, lat={fp.get('lateral_cm')}, head={fp.get('heading_deg')} | {s.get('stop_reason')} | {s.get('success_reason')} | `{r['clip']}` | `{r['topdown_animation_clip']}` |")
    lines += [
        "",
        "## Directory layout",
        "",
        "Each pose directory contains `steps.json`, `candidates.json`, `summary.json`, `decisions.md`, and generated `overlays/`, `topdown/`, `topdown_animation/`, `decision/`, `composite/` frames.",
    ]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pose-a-log", default="")
    ap.add_argument("--pose-b-log", default="")
    ap.add_argument("--pose-c-log", default="")
    ap.add_argument("--pose-a-yolo-dir", default="")
    ap.add_argument("--pose-b-yolo-dir", default="")
    ap.add_argument("--pose-c-yolo-dir", default="")
    ap.add_argument("--real-video-dir", default="")
    ap.add_argument("--out-root", default=str(OUT_ROOT))
    ap.add_argument("--stamp", default=dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--hold-sec", type=float, default=0.0)
    ap.add_argument("--animation-frames-per-step", type=int, default=10)
    ap.add_argument("--demo", action="store_true", help="force demo logs even if real logs are not provided")
    args = ap.parse_args()

    out_dir = ensure_dir(Path(args.out_root) / args.stamp)
    ensure_dir(out_dir / "final_assets")
    logs = {"pose_A": args.pose_a_log, "pose_B": args.pose_b_log, "pose_C": args.pose_c_log}
    demo = args.demo or not all(logs.values())
    if demo:
        demo_logs = write_demo_logs(out_dir)
        for k, v in demo_logs.items():
            logs[k] = str(v)
    yolo_dirs = {"pose_A": args.pose_a_yolo_dir, "pose_B": args.pose_b_yolo_dir, "pose_C": args.pose_c_yolo_dir}
    results = []
    for label in ("pose_A", "pose_B", "pose_C"):
        results.append(process_pose(label, Path(logs[label]), out_dir, yolo_dirs[label], args.real_video_dir, args.fps, args.hold_sec, args.animation_frames_per_step))
    run_config = {"logs": logs, "yolo_dirs": yolo_dirs, "real_video_dir": args.real_video_dir, "demo": demo, "fps": args.fps, "hold_sec": args.hold_sec, "animation_frames_per_step": args.animation_frames_per_step}
    (out_dir / "run_config.json").write_text(json.dumps(run_config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_package_readme(out_dir, results, demo)
    print("PACKAGE_DIR", out_dir)
    print("README", out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
