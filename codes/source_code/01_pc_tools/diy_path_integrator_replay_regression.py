#!/usr/bin/env python3
"""Replay diy_first_frame_path_parking logs and verify odom pose integration.

The regression reads `diy_path_step` JSONL events, recomputes the odom-only
pose update from:

  estimated_pose_before + STM32 progress/yaw + action signed direction

and compares the result with the logged `estimated_pose_after_odom`.

It is intentionally offline/read-only: no board access, no motion.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = ROOT / "artifacts" / "integrator_replay_regression"


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def wrap_deg(value: float) -> float:
    v = float(value)
    while v > 180.0:
        v -= 360.0
    while v <= -180.0:
        v += 360.0
    return v


def round_pose(pose: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(pose, dict):
        return None
    out = {}
    for key in ("y_dist_cm", "lateral_cm", "heading_deg"):
        v = as_float(pose.get(key))
        if v is None:
            return None
        out[key] = round(v, 6)
    return out


def parse_signed_d_from_cmd(cmd: str) -> float | None:
    m = re.search(r"(?:^|\s)D=([+-]?\d+(?:\.\d+)?)", str(cmd or ""))
    return None if not m else as_float(m.group(1))


def action_signed_distance(action: dict[str, Any] | None, chosen: dict[str, Any] | None) -> float | None:
    for obj in (action, chosen, (action or {}).get("binding") if isinstance(action, dict) else None):
        if isinstance(obj, dict):
            v = as_float(obj.get("signed_distance_cm"))
            if v is not None:
                return v
    cmd = ""
    if isinstance(action, dict):
        cmd = str(action.get("cmd") or "")
    if not cmd and isinstance(chosen, dict):
        cmd = str(chosen.get("cmd") or "")
    return parse_signed_d_from_cmd(cmd)


def signed_progress_for_event(event: dict[str, Any]) -> float:
    odom = event.get("odom_delta") or {}
    v = as_float(odom.get("signed_progress_cm"))
    if v is not None:
        return v
    motion = event.get("stm32_result") or {}
    v = as_float(motion.get("signed_progress_cm"))
    if v is not None:
        return v
    progress = as_float(odom.get("progress_cm"), as_float(motion.get("odom_progress_cm"), 0.0)) or 0.0
    chosen = event.get("chosen_action") or {}
    signed_cmd = action_signed_distance(chosen.get("action") if isinstance(chosen, dict) else None, chosen)
    # Historical logs were reverse-only and had no signed field.
    if signed_cmd is not None and signed_cmd > 0.0:
        return -abs(progress)
    return abs(progress)


def integrate_signed_pose(pose: dict[str, float], signed_progress_cm: float, yaw_delta_deg: float) -> dict[str, float]:
    heading0 = wrap_deg(pose["heading_deg"])
    yaw_delta = wrap_deg(yaw_delta_deg)
    heading_mid = wrap_deg(heading0 + 0.5 * yaw_delta)
    theta = math.radians(heading_mid)
    return {
        "y_dist_cm": pose["y_dist_cm"] - signed_progress_cm * math.cos(theta),
        "lateral_cm": pose["lateral_cm"] + signed_progress_cm * math.sin(theta),
        "heading_deg": wrap_deg(heading0 + yaw_delta),
    }


def replay_step(event: dict[str, Any], source: Path, lineno: int) -> dict[str, Any] | None:
    before = round_pose(event.get("estimated_pose_before"))
    logged_after = round_pose(event.get("estimated_pose_after_odom"))
    if before is None or logged_after is None:
        return None
    odom = event.get("odom_delta") or {}
    progress = as_float(odom.get("progress_cm"), 0.0) or 0.0
    signed_progress = signed_progress_for_event(event)
    yaw_delta = as_float(odom.get("yaw_delta_deg"), None)
    if yaw_delta is None:
        raw = as_float(odom.get("raw_yaw_delta_deg"), 0.0) or 0.0
        yaw_sign = as_float(odom.get("diy_path_yaw_sign"), 1.0) or 1.0
        yaw_delta = wrap_deg(raw * yaw_sign)
    predicted = integrate_signed_pose(before, signed_progress, yaw_delta)

    lateral_model = (event.get("stm32_result") or {}).get("lateral_motion_model") or event.get("lateral_motion_model") or {}
    adjusted_delta = as_float(lateral_model.get("adjusted_lateral_delta_cm"))
    if adjusted_delta is not None:
        predicted["lateral_cm"] = before["lateral_cm"] + adjusted_delta

    errors = {
        "y_dist_cm": predicted["y_dist_cm"] - logged_after["y_dist_cm"],
        "lateral_cm": predicted["lateral_cm"] - logged_after["lateral_cm"],
        "heading_deg": wrap_deg(predicted["heading_deg"] - logged_after["heading_deg"]),
    }
    return {
        "source": str(source),
        "lineno": lineno,
        "step_index": event.get("step_index"),
        "cmd": ((event.get("chosen_action") or {}).get("action") or {}).get("cmd") or (event.get("chosen_action") or {}).get("cmd"),
        "progress_cm": progress,
        "signed_progress_cm": signed_progress,
        "yaw_delta_deg": yaw_delta,
        "before": before,
        "predicted_after_odom": {k: round(v, 6) for k, v in predicted.items()},
        "logged_after_odom": logged_after,
        "error": {k: round(v, 6) for k, v in errors.items()},
        "max_abs_error": round(max(abs(v) for v in errors.values()), 6),
        "terminal_shuffle": bool((event.get("chosen_action") or {}).get("terminal_shuffle")),
    }


def iter_jsonl(path: Path):
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip("\ufeff\r\n\t ")
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        yield lineno, row


def expand_inputs(patterns: list[str]) -> list[Path]:
    out = []
    for item in patterns:
        matches = glob.glob(item)
        if matches:
            out.extend(Path(m) for m in matches)
        else:
            p = Path(item)
            if p.exists():
                out.append(p)
    return sorted(set(p.resolve() for p in out))


def summarize(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    files = []
    for source, ss in sorted(by_source.items()):
        max_err = max((r["max_abs_error"] for r in ss), default=0.0)
        files.append({
            "source": source,
            "step_count": len(ss),
            "max_abs_error": round(max_err, 6),
            "mean_abs_error": round(statistics.mean([r["max_abs_error"] for r in ss]), 6) if ss else 0.0,
            "pass": max_err <= threshold,
        })
    overall_max = max((r["max_abs_error"] for r in rows), default=0.0)
    return {
        "schema": "diy_path_integrator_replay_regression_summary.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "threshold": threshold,
        "total_steps": len(rows),
        "max_abs_error": round(overall_max, 6),
        "pass": bool(rows and overall_max <= threshold),
        "files": files,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl", nargs="+", help="JSONL logs or glob patterns")
    ap.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    ap.add_argument("--threshold", type=float, default=0.08,
                    help="maximum allowed absolute y/lateral/heading replay error")
    args = ap.parse_args()

    paths = expand_inputs(args.jsonl)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = Path(args.out_root) / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in paths:
        for lineno, event in iter_jsonl(path):
            if event.get("event") != "diy_path_step":
                continue
            row = replay_step(event, path, lineno)
            if row:
                rows.append(row)

    raw_path = outdir / "replay_step_results.jsonl"
    with raw_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    csv_path = outdir / "replay_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "source", "lineno", "step_index", "cmd", "progress_cm", "signed_progress_cm",
            "yaw_delta_deg", "max_abs_error", "terminal_shuffle",
            "err_y_dist_cm", "err_lateral_cm", "err_heading_deg",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "source": row["source"],
                "lineno": row["lineno"],
                "step_index": row["step_index"],
                "cmd": row["cmd"],
                "progress_cm": row["progress_cm"],
                "signed_progress_cm": row["signed_progress_cm"],
                "yaw_delta_deg": row["yaw_delta_deg"],
                "max_abs_error": row["max_abs_error"],
                "terminal_shuffle": row["terminal_shuffle"],
                "err_y_dist_cm": row["error"]["y_dist_cm"],
                "err_lateral_cm": row["error"]["lateral_cm"],
                "err_heading_deg": row["error"]["heading_deg"],
            })

    summary = summarize(rows, args.threshold)
    (outdir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# DIY path integrator replay regression",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- total_steps: `{summary['total_steps']}`",
        f"- threshold: `{summary['threshold']}`",
        f"- max_abs_error: `{summary['max_abs_error']}`",
        f"- pass: `{summary['pass']}`",
        "",
        "| file | steps | max error | mean error | pass |",
        "|---|---:|---:|---:|---|",
    ]
    for item in summary["files"]:
        lines.append(
            f"| `{item['source']}` | {item['step_count']} | {item['max_abs_error']} | {item['mean_abs_error']} | `{item['pass']}` |"
        )
    (outdir / "integrator_replay_regression_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    print("OUTDIR", outdir)
    print("RAW", raw_path)
    print("CSV", csv_path)
    print("SUMMARY", outdir / "summary.json")
    print("REPORT", outdir / "integrator_replay_regression_report.md")
    print("PASS", summary["pass"], "MAX_ERROR", summary["max_abs_error"], "STEPS", summary["total_steps"])
    return 0 if summary["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
