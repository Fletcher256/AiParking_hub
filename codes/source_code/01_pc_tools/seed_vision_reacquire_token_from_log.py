#!/usr/bin/env python3
"""Seed a one-shot kinematic-lattice vision-reacquire token from a recent log.

This is an operator/debug utility for the case where a previous closed-loop run
ended in a no-YOLO viewpoint before token persistence existed.  It extracts the
last executed short reverse action and the latest stable visual state after it,
then writes the same token that the controller now writes online.
"""

from __future__ import annotations

import argparse
import json
import os
import time


SERVO_CENTER = 100.0
GEAR = 1


def to_float(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_motion_command_fields(cmd):
    parts = str(cmd or "").split()
    kind = parts[0].upper() if parts else ""
    kv = {}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.upper()] = v
    d = to_float(kv.get("D"), 0.0)
    servo = to_float(kv.get("STE"), SERVO_CENTER) if kind == "ARC" else SERVO_CENTER
    velocity = int(to_float(kv.get("V"), GEAR))
    return {
        "kind": kind,
        "d_cm": d,
        "abs_d_cm": abs(d),
        "servo": servo,
        "velocity": velocity,
    }


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def candidate_visual_state(row):
    lattice = row.get("kinematic_lattice") or {}
    state = lattice.get("pre_state")
    if not isinstance(state, dict):
        return None
    if not row.get("stable", False):
        return None
    return state


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-jsonl", required=True)
    ap.add_argument("--out-token", default="/tmp/parking_vision_reacquire_token.json")
    ap.add_argument("--max-age-sec", type=float, default=600.0)
    args = ap.parse_args(argv)

    rows = read_jsonl(args.log_jsonl)
    if not rows:
        raise SystemExit("no rows in %s" % args.log_jsonl)

    motion_idx = None
    motion = None
    for idx, row in enumerate(rows):
        if row.get("event") == "stm32_motion_result":
            fields = parse_motion_command_fields(row.get("candidate_cmd"))
            if fields["kind"] in ("MOVE", "ARC") and fields["d_cm"] < -0.1:
                motion_idx = idx
                motion = row
    if motion_idx is None or motion is None:
        raise SystemExit("no executed reverse motion found")

    motion_candidate = None
    for row in rows[:motion_idx]:
        if row.get("event") == "candidate" and row.get("will_execute_motion"):
            motion_candidate = row

    visual_row = None
    for row in rows[motion_idx + 1:]:
        if row.get("event") == "vision_lost":
            break
        if row.get("event") == "candidate" and candidate_visual_state(row) is not None:
            visual_row = row
    if visual_row is None:
        # Fall back to the visual state that selected the motion.
        visual_row = motion_candidate
    if visual_row is None or candidate_visual_state(visual_row) is None:
        raise SystemExit("no stable visual state found around last motion")

    fields = parse_motion_command_fields(motion.get("candidate_cmd"))
    tier = (
        ((motion_candidate or {}).get("binding") or {}).get("tier") or
        (((motion_candidate or {}).get("kinematic_lattice") or {}).get("mode")) or
        "unknown"
    )
    now = time.time()
    original_visual_time = to_float(visual_row.get("time_unix"), now)
    motion_time = to_float(motion.get("time_unix"), original_visual_time)
    command_step = to_float(motion.get("commanded_step_cm"), fields["abs_d_cm"])
    last_motion = {
        "schema": "kinematic_lattice_last_motion.v1",
        "time_unix": motion_time,
        # Treat the operator-approved seed time as the current validity time.
        # The original visual timestamp is preserved for audit below.
        "visual_time_unix": now,
        "original_visual_time_unix": original_visual_time,
        "original_motion_time_unix": motion_time,
        "source": "seed_from_log",
        "cmd": motion.get("candidate_cmd"),
        "action": fields["kind"],
        "reason": "seeded_from_recent_closed_loop_log",
        "tier": tier,
        "command_fields": fields,
        "servo": fields["servo"],
        "commanded_step_cm": round(abs(command_step), 3),
        "odom_progress_cm": motion.get("odom_progress_cm"),
        "visual_state": candidate_visual_state(visual_row),
        "steps_after": (visual_row.get("totals") or {}).get("steps_done"),
        "total_cm_after": (visual_row.get("totals") or {}).get("total_cm"),
    }
    token = {
        "schema": "parking_vision_reacquire_token.v1",
        "time_unix": now,
        "consumed": False,
        "reason": "seeded_from_recent_closed_loop_log",
        "source_log_jsonl": args.log_jsonl,
        "visual_age_sec_at_seed": round(max(0.0, now - original_visual_time), 3),
        "max_age_sec": args.max_age_sec,
        "last_motion": last_motion,
    }
    parent = os.path.dirname(args.out_token)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = "%s.tmp" % args.out_token
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(token, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, args.out_token)
    print("SEEDED_VISION_REACQUIRE_TOKEN path=%s cmd=%s age_sec=%.3f" % (
        args.out_token,
        motion.get("candidate_cmd"),
        max(0.0, now - original_visual_time),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
