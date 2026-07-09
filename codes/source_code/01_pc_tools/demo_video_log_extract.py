#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract parking-controller JSONL into normalized demo-video step data.

Read-only/offline: this script never contacts the board and never sends motion
commands.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_video_utils import build_steps_from_log, ensure_dir, fmt_num


def write_decisions(payload: dict, out_path: Path) -> None:
    lines = [
        f"# Demo decisions - {payload.get('pose_label')}",
        "",
        f"- source_log: `{payload.get('source_log')}`",
        f"- step_count: `{payload.get('step_count')}`",
        f"- stop_reason: `{payload.get('stop_reason') or 'N/A'}`",
        f"- success_reason: `{payload.get('success_reason') or 'N/A'}`",
        "",
    ]
    for step in payload.get("steps", []):
        pose = step.get("current_pose") or {}
        chosen = step.get("chosen_action") or {}
        stm = step.get("stm32_result") or {}
        lines += [
            f"## Step {step.get('step_index')}",
            "",
            f"- pose: y={fmt_num(pose.get('y_dist_cm'))} cm, lateral={fmt_num(pose.get('lateral_cm'))} cm, heading={fmt_num(pose.get('heading_deg'))} deg",
            f"- chosen: `{chosen.get('cmd') or 'N/A'}`",
            f"- score: `{fmt_num(chosen.get('score'))}`; reason: `{chosen.get('reason') or chosen.get('block_reason') or 'N/A'}`",
            f"- STM32: ACK={stm.get('ack', 'N/A')}, DONE={stm.get('done', 'N/A')}, progress={fmt_num(stm.get('odom_progress_cm'))} cm, yaw_delta={fmt_num(stm.get('yaw_delta_deg'))} deg, IMU={stm.get('imu', 'N/A')}, DROP={stm.get('drop', 'N/A')}",
            "",
            "| rank | status | cmd | score | predicted y | predicted lateral | predicted heading | reason |",
            "|---:|---|---|---:|---:|---:|---:|---|",
        ]
        cands = sorted(step.get("candidate_actions") or [], key=lambda c: (c.get("status") != "selected", c.get("score") is None, c.get("score") or 1e9))[:5]
        for i, cand in enumerate(cands, 1):
            pred = cand.get("predicted_pose") or {}
            lines.append(
                f"| {i} | {cand.get('status','candidate')} | `{cand.get('cmd','')}` | {fmt_num(cand.get('score'))} | "
                f"{fmt_num(pred.get('y_dist_cm'))} | {fmt_num(pred.get('lateral_cm'))} | {fmt_num(pred.get('heading_deg'))} | "
                f"{cand.get('block_reason') or cand.get('reason') or 'ok'} |"
            )
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log-jsonl", required=True, help="controller JSONL log path")
    ap.add_argument("--out-dir", required=True, help="pose output directory")
    ap.add_argument("--pose-label", default="pose_A")
    args = ap.parse_args()

    out_dir = ensure_dir(Path(args.out_dir))
    payload = build_steps_from_log(Path(args.log_jsonl), args.pose_label)
    steps = payload.get("steps", [])
    candidates = {
        "schema": "demo_video_candidates.v1",
        "pose_label": args.pose_label,
        "source_log": str(args.log_jsonl),
        "steps": [
            {"step_index": s.get("step_index"), "candidate_actions": s.get("candidate_actions") or []}
            for s in steps
        ],
    }
    summary = {k: payload.get(k) for k in ("schema", "pose_label", "source_log", "event_counts", "locked_initial_pose", "final_pose", "stop_reason", "success_reason", "step_count")}
    (out_dir / "steps.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_decisions(payload, out_dir / "decisions.md")
    print("STEPS", out_dir / "steps.json")
    print("CANDIDATES", out_dir / "candidates.json")
    print("SUMMARY", out_dir / "summary.json")
    print("DECISIONS", out_dir / "decisions.md")
    print("STEP_COUNT", summary.get("step_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
