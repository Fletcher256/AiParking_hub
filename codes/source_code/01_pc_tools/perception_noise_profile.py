#!/usr/bin/env python3
"""Profile parking perception jitter/dropout from controller JSONL logs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def load_rows(paths):
    for path in paths:
        p = Path(path)
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row["_source_file"] = str(p)
            row["_lineno"] = lineno
            yield row


def percentile(values, q):
    if not values:
        return None
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def hist(values, bins):
    out = []
    for lo, hi in bins:
        count = sum(1 for v in values if lo <= v < hi)
        out.append({"range": [lo, hi], "count": count})
    if values:
        out.append({"range": [bins[-1][1], None], "count": sum(1 for v in values if v >= bins[-1][1])})
    return out


def candidate_state(row):
    rel = row.get("slot_relative_state") or {}
    ground = rel.get("ground_estimate") or {}
    image = rel.get("image") or {}
    corridor = rel.get("corridor") or {}
    center_cm = ground.get("rear_target_cm") or ground.get("slot_center_cm")
    center_px = image.get("center_px")
    yaw = ground.get("slot_axis_heading_deg")
    if center_cm is None or yaw is None:
        return None
    try:
        return {
            "time_unix": float(row.get("time_unix", 0.0)),
            "stable": bool(row.get("stable")),
            "center_cm": [float(center_cm[0]), float(center_cm[1])],
            "center_px": [float(center_px[0]), float(center_px[1])] if center_px else None,
            "yaw_deg": float(yaw),
            "slot_x_err_px": float(corridor.get("slot_x_err_px", 0.0)),
            "min_margin_px": float(corridor.get("min_margin_px", 0.0)),
            "line_risk": bool(corridor.get("line_risk")),
            "source_file": row.get("_source_file"),
            "lineno": row.get("_lineno"),
        }
    except (TypeError, ValueError, IndexError):
        return None


def angle_diff_deg(a, b):
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def stats(values):
    return {
        "count": len(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def round_floats(obj, ndigits=4):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [round_floats(v, ndigits) for v in obj]
    if isinstance(obj, dict):
        return {k: round_floats(v, ndigits) for k, v in obj.items()}
    return obj


def build_profile(rows):
    states = []
    event_counts = {}
    dropout_runs = []
    current_dropout = 0
    deltas_cm = []
    deltas_px = []
    deltas_yaw = []
    largest_jumps = []
    previous = None

    for row in rows:
        event = row.get("event", "")
        event_counts[event] = event_counts.get(event, 0) + 1
        state = candidate_state(row) if event == "candidate" else None
        is_dropout = event in ("vision_lost", "slot_target_selection_wait")
        if state:
            if current_dropout:
                dropout_runs.append(current_dropout)
                current_dropout = 0
            states.append(state)
            if previous:
                dc = math.hypot(
                    state["center_cm"][0] - previous["center_cm"][0],
                    state["center_cm"][1] - previous["center_cm"][1],
                )
                dyaw = abs(angle_diff_deg(state["yaw_deg"], previous["yaw_deg"]))
                deltas_cm.append(dc)
                deltas_yaw.append(dyaw)
                dpx = None
                if state["center_px"] and previous["center_px"]:
                    dpx = math.hypot(
                        state["center_px"][0] - previous["center_px"][0],
                        state["center_px"][1] - previous["center_px"][1],
                    )
                    deltas_px.append(dpx)
                largest_jumps.append({
                    "dc_cm": dc,
                    "dyaw_deg": dyaw,
                    "dpx": dpx,
                    "from": {"file": previous["source_file"], "lineno": previous["lineno"]},
                    "to": {"file": state["source_file"], "lineno": state["lineno"]},
                    "from_state": {
                        "center_cm": previous["center_cm"],
                        "yaw_deg": previous["yaw_deg"],
                        "slot_x_err_px": previous["slot_x_err_px"],
                    },
                    "to_state": {
                        "center_cm": state["center_cm"],
                        "yaw_deg": state["yaw_deg"],
                        "slot_x_err_px": state["slot_x_err_px"],
                    },
                })
            previous = state
        elif is_dropout:
            current_dropout += 1
        else:
            if current_dropout:
                dropout_runs.append(current_dropout)
                current_dropout = 0
    if current_dropout:
        dropout_runs.append(current_dropout)

    largest_jumps.sort(key=lambda item: (item["dc_cm"], item["dyaw_deg"]), reverse=True)
    frame_period_sec = 0.25
    dropout_p99 = percentile(dropout_runs, 0.99) or 0.0
    center_p99 = percentile(deltas_cm, 0.99) or 1.0
    yaw_p99 = percentile(deltas_yaw, 0.99) or 1.0
    gate_center = max(1.5, min(4.0, center_p99 * 1.5))
    gate_yaw = max(2.0, min(8.0, yaw_p99 * 1.5))
    hold_grace = max(0.8, min(2.5, dropout_p99 * frame_period_sec * 1.5))
    hold_max_frames = max(2, int(math.ceil(hold_grace / frame_period_sec)))

    return {
        "schema": "perception_noise_profile.v1",
        "counts": {
            "events": event_counts,
            "candidate_states": len(states),
            "dropout_runs": len(dropout_runs),
        },
        "frame_delta_cm": stats(deltas_cm),
        "frame_delta_px": stats(deltas_px),
        "frame_delta_yaw_deg": stats(deltas_yaw),
        "dropout_run_frames": {
            **stats(dropout_runs),
            "histogram": hist(dropout_runs, [(0, 1), (1, 2), (2, 4), (4, 8), (8, 16), (16, 32)]),
        },
        "largest_jumps": largest_jumps[:12],
        "recommended_filter": {
            "schema": "perception_filter.v1",
            "required_frames": 5,
            "gate_center_shift_cm": gate_center,
            "gate_yaw_shift_deg": gate_yaw,
            "gate_static_scale": 0.5,
            "outlier_accept_consecutive": 3,
            "hold_grace_sec": hold_grace,
            "hold_max_frames": hold_max_frames,
            "divergence_debounce_frames": 2,
            "line_risk_debounce_frames": 1,
            "notes": "thresholds derived from controller JSONL logs; line_risk intentionally not debounced",
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl", nargs="+")
    ap.add_argument("--out", default="")
    ap.add_argument("--config-out", default="")
    args = ap.parse_args()
    profile = round_floats(build_profile(load_rows(args.jsonl)))
    text = json.dumps(profile, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.config_out:
        Path(args.config_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.config_out).write_text(
            json.dumps(profile["recommended_filter"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
