#!/usr/bin/env python3
"""Analyze board_parking_controller.py dry-run JSONL logs.

This is offline-only. It never connects to the board, VM, STM32, serial, CAN,
motor, steering, brake, or throttle. It summarizes whether the perception and
candidate command stream is stable enough to consider a later real single-step
test.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def nums(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            out.append(float(value))
    return out


def stat(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "std": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(mean(values), 4),
        "std": round(pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def command_flips(candidates: list[dict[str, Any]]) -> int:
    prev = None
    flips = 0
    for row in candidates:
        cmd = str(row.get("candidate_cmd") or "")
        family = cmd.split()[0] if cmd else ""
        if prev is not None and family != prev:
            flips += 1
        prev = family
    return flips


def write_curve(path: Path, candidates: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "index",
        "time_unix",
        "stable",
        "state",
        "confidence",
        "lon",
        "lat",
        "head",
        "axis_yaw_deg",
        "candidate_cmd",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, row in enumerate(candidates):
            writer.writerow({field: row.get(field, "") for field in fields if field != "index"} | {"index": idx})


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [row for row in rows if row.get("event") == "candidate"]
    replanner_steps = [row for row in rows if row.get("event") == "replanner_step"]
    vision_lost = [row for row in rows if row.get("event") == "vision_lost"]
    stable = [row for row in candidates if row.get("stable") is True]
    unstable = [row for row in candidates if row.get("stable") is not True]
    commands = Counter(str(row.get("candidate_cmd") or "") for row in stable)
    states = Counter(str(row.get("state") or "") for row in candidates)

    chosen_actions: Counter[str] = Counter()
    chosen_commands: Counter[str] = Counter()
    chosen_origins: Counter[str] = Counter()
    blocked_reasons: Counter[str] = Counter()
    gate_true_counts: Counter[str] = Counter()
    gate_false_counts: Counter[str] = Counter()
    replanner_motion_events = 0
    for row in replanner_steps:
        chosen = row.get("chosen") if isinstance(row.get("chosen"), dict) else {}
        gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
        action_id = str(chosen.get("action_id") or chosen.get("id") or chosen.get("action") or "")
        cmd = str(chosen.get("command") or chosen.get("cmd") or "")
        origin = str(chosen.get("origin") or chosen.get("prediction_origin") or "")
        if action_id:
            chosen_actions[action_id] += 1
        if cmd:
            chosen_commands[cmd] += 1
        if origin:
            chosen_origins[origin] += 1
        if gates.get("will_execute_motion") is True:
            replanner_motion_events += 1
        for key, value in gates.items():
            if isinstance(value, bool):
                if value:
                    gate_true_counts[key] += 1
                else:
                    gate_false_counts[key] += 1
        for field in ("blocked_reasons", "hard_block_reasons", "reasons"):
            reasons = chosen.get(field)
            if isinstance(reasons, list):
                for reason in reasons:
                    blocked_reasons[str(reason)] += 1
            elif isinstance(reasons, str) and reasons:
                blocked_reasons[reasons] += 1
    return {
        "schema_version": 1,
        "total_events": len(rows),
        "candidate_events": len(candidates),
        "replanner_step_events": len(replanner_steps),
        "stable_candidate_events": len(stable),
        "unstable_candidate_events": len(unstable),
        "vision_lost_events": len(vision_lost),
        "command_family_flips": command_flips(stable),
        "states": dict(states),
        "top_commands": commands.most_common(10),
        "replanner": {
            "chosen_actions": chosen_actions.most_common(20),
            "chosen_commands": chosen_commands.most_common(20),
            "chosen_origins": chosen_origins.most_common(20),
            "blocked_reasons": blocked_reasons.most_common(20),
            "gate_true_counts": dict(gate_true_counts),
            "gate_false_counts": dict(gate_false_counts),
            "will_execute_motion_events": replanner_motion_events,
        },
        "confidence": stat(nums(candidates, "confidence")),
        "lon_cm": stat(nums(candidates, "lon")),
        "lat_cm": stat(nums(candidates, "lat")),
        "head_deg": stat(nums(candidates, "head")),
        "axis_yaw_deg": stat(nums(candidates, "axis_yaw_deg")),
        "slot_center_x_cm": stat([float(row["slot_center_cm"][0]) for row in candidates if isinstance(row.get("slot_center_cm"), list)]),
        "slot_center_y_cm": stat([float(row["slot_center_cm"][1]) for row in candidates if isinstance(row.get("slot_center_cm"), list)]),
        "safety": {
            "motion_events": sum(1 for row in rows if row.get("motion_enabled") is True),
            "actuator_allowed_events": sum(1 for row in rows if row.get("actuator_control_allowed") is True),
            "send_to_stm32_events": sum(1 for row in rows if row.get("send_to_stm32") is True),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--summary-json", type=Path)
    ap.add_argument("--curve-csv", type=Path)
    args = ap.parse_args()

    rows = load_jsonl(args.jsonl)
    summary = build_summary(rows)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(text + "\n", encoding="utf-8")
    if args.curve_csv:
        write_curve(args.curve_csv, [row for row in rows if row.get("event") == "candidate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
