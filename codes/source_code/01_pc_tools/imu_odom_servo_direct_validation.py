#!/usr/bin/env python3
"""IMU + odometry servo-direct validation runner.

This tool is intentionally independent from the parking controller.  It
validates the low-level pair used by the DIY parking stack:

    STM32 IMU yaw + STM32 odometry D/X/Y

It never writes board configuration.  Motion is opt-in and requires
``--run-sweep --allow-risk``; each ARC step is followed by STOP and a fresh STAT.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from parking_fusion import parse_stm32_text, wrap_degrees


ROOT = Path(__file__).resolve().parents[1]
STM32_SEND = ROOT / "tools" / "stm32_send.py"
DEFAULT_STES = "90,92,94,95,96,98,100,102,105"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def parse_csv_numbers(text: str, cast=float) -> list[Any]:
    out = []
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        out.append(cast(item))
    return out


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def sign(value: float, eps: float = 1e-6) -> int:
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for ev in reversed(events):
        if ev.get("type") == event_type:
            return ev
    return None


@dataclass
class Stm32Result:
    command: str
    returncode: int
    started_at: str
    ended_at: str
    stdout: str
    stderr: str
    events: list[dict[str, Any]]

    def latest_stat(self) -> dict[str, Any] | None:
        return latest_event(self.events, "stat")

    def latest_done(self) -> dict[str, Any] | None:
        return latest_event(self.events, "done")

    def latest_err(self) -> dict[str, Any] | None:
        return latest_event(self.events, "err")

    def to_json(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "events": self.events,
        }


def run_stm32(
    args: argparse.Namespace,
    command: str,
    *,
    allow_motion: bool = False,
    read_sec: int = 1,
    timeout_pad_sec: int = 30,
) -> Stm32Result:
    cmd = [
        sys.executable,
        str(STM32_SEND),
        "--host",
        args.host,
        "--user",
        args.user,
        "--password",
        args.password,
        "--cmd",
        command,
        "--read-sec",
        str(read_sec),
        "--max-abs-d",
        str(args.max_abs_d_cm),
        "--max-gear",
        str(args.max_gear),
    ]
    if allow_motion:
        cmd.append("--allow-motion")
    started = now_iso()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(read_sec + timeout_pad_sec, 20),
    )
    ended = now_iso()
    text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    events = parse_stm32_text(text)
    return Stm32Result(
        command=command,
        returncode=proc.returncode,
        started_at=started,
        ended_at=ended,
        stdout=proc.stdout,
        stderr=proc.stderr,
        events=events,
    )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def compact_stat(stat: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stat:
        return None
    keys = ("seq", "mode", "run", "dir", "spd", "ang", "yaw", "x", "y", "d", "vel", "drop", "imu", "raw")
    return {k: stat.get(k) for k in keys if k in stat}


def stat_numeric(stat: dict[str, Any] | None, key: str) -> float | None:
    if not stat:
        return None
    return as_float(stat.get(key))


def compute_static_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    stats = [s.get("stat") or {} for s in samples if s.get("stat")]
    yaws = [stat_numeric(st, "yaw") for st in stats]
    yaws = [v for v in yaws if v is not None]
    ds = [stat_numeric(st, "d") for st in stats]
    ds = [v for v in ds if v is not None]
    xs = [stat_numeric(st, "x") for st in stats]
    xs = [v for v in xs if v is not None]
    ys = [stat_numeric(st, "y") for st in stats]
    ys = [v for v in ys if v is not None]
    vels = [abs(stat_numeric(st, "vel") or 0.0) for st in stats if stat_numeric(st, "vel") is not None]
    drops = sorted({str(st.get("drop")) for st in stats if st.get("drop") is not None})
    imus = sorted({str(st.get("imu")) for st in stats if st.get("imu") is not None})
    t0 = as_float(samples[0].get("t_mono")) if samples else None
    t1 = as_float(samples[-1].get("t_mono")) if samples else None
    duration = max((t1 - t0), 0.0) if t0 is not None and t1 is not None else 0.0
    yaw_drift = wrap_degrees(yaws[-1] - yaws[0]) if len(yaws) >= 2 else None
    yaw_rel = [wrap_degrees(v - yaws[0]) for v in yaws] if yaws else []
    d_delta = (ds[-1] - ds[0]) if len(ds) >= 2 else None
    x_delta = (xs[-1] - xs[0]) if len(xs) >= 2 else None
    y_delta = (ys[-1] - ys[0]) if len(ys) >= 2 else None
    drift_per_min = yaw_drift / (duration / 60.0) if yaw_drift is not None and duration > 0 else None
    out = {
        "sample_count": len(samples),
        "valid_stat_count": len(stats),
        "valid_yaw_count": len(yaws),
        "duration_sec": round(duration, 3),
        "yaw_start_deg": yaws[0] if yaws else None,
        "yaw_end_deg": yaws[-1] if yaws else None,
        "yaw_drift_deg": round(yaw_drift, 6) if yaw_drift is not None else None,
        "yaw_drift_deg_per_min": round(drift_per_min, 6) if drift_per_min is not None else None,
        "yaw_peak_to_peak_deg": round((max(yaw_rel) - min(yaw_rel)), 6) if yaw_rel else None,
        "yaw_std_deg": round(statistics.pstdev(yaw_rel), 6) if len(yaw_rel) >= 2 else None,
        "odom_d_delta_cm": round(d_delta, 6) if d_delta is not None else None,
        "odom_x_delta_cm": round(x_delta, 6) if x_delta is not None else None,
        "odom_y_delta_cm": round(y_delta, 6) if y_delta is not None else None,
        "vel_abs_max": max(vels) if vels else None,
        "drop_values": drops,
        "imu_status_values": imus,
    }
    yaw_p2p = out["yaw_peak_to_peak_deg"]
    vel_max = out["vel_abs_max"]
    out["verdict"] = (
        "PASS"
        if out["valid_yaw_count"] >= 3
        and out["yaw_drift_deg_per_min"] is not None
        and abs(out["yaw_drift_deg_per_min"]) <= 0.2
        and yaw_p2p is not None
        and yaw_p2p <= 0.5
        and vel_max is not None
        and vel_max <= args_global_static_vel_max
        and imus == ["OK"]
        and all(v in {"0", "0.0"} for v in drops)
        else "CHECK"
    )
    return out


# Kept as a module-level constant so compute_static_summary stays argparse-free.
args_global_static_vel_max = 0.1


def run_static_baseline(args: argparse.Namespace, outdir: Path, raw_path: Path) -> dict[str, Any]:
    global args_global_static_vel_max
    args_global_static_vel_max = args.static_vel_max
    print(f"[static] sampling STAT for {args.static_sec:.1f}s ...", flush=True)
    samples: list[dict[str, Any]] = []
    end_at = time.monotonic() + args.static_sec
    i = 0
    while True:
        now = time.monotonic()
        if i > 0 and now >= end_at:
            break
        res = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
        stat = compact_stat(res.latest_stat())
        item = {
            "event": "static_stat",
            "index": i,
            "time": now_iso(),
            "t_mono": time.monotonic(),
            "stat": stat,
            "stm32": res.to_json(),
        }
        samples.append(item)
        append_jsonl(raw_path, item)
        if res.returncode != 0:
            print(f"[static] WARN STAT rc={res.returncode}", flush=True)
        i += 1
        if time.monotonic() >= end_at:
            break
        time.sleep(max(args.static_interval_sec, 0.0))
    summary = compute_static_summary(samples)
    (outdir / "static_baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def sensor_consistency(delta_yaw: float | None, delta_x: float | None, progress: float | None) -> dict[str, Any]:
    if delta_yaw is None or delta_x is None or progress is None:
        return {"verdict": "CHECK", "reason": "missing_delta"}
    if progress < 0.5:
        return {"verdict": "FAIL", "reason": "no_progress"}
    sy = sign(delta_yaw, eps=0.25)
    sx = sign(delta_x, eps=0.15)
    if sy == 0 or sx == 0:
        return {"verdict": "PASS", "reason": "near_straight_or_small_lateral"}
    if sy == sx:
        return {"verdict": "PASS", "reason": "yaw_and_odom_x_same_turn_sign"}
    return {"verdict": "FAIL", "reason": "yaw_and_odom_x_opposite_sign"}


def run_servo_sweep(args: argparse.Namespace, outdir: Path, raw_path: Path) -> list[dict[str, Any]]:
    if not args.allow_risk:
        raise SystemExit("--run-sweep requires --allow-risk after operator approval")
    stes = [int(v) for v in parse_csv_numbers(args.stes, int)]
    rows: list[dict[str, Any]] = []
    fused = {"x_cm": 0.0, "y_cm": 0.0, "heading_deg": 0.0}
    print(f"[sweep] stes={stes} repeats={args.repeats} command D={-abs(args.step_cm):.1f}cm", flush=True)
    for rep in range(args.repeats):
        for ste in stes:
            command = f"ARC D={-abs(args.step_cm):.1f} STE={ste} V={args.gear}"
            print(f"[sweep] rep={rep + 1}/{args.repeats} ste={ste} command={command}", flush=True)
            before_res = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
            before = before_res.latest_stat()
            append_jsonl(raw_path, {
                "event": "sweep_stat_before",
                "time": now_iso(),
                "repeat": rep,
                "ste": ste,
                "command": command,
                "stat": compact_stat(before),
                "stm32": before_res.to_json(),
            })
            fused_before = dict(fused)
            motion_res = run_stm32(args, command, allow_motion=True, read_sec=args.motion_read_sec)
            append_jsonl(raw_path, {
                "event": "sweep_motion",
                "time": now_iso(),
                "repeat": rep,
                "ste": ste,
                "command": command,
                "stm32": motion_res.to_json(),
            })
            stop_res = run_stm32(args, "STOP", read_sec=args.stop_read_sec)
            append_jsonl(raw_path, {
                "event": "sweep_stop",
                "time": now_iso(),
                "repeat": rep,
                "ste": ste,
                "command": "STOP",
                "stm32": stop_res.to_json(),
            })
            time.sleep(max(args.settle_sec, 0.0))
            after_res = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
            after = after_res.latest_stat()
            append_jsonl(raw_path, {
                "event": "sweep_stat_after",
                "time": now_iso(),
                "repeat": rep,
                "ste": ste,
                "command": command,
                "stat": compact_stat(after),
                "stm32": after_res.to_json(),
            })

            yaw0 = stat_numeric(before, "yaw")
            yaw1 = stat_numeric(after, "yaw")
            x0 = stat_numeric(before, "x")
            x1 = stat_numeric(after, "x")
            d0 = stat_numeric(before, "d")
            d1 = stat_numeric(after, "d")
            y0 = stat_numeric(before, "y")
            y1 = stat_numeric(after, "y")
            delta_yaw = wrap_degrees(yaw1 - yaw0) if yaw0 is not None and yaw1 is not None else None
            delta_x = x1 - x0 if x0 is not None and x1 is not None else None
            delta_y_odom = y1 - y0 if y0 is not None and y1 is not None else None
            delta_d = d1 - d0 if d0 is not None and d1 is not None else None
            progress = abs(delta_d) if delta_d is not None else None
            yaw_per_cm = delta_yaw / progress if delta_yaw is not None and progress and progress > 1e-6 else None
            consistency = sensor_consistency(delta_yaw, delta_x, progress)
            fused["x_cm"] += delta_x or 0.0
            fused["y_cm"] += progress or 0.0
            fused["heading_deg"] = wrap_degrees(fused["heading_deg"] + (delta_yaw or 0.0))
            stop_reason = "done" if motion_res.latest_done() else ("motion_error" if motion_res.returncode != 0 or motion_res.latest_err() else "no_done_seen")
            row = {
                "event": "servo_sweep_step",
                "time": now_iso(),
                "repeat": rep + 1,
                "command": command,
                "ste": ste,
                "stat_before": compact_stat(before),
                "stat_after": compact_stat(after),
                "delta_yaw_deg": delta_yaw,
                "odom_progress_cm": progress,
                "odom_lateral_cm": delta_x,
                "odom_y_delta_cm": delta_y_odom,
                "yaw_per_cm": yaw_per_cm,
                "fused_pose_before": fused_before,
                "fused_pose_after": dict(fused),
                "sensor_consistency_verdict": consistency,
                "motion_returncode": motion_res.returncode,
                "stop_returncode": stop_res.returncode,
                "stop_reason": stop_reason,
            }
            rows.append(row)
            append_jsonl(raw_path, row)
            print(
                "[sweep] result ste=%s dyaw=%s progress=%s x=%s ypc=%s verdict=%s"
                % (
                    ste,
                    None if delta_yaw is None else round(delta_yaw, 3),
                    None if progress is None else round(progress, 3),
                    None if delta_x is None else round(delta_x, 3),
                    None if yaw_per_cm is None else round(yaw_per_cm, 4),
                    consistency["verdict"],
                ),
                flush=True,
            )
            if args.pause_between_steps_sec > 0:
                time.sleep(args.pause_between_steps_sec)
    return rows


def summarize_sweep(rows: list[dict[str, Any]], outdir: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    by_ste: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_ste.setdefault(int(row["ste"]), []).append(row)
    summary_rows: list[dict[str, Any]] = []
    for ste, items in sorted(by_ste.items()):
        yaw_per_cm_vals = [as_float(r.get("yaw_per_cm")) for r in items]
        yaw_per_cm_vals = [v for v in yaw_per_cm_vals if v is not None]
        delta_yaws = [as_float(r.get("delta_yaw_deg")) for r in items]
        delta_yaws = [v for v in delta_yaws if v is not None]
        laterals = [as_float(r.get("odom_lateral_cm")) for r in items]
        laterals = [v for v in laterals if v is not None]
        progresses = [as_float(r.get("odom_progress_cm")) for r in items]
        progresses = [v for v in progresses if v is not None]
        fails = [r for r in items if (r.get("sensor_consistency_verdict") or {}).get("verdict") == "FAIL"]
        mean_yaw_per_cm = statistics.mean(yaw_per_cm_vals) if yaw_per_cm_vals else None
        mean_delta_yaw = statistics.mean(delta_yaws) if delta_yaws else None
        std_delta_yaw = statistics.pstdev(delta_yaws) if len(delta_yaws) >= 2 else 0.0 if delta_yaws else None
        mean_abs_lateral = statistics.mean([abs(v) for v in laterals]) if laterals else None
        mean_progress = statistics.mean(progresses) if progresses else None
        pass_criteria = (
            mean_yaw_per_cm is not None
            and abs(mean_yaw_per_cm) <= args.accept_yaw_per_cm
            and mean_delta_yaw is not None
            and abs(mean_delta_yaw) <= args.accept_step_yaw_deg
            and mean_abs_lateral is not None
            and mean_abs_lateral <= args.accept_lateral_cm
            and std_delta_yaw is not None
            and std_delta_yaw <= args.accept_yaw_std_deg
            and mean_progress is not None
            and mean_progress >= args.accept_min_progress_cm
            and not fails
        )
        score = None
        if mean_yaw_per_cm is not None and mean_abs_lateral is not None and std_delta_yaw is not None:
            score = abs(mean_yaw_per_cm) * 100.0 + mean_abs_lateral * 10.0 + std_delta_yaw
        summary_rows.append({
            "ste": ste,
            "n": len(items),
            "mean_yaw_per_cm": mean_yaw_per_cm,
            "mean_delta_yaw_deg": mean_delta_yaw,
            "std_delta_yaw_deg": std_delta_yaw,
            "mean_abs_lateral_cm": mean_abs_lateral,
            "mean_progress_cm": mean_progress,
            "consistency_fail_count": len(fails),
            "score": score,
            "pass_criteria": pass_criteria,
        })

    csv_path = outdir / "servo_sweep_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "ste",
            "n",
            "mean_yaw_per_cm",
            "mean_delta_yaw_deg",
            "std_delta_yaw_deg",
            "mean_abs_lateral_cm",
            "mean_progress_cm",
            "consistency_fail_count",
            "score",
            "pass_criteria",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in summary_rows:
            w.writerow(r)

    valid = [r for r in summary_rows if r["score"] is not None]
    # A no-progress row can have perfect-looking yaw/lateral only because the
    # chassis did not actually move.  Keep it as a diagnostic candidate, but do
    # not publish it as STE_STRAIGHT.
    eligible = [
        r for r in valid
        if r.get("mean_progress_cm") is not None
        and r["mean_progress_cm"] >= args.accept_min_progress_cm
        and r.get("consistency_fail_count", 999) == 0
    ]
    best_candidate = min(valid, key=lambda r: (abs(r["mean_yaw_per_cm"]), r["mean_abs_lateral_cm"], r["std_delta_yaw_deg"])) if valid else None
    recommended_row = min(
        eligible,
        key=lambda r: (abs(r["mean_yaw_per_cm"]), r["mean_abs_lateral_cm"], r["std_delta_yaw_deg"]),
    ) if eligible else None
    recommended = {
        "schema": "recommended_ste_straight.v1",
        "generated_at": now_iso(),
        "ste_straight": recommended_row["ste"] if recommended_row else None,
        "status": "PASS" if recommended_row and recommended_row["pass_criteria"] else "CHECK",
        "recommended_row": recommended_row,
        "best_candidate_including_no_progress": best_candidate,
        "criteria": {
            "accept_yaw_per_cm": args.accept_yaw_per_cm,
            "accept_step_yaw_deg": args.accept_step_yaw_deg,
            "accept_lateral_cm": args.accept_lateral_cm,
            "accept_yaw_std_deg": args.accept_yaw_std_deg,
            "accept_min_progress_cm": args.accept_min_progress_cm,
        },
        "all_rows": summary_rows,
    }
    (outdir / "recommended_ste_straight.json").write_text(
        json.dumps(recommended, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fusion = build_fusion_residuals(rows, summary_rows, recommended, args)
    (outdir / "fusion_residuals.json").write_text(
        json.dumps(fusion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary_rows, recommended, fusion


def build_fusion_residuals(
    rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    recommended: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    ste_straight = recommended.get("ste_straight")
    stes = sorted([int(r["ste"]) for r in summary_rows])
    lower = max([s for s in stes if ste_straight is not None and s < ste_straight], default=None)
    upper = min([s for s in stes if ste_straight is not None and s > ste_straight], default=None)

    def direct_rule(heading: float, lateral: float) -> int | None:
        if ste_straight is None:
            return None
        if abs(heading) < 2.0 and abs(lateral) < 1.5:
            return int(ste_straight)
        if heading > 0:
            return lower if lower is not None else int(ste_straight)
        if heading < 0:
            return upper if upper is not None else int(ste_straight)
        return int(ste_straight)

    checks = []
    for heading in [-8, -4, -1, 0, 1, 4, 8]:
        for lateral in [-2, 0, 2]:
            checks.append({"heading_deg": heading, "lateral_cm": lateral, "recommended_ste": direct_rule(heading, lateral)})

    fail_rows = [r for r in rows if (r.get("sensor_consistency_verdict") or {}).get("verdict") == "FAIL"]
    no_progress = [r for r in rows if (as_float(r.get("odom_progress_cm"), 0.0) or 0.0) < args.accept_min_progress_cm]
    return {
        "schema": "imu_odom_fusion_residuals.v1",
        "generated_at": now_iso(),
        "step_count": len(rows),
        "sensor_consistency_fail_count": len(fail_rows),
        "no_progress_count": len(no_progress),
        "ste_straight": ste_straight,
        "light_left_ste": lower,
        "light_right_ste": upper,
        "direct_rule_shadow_checks": checks,
        "verdict": "PASS" if rows and not fail_rows and not no_progress and ste_straight is not None else "CHECK",
    }


def write_report(
    outdir: Path,
    args: argparse.Namespace,
    static_summary: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
    fusion: dict[str, Any] | None,
) -> None:
    lines: list[str] = []
    lines.append("# IMU + 里程计双传感器舵机直导验证报告")
    lines.append("")
    lines.append(f"- 生成时间：`{now_iso()}`")
    lines.append(f"- 输出目录：`{outdir}`")
    lines.append(f"- 运动扫描：`{'已执行' if rows else '未执行'}`")
    lines.append("")
    lines.append("## 阶段 A：传感器健康基线")
    if static_summary:
        lines.append(f"- verdict: `{static_summary.get('verdict')}`")
        lines.append(f"- duration: `{static_summary.get('duration_sec')}` s, samples: `{static_summary.get('sample_count')}`")
        lines.append(f"- yaw drift: `{static_summary.get('yaw_drift_deg')}` deg, `{static_summary.get('yaw_drift_deg_per_min')}` deg/min")
        lines.append(f"- yaw p2p/std: `{static_summary.get('yaw_peak_to_peak_deg')}` / `{static_summary.get('yaw_std_deg')}` deg")
        lines.append(f"- odom D/X/Y delta: `{static_summary.get('odom_d_delta_cm')}` / `{static_summary.get('odom_x_delta_cm')}` / `{static_summary.get('odom_y_delta_cm')}` cm")
        lines.append(f"- VEL max: `{static_summary.get('vel_abs_max')}`, DROP: `{static_summary.get('drop_values')}`, IMU: `{static_summary.get('imu_status_values')}`")
    else:
        lines.append("- 未运行静止基线。")
    lines.append("")
    lines.append("## 阶段 B/C：舵机直行点扫描与双传感器一致性")
    if summary_rows:
        lines.append("| STE | n | mean yaw/cm | mean yaw | yaw std | mean |X| | progress | fail | pass |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for r in summary_rows:
            def fmt(v: Any) -> str:
                if v is None:
                    return ""
                try:
                    return f"{float(v):.4f}"
                except (TypeError, ValueError):
                    return str(v)
            lines.append(
                f"| {r['ste']} | {r['n']} | {fmt(r['mean_yaw_per_cm'])} | "
                f"{fmt(r['mean_delta_yaw_deg'])} | {fmt(r['std_delta_yaw_deg'])} | "
                f"{fmt(r['mean_abs_lateral_cm'])} | {fmt(r['mean_progress_cm'])} | "
                f"{r['consistency_fail_count']} | `{r['pass_criteria']}` |"
            )
    else:
        lines.append("- 未运行舵机扫描。")
    lines.append("")
    lines.append("## 阶段 D：舵机直导 shadow")
    if recommended:
        lines.append(f"- 推荐 `STE_STRAIGHT`: `{recommended.get('ste_straight')}`")
        lines.append(f"- 推荐状态：`{recommended.get('status')}`")
    if fusion:
        lines.append(f"- 融合一致性：`{fusion.get('verdict')}`")
        lines.append(f"- 轻左/轻右修正：`{fusion.get('light_left_ste')}` / `{fusion.get('light_right_ste')}`")
    lines.append("")
    lines.append("## 结论")
    if recommended and recommended.get("ste_straight") is not None:
        lines.append(f"- 本轮推荐直行舵角为 `STE={recommended.get('ste_straight')}`。")
        lines.append("- 若推荐状态为 `CHECK`，表示可作为候选但未完全满足严格验收，需要重复或放宽阈值后再用于主线。")
    else:
        lines.append("- 暂无可推荐直行舵角。")
    lines.append("- 本工具未修改任何板端配置；若要接入主倒车链路，需另行审批。")
    (outdir / "imu_odom_servo_direct_validation_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.137.2")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="ebaina")
    ap.add_argument("--out-root", default=str(ROOT / "artifacts" / "imu_odom_servo_direct_validation"))
    ap.add_argument("--static-sec", type=float, default=60.0)
    ap.add_argument("--static-interval-sec", type=float, default=0.2)
    ap.add_argument("--static-vel-max", type=float, default=0.1)
    ap.add_argument("--skip-static", action="store_true")
    ap.add_argument("--run-sweep", action="store_true", help="Actually run ARC sweep; requires --allow-risk.")
    ap.add_argument("--allow-risk", action="store_true", help="Required for real motion sweep after operator approval.")
    ap.add_argument("--stes", default=DEFAULT_STES)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--step-cm", type=float, default=4.0)
    ap.add_argument("--gear", type=int, default=1)
    ap.add_argument("--settle-sec", type=float, default=0.2)
    ap.add_argument("--pause-between-steps-sec", type=float, default=0.0)
    ap.add_argument("--stat-read-sec", type=int, default=1)
    ap.add_argument("--motion-read-sec", type=int, default=8)
    ap.add_argument("--stop-read-sec", type=int, default=1)
    ap.add_argument("--max-abs-d-cm", type=float, default=8.0)
    ap.add_argument("--max-gear", type=int, default=1)
    ap.add_argument("--accept-yaw-per-cm", type=float, default=0.15)
    ap.add_argument("--accept-step-yaw-deg", type=float, default=0.6)
    ap.add_argument("--accept-lateral-cm", type=float, default=0.5)
    ap.add_argument("--accept-yaw-std-deg", type=float, default=0.4)
    ap.add_argument("--accept-min-progress-cm", type=float, default=0.5)
    args = ap.parse_args()

    outdir = Path(args.out_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    raw_path = outdir / "raw_stat_samples.jsonl"
    (outdir / "run_config.json").write_text(
        json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.run_sweep and not args.allow_risk:
        print("REFUSE: --run-sweep requires --allow-risk after explicit operator approval.", file=sys.stderr)
        print("No motion was sent.", file=sys.stderr)
        return 4

    static_summary = None
    if not args.skip_static and args.static_sec > 0:
        static_summary = run_static_baseline(args, outdir, raw_path)

    rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    recommended = None
    fusion = None
    if args.run_sweep:
        rows = run_servo_sweep(args, outdir, raw_path)
        (outdir / "servo_sweep_steps.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary_rows, recommended, fusion = summarize_sweep(rows, outdir, args)
    else:
        # Still create required placeholder artifacts for static-only runs.
        (outdir / "servo_sweep_summary.csv").write_text(
            "ste,n,mean_yaw_per_cm,mean_delta_yaw_deg,std_delta_yaw_deg,mean_abs_lateral_cm,mean_progress_cm,consistency_fail_count,score,pass_criteria\n",
            encoding="utf-8",
        )
        recommended = {
            "schema": "recommended_ste_straight.v1",
            "generated_at": now_iso(),
            "ste_straight": None,
            "status": "NOT_RUN",
            "reason": "run with --run-sweep --allow-risk to execute servo scan",
        }
        fusion = {
            "schema": "imu_odom_fusion_residuals.v1",
            "generated_at": now_iso(),
            "verdict": "NOT_RUN",
            "reason": "servo sweep not executed",
        }
        (outdir / "recommended_ste_straight.json").write_text(
            json.dumps(recommended, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (outdir / "fusion_residuals.json").write_text(
            json.dumps(fusion, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    write_report(outdir, args, static_summary, rows, summary_rows, recommended, fusion)
    print("OUTDIR", outdir)
    print("RAW", raw_path)
    print("REPORT", outdir / "imu_odom_servo_direct_validation_report.md")
    if static_summary:
        print("STATIC_VERDICT", static_summary.get("verdict"))
    if recommended:
        print("STE_STRAIGHT", recommended.get("ste_straight"), "STATUS", recommended.get("status"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
