#!/usr/bin/env python3
"""Isolated chassis action-set validation for the DIY parking car.

This tool validates a small ARC action set with STM32 IMU yaw + odometry.
It does not write project or board configuration.  Real motion is only sent
when both ``--run`` and ``--allow-risk`` are present; otherwise it prints the
planned batches and creates placeholder artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
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
DEFAULT_BATCH_SPEC = (
    "baseline:ARC D=-6.0 STE=100 V=1x3,"
    "baseline:ARC D=-4.0 STE=100 V=1x3,"
    "light:ARC D=-6.0 STE=96 V=1x2,"
    "light:ARC D=-6.0 STE=98 V=1x2,"
    "light:ARC D=-6.0 STE=102 V=1x2,"
    "light:ARC D=-6.0 STE=105 V=1x2,"
    "strong:ARC D=-6.0 STE=90 V=1x2,"
    "strong:ARC D=-6.0 STE=94 V=1x2,"
    "strong:ARC D=-6.0 STE=110 V=1x2,"
    "strong:ARC D=-6.0 STE=120 V=1x2"
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def sign(value: float | None, eps: float = 1e-6) -> int:
    if value is None:
        return 0
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def parse_command(command: str) -> dict[str, Any]:
    m = re.fullmatch(r"ARC D=([+-]?\d+(?:\.\d+)?) STE=(\d+) V=(\d+)", command.strip())
    if not m:
        raise ValueError(f"only ARC commands are supported, got: {command!r}")
    return {"d": float(m.group(1)), "ste": int(m.group(2)), "v": int(m.group(3))}


def parse_batch_spec(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in str(text or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        if ":" not in raw:
            raise ValueError(f"batch item must look like name:ARC ...xN, got {raw!r}")
        batch, rest = raw.split(":", 1)
        batch = batch.strip()
        m = re.fullmatch(r"(.+?)x(\d+)", rest.strip())
        if not m:
            raise ValueError(f"batch command must end with x<repeat>, got {rest!r}")
        command = m.group(1).strip()
        repeat = int(m.group(2))
        parsed = parse_command(command)
        role = action_role(batch, parsed["ste"])
        out.append({
            "batch": batch,
            "role": role,
            "command": command,
            "repeat": repeat,
            "ste": parsed["ste"],
            "signed_distance_cm": parsed["d"],
            "distance_cm": abs(parsed["d"]),
            "gear": parsed["v"],
        })
    return out


def action_role(batch: str, ste: int) -> str:
    if ste == 100:
        return "straight"
    if "light" in batch:
        return "left_light" if ste < 100 else "right_light"
    if "strong" in batch:
        return "left_strong" if ste < 100 else "right_strong"
    return "left" if ste < 100 else "right"


@dataclass
class Stm32Result:
    command: str
    returncode: int
    started_at: str
    ended_at: str
    stdout: str
    stderr: str
    events: list[dict[str, Any]]

    def latest(self, typ: str) -> dict[str, Any] | None:
        for ev in reversed(self.events):
            if ev.get("type") == typ:
                return ev
        return None

    def latest_stat(self) -> dict[str, Any] | None:
        return self.latest("stat")

    def latest_done(self) -> dict[str, Any] | None:
        return self.latest("done")

    def latest_err(self) -> dict[str, Any] | None:
        return self.latest("err")

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
        "--min-ste",
        str(args.min_ste),
        "--max-ste",
        str(args.max_ste),
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
        timeout=max(read_sec + 30, 20),
    )
    ended = now_iso()
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return Stm32Result(
        command=command,
        returncode=proc.returncode,
        started_at=started,
        ended_at=ended,
        stdout=proc.stdout,
        stderr=proc.stderr,
        events=parse_stm32_text(combined),
    )


def stat_value(stat: dict[str, Any] | None, key: str) -> float | None:
    if not stat:
        return None
    return as_float(stat.get(key))


def compact_event(ev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ev:
        return None
    keys = ("type", "seq", "cmd", "mode", "run", "dir", "spd", "ang", "yaw", "x", "y", "d", "vel", "drop", "imu", "raw")
    return {k: ev.get(k) for k in keys if k in ev}


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def compute_sample(
    *,
    batch: str,
    role: str,
    repeat_index: int,
    command: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    motion: Stm32Result,
    stop: Stm32Result,
    args: argparse.Namespace,
) -> dict[str, Any]:
    parsed = parse_command(command)
    yaw0 = stat_value(before, "yaw")
    yaw1 = stat_value(after, "yaw")
    x0 = stat_value(before, "x")
    x1 = stat_value(after, "x")
    y0 = stat_value(before, "y")
    y1 = stat_value(after, "y")
    d0 = stat_value(before, "d")
    d1 = stat_value(after, "d")
    delta_yaw = wrap_degrees(yaw1 - yaw0) if yaw0 is not None and yaw1 is not None else None
    delta_x = x1 - x0 if x0 is not None and x1 is not None else None
    delta_y = y1 - y0 if y0 is not None and y1 is not None else None
    stat_delta_d = d1 - d0 if d0 is not None and d1 is not None else None
    done = motion.latest_done()
    done_d = as_float(done.get("d")) if done else None
    # For isolated action validation, DONE.D is the controller's completed
    # motion distance for this command.  STAT.D can be reset/accumulated with
    # ambiguous semantics across repeated short actions, so keep it only as an
    # auxiliary diagnostic and use DONE.D directly for progress.
    progress = abs(done_d) if done_d is not None else None
    deg_per_cm = delta_yaw / progress if delta_yaw is not None and progress and progress > 1e-6 else None
    err = motion.latest_err()
    imu_ok = bool(after and after.get("imu") == "OK")
    drop_ok = bool(after and str(after.get("drop")) in {"0", "0.0"})
    vel = stat_value(after, "vel")
    vel_ok = bool(vel is not None and abs(vel) <= args.accept_vel_abs_max)
    progress_ok = bool(progress is not None and progress >= args.accept_min_progress_cm)
    direction_ok = direction_verdict(role, delta_yaw, args, parsed["d"])
    yaw_ok = yaw_verdict(role, delta_yaw, args)
    hard_fail_reasons = []
    if motion.returncode != 0:
        hard_fail_reasons.append("motion_returncode")
    if err:
        hard_fail_reasons.append("motion_err")
    if stop.returncode != 0:
        hard_fail_reasons.append("stop_returncode")
    if not imu_ok:
        hard_fail_reasons.append("imu_not_ok")
    if not drop_ok:
        hard_fail_reasons.append("drop_nonzero")
    if not vel_ok:
        hard_fail_reasons.append("vel_not_zero")
    if not progress_ok:
        hard_fail_reasons.append("no_progress")
    if direction_ok is False:
        hard_fail_reasons.append("wrong_yaw_direction")
    if yaw_ok is False:
        hard_fail_reasons.append("yaw_out_of_range")
    verdict = "PASS" if not hard_fail_reasons else "FAIL"
    return {
        "event": "action_set_sample",
        "time": now_iso(),
        "batch": batch,
        "role": role,
        "repeat_index": repeat_index,
        "command": command,
        "ste": parsed["ste"],
        "signed_distance_cm": parsed["d"],
        "distance_cm": abs(parsed["d"]),
        "stat_before": compact_event(before),
        "stat_after": compact_event(after),
        "delta_yaw_deg": delta_yaw,
        "odom_progress_cm": progress,
        "progress_source": "done_d",
        "done_progress_cm": progress,
        "stat_d_delta_cm": stat_delta_d,
        "odom_x_delta_cm": delta_x,
        "odom_y_delta_cm": delta_y,
        "actual_deg_per_cm": deg_per_cm,
        "done_metrics": compact_event(done),
        "imu_ok": imu_ok,
        "drop_ok": drop_ok,
        "vel_ok": vel_ok,
        "progress_ok": progress_ok,
        "direction_ok": direction_ok,
        "yaw_ok": yaw_ok,
        "verdict": verdict,
        "fail_reasons": hard_fail_reasons,
        "motion": motion.to_json(),
        "stop": stop.to_json(),
    }


def direction_verdict(role: str, delta_yaw: float | None, args: argparse.Namespace,
                      signed_distance_cm: float | None = None) -> bool | None:
    if delta_yaw is None:
        return None
    mode = str(getattr(args, "direction_check_mode", "reverse") or "reverse").strip().lower()
    if mode == "none":
        return True
    if mode == "auto":
        mode = "forward" if signed_distance_cm is not None and float(signed_distance_cm) > 0.0 else "reverse"
    if role == "straight":
        return True
    # Small yaw is inconclusive but not direction-wrong.
    if abs(delta_yaw) < args.direction_deadband_deg:
        return True
    if role.startswith("left"):
        return delta_yaw > 0.0 if mode == "forward" else delta_yaw < 0.0
    if role.startswith("right"):
        return delta_yaw < 0.0 if mode == "forward" else delta_yaw > 0.0
    return True


def yaw_verdict(role: str, delta_yaw: float | None, args: argparse.Namespace) -> bool | None:
    if delta_yaw is None:
        return None
    ay = abs(delta_yaw)
    if role == "straight":
        return ay <= args.accept_straight_abs_yaw_deg
    if "light" in role:
        return ay <= args.accept_light_abs_yaw_deg
    if "strong" in role:
        return ay <= args.accept_strong_abs_yaw_deg
    return True


def run_action(args: argparse.Namespace, item: dict[str, Any], repeat_index: int, raw_path: Path) -> dict[str, Any]:
    command = item["command"]
    before_res = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
    before = before_res.latest_stat()
    append_jsonl(raw_path, {"event": "stat_before", "time": now_iso(), "command": command, "stm32": before_res.to_json()})
    motion_res = run_stm32(args, command, allow_motion=True, read_sec=args.motion_read_sec)
    append_jsonl(raw_path, {"event": "motion", "time": now_iso(), "command": command, "stm32": motion_res.to_json()})
    stop_res = run_stm32(args, "STOP", read_sec=args.stop_read_sec)
    append_jsonl(raw_path, {"event": "stop", "time": now_iso(), "command": "STOP", "stm32": stop_res.to_json()})
    time.sleep(max(0.0, args.settle_sec))
    after_res = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
    after = after_res.latest_stat()
    append_jsonl(raw_path, {"event": "stat_after", "time": now_iso(), "command": command, "stm32": after_res.to_json()})
    sample = compute_sample(
        batch=item["batch"],
        role=item["role"],
        repeat_index=repeat_index,
        command=command,
        before=before,
        after=after,
        motion=motion_res,
        stop=stop_res,
        args=args,
    )
    append_jsonl(raw_path, sample)
    return sample


def summarize(samples: list[dict[str, Any]], items: list[dict[str, Any]], outdir: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        groups.setdefault(s["command"], []).append(s)
    rows: list[dict[str, Any]] = []
    for item in items:
        command = item["command"]
        ss = groups.get(command, [])
        yaws = [as_float(s.get("delta_yaw_deg")) for s in ss]
        yaws = [v for v in yaws if v is not None]
        progress = [as_float(s.get("odom_progress_cm")) for s in ss]
        progress = [v for v in progress if v is not None]
        lateral = [as_float(s.get("odom_x_delta_cm")) for s in ss]
        lateral = [v for v in lateral if v is not None]
        deg_per_cm = [as_float(s.get("actual_deg_per_cm")) for s in ss]
        deg_per_cm = [v for v in deg_per_cm if v is not None]
        pass_count = sum(1 for s in ss if s.get("verdict") == "PASS")
        fail_reasons = sorted({reason for s in ss for reason in (s.get("fail_reasons") or [])})
        row = {
            "batch": item["batch"],
            "role": item["role"],
            "command": command,
            "ste": item["ste"],
            "signed_distance_cm": item.get("signed_distance_cm"),
            "distance_cm": item["distance_cm"],
            "repeat_expected": item["repeat"],
            "sample_count": len(ss),
            "pass_count": pass_count,
            "fail_count": len(ss) - pass_count,
            "mean_delta_yaw_deg": mean_or_none(yaws),
            "std_delta_yaw_deg": std_or_none(yaws),
            "mean_abs_delta_yaw_deg": mean_or_none([abs(v) for v in yaws]),
            "mean_progress_cm": mean_or_none(progress),
            "mean_abs_lateral_cm": mean_or_none([abs(v) for v in lateral]),
            "mean_actual_deg_per_cm": mean_or_none(deg_per_cm),
            "fail_reasons": ";".join(fail_reasons),
            "accepted": len(ss) == item["repeat"] and pass_count == len(ss) and len(ss) > 0,
        }
        rows.append(row)
    csv_path = outdir / "action_set_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "batch", "role", "command", "ste", "signed_distance_cm", "distance_cm", "repeat_expected",
            "sample_count", "pass_count", "fail_count", "mean_delta_yaw_deg",
            "std_delta_yaw_deg", "mean_abs_delta_yaw_deg", "mean_progress_cm",
            "mean_abs_lateral_cm", "mean_actual_deg_per_cm", "fail_reasons",
            "accepted",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    recommended = build_recommended(rows, args)
    (outdir / "recommended_runtime_action_set.json").write_text(
        json.dumps(recommended, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows, recommended


def mean_or_none(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def std_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.pstdev(values), 6) if len(values) >= 2 else 0.0


def build_recommended(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    accepted = [r for r in rows if r.get("accepted")]
    by_role: dict[str, list[dict[str, Any]]] = {}
    for r in accepted:
        by_role.setdefault(str(r["role"]), []).append(r)

    def best(role: str) -> dict[str, Any] | None:
        vals = by_role.get(role, [])
        if not vals:
            return None
        if role == "straight":
            return min(vals, key=lambda r: (r.get("mean_abs_delta_yaw_deg") or 999, r.get("std_delta_yaw_deg") or 999))
        return min(vals, key=lambda r: (abs(r.get("mean_actual_deg_per_cm") or 999), r.get("std_delta_yaw_deg") or 999))

    payload = {
        "schema": "recommended_runtime_action_set.v1",
        "generated_at": now_iso(),
        "policy": "STE=100 is engineering straight baseline; validation does not overwrite chassis config.",
        "accepted_commands": [r["command"] for r in accepted],
        "straight_baseline": best("straight"),
        "left_light": best("left_light"),
        "right_light": best("right_light"),
        "left_strong": best("left_strong"),
        "right_strong": best("right_strong"),
        "all_summary_rows": rows,
    }
    incomplete = any(int(r.get("sample_count") or 0) < int(r.get("repeat_expected") or 0) for r in rows)
    any_failed = any(int(r.get("fail_count") or 0) > 0 for r in rows)
    payload["overall"] = "PASS" if payload["straight_baseline"] and not incomplete and not any_failed else "CHECK"
    return payload


def build_forward_terminal_shuffle_kinematics(rows: list[dict[str, Any]], outdir: Path) -> dict[str, Any]:
    forward_rows = []
    for r in rows:
        signed_d = as_float(r.get("signed_distance_cm"))
        mean_deg = as_float(r.get("mean_actual_deg_per_cm"))
        if signed_d is None or signed_d <= 0.0 or mean_deg is None:
            continue
        if int(r.get("pass_count") or 0) <= 0:
            continue
        forward_rows.append({
            "ste": int(r["ste"]),
            "direction": "forward_left" if int(r["ste"]) < 100 else ("forward_right" if int(r["ste"]) > 100 else "forward_straight"),
            "command": r["command"],
            "command_distance_cm": abs(float(signed_d)),
            "deg_per_cm": mean_deg,
            "abs_deg_per_cm": abs(mean_deg),
            "std_deg_per_cm": as_float(r.get("std_delta_yaw_deg")),
            "mean_progress_cm": as_float(r.get("mean_progress_cm")),
            "n": int(r.get("pass_count") or 0),
            "source": "forward_arc_primitive_probe",
            "source_artifact": str(outdir),
            "notes": "Positive D forward ARC table for diy terminal_shuffle; do not merge into reverse chassis_kinematics.",
        })
    return {
        "schema": "terminal_shuffle_forward_kinematics.v1",
        "generated_at": now_iso(),
        "generated_by": "tools/chassis_action_set_validation.py",
        "source_artifact": str(outdir),
        "units": {
            "ste": "servo_deg",
            "deg_per_cm": "yaw_deg_per_cm_done_d",
            "command_distance_cm": "cm",
        },
        "policy": "Dedicated forward ARC primitive table for terminal shuffle only; reverse chassis_kinematics remains unchanged.",
        "steer_curvature": sorted(forward_rows, key=lambda x: x["ste"]),
    }


def write_report(outdir: Path, rows: list[dict[str, Any]], recommended: dict[str, Any], args: argparse.Namespace) -> None:
    lines = [
        "# 底盘执行动作集隔离验证报告",
        "",
        f"- 生成时间：`{now_iso()}`",
        f"- 输出目录：`{outdir}`",
        f"- 总体：`{recommended.get('overall')}`",
        "- 本轮不写 `chassis_kinematics.json` / `chassis_signs.json`。",
        "",
        "## Summary",
        "| batch | role | command | pass | mean yaw | yaw std | progress | lateral | accepted | fail reasons |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {batch} | {role} | `{command}` | {pass_count}/{sample_count} | {yaw} | {std} | {prog} | {lat} | `{acc}` | {fail} |".format(
                batch=r["batch"],
                role=r["role"],
                command=r["command"],
                pass_count=r["pass_count"],
                sample_count=r["sample_count"],
                yaw=fmt(r.get("mean_delta_yaw_deg")),
                std=fmt(r.get("std_delta_yaw_deg")),
                prog=fmt(r.get("mean_progress_cm")),
                lat=fmt(r.get("mean_abs_lateral_cm")),
                acc=r["accepted"],
                fail=r.get("fail_reasons") or "",
            )
        )
    lines += [
        "",
        "## Recommended runtime action set",
        f"- straight_baseline: `{cmd_of(recommended.get('straight_baseline'))}`",
        f"- left_light: `{cmd_of(recommended.get('left_light'))}`",
        f"- right_light: `{cmd_of(recommended.get('right_light'))}`",
        f"- left_strong: `{cmd_of(recommended.get('left_strong'))}`",
        f"- right_strong: `{cmd_of(recommended.get('right_strong'))}`",
        "",
        "## Notes",
        "- `STE=100` 按工程直线基准处理；连续 sweep 的异常不直接推翻该结论。",
        "- 若出现 no-progress / IMU fault / DROP / STOP 异常，脚本会停止后续 batch。",
    ]
    (outdir / "chassis_action_set_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt(v: Any) -> str:
    if v is None:
        return ""
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)


def cmd_of(row: dict[str, Any] | None) -> str:
    return "" if not row else str(row.get("command") or "")


def should_abort_after_sample(sample: dict[str, Any], args: argparse.Namespace) -> bool:
    if not args.stop_on_fail:
        return False
    reasons = set(sample.get("fail_reasons") or [])
    hard = {"motion_returncode", "motion_err", "stop_returncode", "imu_not_ok", "drop_nonzero", "vel_not_zero", "no_progress", "wrong_yaw_direction", "yaw_out_of_range"}
    return bool(reasons & hard)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.137.2")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="ebaina")
    ap.add_argument("--out-root", default=str(ROOT / "artifacts" / "chassis_action_set_validation"))
    ap.add_argument("--batch-spec", default=DEFAULT_BATCH_SPEC)
    ap.add_argument("--run", action="store_true", help="Actually execute real motion; requires --allow-risk.")
    ap.add_argument("--allow-risk", action="store_true", help="Required together with --run for real motion.")
    ap.add_argument("--settle-sec", type=float, default=0.35)
    ap.add_argument("--pause-between-samples-sec", type=float, default=0.0)
    ap.add_argument("--stat-read-sec", type=int, default=1)
    ap.add_argument("--motion-read-sec", type=int, default=8)
    ap.add_argument("--stop-read-sec", type=int, default=1)
    ap.add_argument("--max-abs-d-cm", type=float, default=8.0)
    ap.add_argument("--max-gear", type=int, default=1)
    ap.add_argument("--min-ste", type=int, default=45)
    ap.add_argument("--max-ste", type=int, default=140)
    ap.add_argument("--accept-min-progress-cm", type=float, default=2.0)
    ap.add_argument("--accept-vel-abs-max", type=float, default=0.05)
    ap.add_argument("--accept-straight-abs-yaw-deg", type=float, default=1.5)
    ap.add_argument("--accept-light-abs-yaw-deg", type=float, default=3.0)
    ap.add_argument("--accept-strong-abs-yaw-deg", type=float, default=8.0)
    ap.add_argument("--direction-deadband-deg", type=float, default=0.15)
    ap.add_argument("--direction-check-mode", choices=["reverse", "forward", "auto", "none"], default="reverse",
                    help="expected yaw sign convention for left/right direction checks")
    ap.add_argument("--stop-on-fail", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    items = parse_batch_spec(args.batch_spec)
    outdir = Path(args.out_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    raw_path = outdir / "raw_action_samples.jsonl"
    (outdir / "run_config.json").write_text(
        json.dumps({"args": vars(args), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.run and not args.allow_risk:
        print("REFUSE: --run requires --allow-risk after explicit operator approval.", file=sys.stderr)
        print("No motion was sent.", file=sys.stderr)
        return 4

    samples: list[dict[str, Any]] = []
    aborted = False
    if not args.run:
        print("DRY_PLAN_ONLY: no motion will be sent. Use --run --allow-risk after approval.")
        for item in items:
            print(f"{item['batch']:8s} repeat={item['repeat']} {item['command']}")
    else:
        append_jsonl(raw_path, {"event": "validation_start", "time": now_iso(), "items": items})
        try:
            run_stm32(args, "STOP", read_sec=args.stop_read_sec)
            current_batch = None
            for item in items:
                if current_batch != item["batch"]:
                    current_batch = item["batch"]
                    print(f"[batch] {current_batch}", flush=True)
                for rep in range(1, item["repeat"] + 1):
                    print(f"[sample] {item['batch']} rep={rep}/{item['repeat']} {item['command']}", flush=True)
                    sample = run_action(args, item, rep, raw_path)
                    samples.append(sample)
                    print(
                        "[result] verdict=%s dyaw=%s progress=%s x=%s reasons=%s" % (
                            sample["verdict"],
                            fmt(sample.get("delta_yaw_deg")),
                            fmt(sample.get("odom_progress_cm")),
                            fmt(sample.get("odom_x_delta_cm")),
                            ",".join(sample.get("fail_reasons") or []),
                        ),
                        flush=True,
                    )
                    if should_abort_after_sample(sample, args):
                        aborted = True
                        print("[abort] stop_on_fail triggered; stopping further batches.", flush=True)
                        break
                    if args.pause_between_samples_sec > 0:
                        time.sleep(args.pause_between_samples_sec)
                stop_end = run_stm32(args, "STOP", read_sec=args.stop_read_sec)
                stat_end = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
                append_jsonl(raw_path, {
                    "event": "batch_end",
                    "time": now_iso(),
                    "batch": item["batch"],
                    "stop": stop_end.to_json(),
                    "stat": stat_end.to_json(),
                })
                if aborted:
                    break
        finally:
            try:
                final_stop = run_stm32(args, "STOP", read_sec=args.stop_read_sec)
                final_stat = run_stm32(args, "STAT", read_sec=args.stat_read_sec)
                append_jsonl(raw_path, {
                    "event": "validation_end",
                    "time": now_iso(),
                    "aborted": aborted,
                    "final_stop": final_stop.to_json(),
                    "final_stat": final_stat.to_json(),
                })
            except Exception as exc:  # noqa: BLE001
                append_jsonl(raw_path, {"event": "validation_end_error", "time": now_iso(), "error": str(exc)})

    rows, recommended = summarize(samples, items, outdir, args)
    recommended["aborted"] = aborted
    forward_kinematics = build_forward_terminal_shuffle_kinematics(rows, outdir)
    (outdir / "recommended_runtime_action_set.json").write_text(
        json.dumps(recommended, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (outdir / "forward_terminal_shuffle_kinematics.json").write_text(
        json.dumps(forward_kinematics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(outdir, rows, recommended, args)
    print("OUTDIR", outdir)
    print("RAW", raw_path)
    print("SUMMARY", outdir / "action_set_summary.csv")
    print("RECOMMENDED", outdir / "recommended_runtime_action_set.json")
    print("FORWARD_KINEMATICS", outdir / "forward_terminal_shuffle_kinematics.json")
    print("REPORT", outdir / "chassis_action_set_validation_report.md")
    print("OVERALL", recommended.get("overall"), "ABORTED", aborted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
