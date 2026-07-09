#!/usr/bin/env python3
"""Summarize recorded SS-LD-AS01 dToF frames for one physical condition.

Run on the Ubuntu VM. The script reads the current sensor_suite session and
writes a JSON report with packet, depth, zone, and obstacle-block statistics.
It does not control hardware or start any actuator path.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


ZONE_SPECS = [
    ("far_left", "FL", 0.0, 0.2),
    ("left", "L", 0.2, 0.4),
    ("center", "C", 0.4, 0.6),
    ("right", "R", 0.6, 0.8),
    ("far_right", "FR", 0.8, 1.0),
]
WIDTH = 40
HEIGHT = 30
PACKET_SIZE = 4873


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def latest_session(record_root: Path) -> Path:
    sessions = sorted(record_root.glob("session_*"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise SystemExit(f"no session_* under {record_root}")
    return sessions[-1]


def current_session() -> Path:
    marker = Path("/tmp/parking_sensor_link/parking_record_dir")
    if not marker.exists():
        raise SystemExit("missing /tmp/parking_sensor_link/parking_record_dir")
    return latest_session(Path(marker.read_text(encoding="utf-8", errors="replace").strip()))


def finite_stats(values: np.ndarray) -> dict[str, Any]:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "max": None,
        }
    return {
        "count": int(values.size),
        "min": int(np.min(values)),
        "p10": int(np.percentile(values, 10)),
        "p25": int(np.percentile(values, 25)),
        "median": int(np.median(values)),
        "mean": float(np.mean(values)),
        "p75": int(np.percentile(values, 75)),
        "max": int(np.max(values)),
    }


def frame_stats(depth: np.ndarray, min_valid_mm: int, max_valid_mm: int) -> dict[str, Any]:
    finite = depth[np.isfinite(depth)]
    valid_mask = np.isfinite(depth) & (depth >= min_valid_mm) & (depth <= max_valid_mm)
    valid = depth[valid_mask]
    support_mask = np.isfinite(depth) & (depth >= 250) & (depth <= max_valid_mm)
    support = depth[support_mask]
    flat = depth.reshape(-1)
    return {
        "shape": [int(depth.shape[0]), int(depth.shape[1])],
        "all_pixels": int(flat.size),
        "nan_pixels": int(np.count_nonzero(~np.isfinite(depth))),
        "zero_pixels": int(np.count_nonzero(finite == 0)),
        "eq_2_pixels": int(np.count_nonzero(finite == 2)),
        "lt_20_pixels": int(np.count_nonzero(finite < 20)),
        "lt_250_pixels": int(np.count_nonzero((finite > 0) & (finite < 250))),
        "lt_500_pixels": int(np.count_nonzero((finite > 0) & (finite < 500))),
        "lt_1200_pixels": int(np.count_nonzero((finite > 0) & (finite < 1200))),
        "valid_lt_500_pixels": int(np.count_nonzero((valid > 0) & (valid < 500))),
        "valid_lt_1200_pixels": int(np.count_nonzero((valid > 0) & (valid < 1200))),
        "support_pixels_ge250": int(support.size),
        "support_lt_500_pixels": int(np.count_nonzero((support > 0) & (support < 500))),
        "support_lt_1200_pixels": int(np.count_nonzero((support > 0) & (support < 1200))),
        "valid_pixels": int(valid.size),
        "valid_ratio": float(valid.size) / float(flat.size) if flat.size else 0.0,
        "valid": finite_stats(valid.astype(np.float32)),
        "unique_count": int(np.unique(finite).size) if finite.size else 0,
    }


def summarize_depth_frames(frames: list[np.ndarray], min_valid_mm: int, max_valid_mm: int) -> dict[str, Any]:
    if not frames:
        return {"frame_count": 0}
    stack = np.stack(frames, axis=0).astype(np.float32)
    valid_mask = np.isfinite(stack) & (stack >= min_valid_mm) & (stack <= max_valid_mm)
    valid = stack[valid_mask]
    per_frame = [frame_stats(frame, min_valid_mm, max_valid_mm) for frame in frames]
    zone_summary: dict[str, Any] = {}
    for name, label, start_ratio, end_ratio in ZONE_SPECS:
        start_col = max(0, min(WIDTH - 1, int(round(WIDTH * start_ratio))))
        end_col = max(start_col + 1, min(WIDTH, int(round(WIDTH * end_ratio))))
        zone = stack[:, :, start_col:end_col]
        zone_valid = zone[np.isfinite(zone) & (zone >= min_valid_mm) & (zone <= max_valid_mm)]
        zone_support = zone[np.isfinite(zone) & (zone >= 250) & (zone <= max_valid_mm)]
        zone_summary[name] = {
            "label": label,
            "columns": [start_col, end_col],
            "valid": finite_stats(zone_valid),
            "avg_valid_pixels_per_frame": float(zone_valid.size) / float(len(frames)) if frames else 0.0,
            "avg_lt_500_pixels_per_frame": float(np.count_nonzero((zone > 0) & (zone < 500))) / float(len(frames)),
            "avg_lt_1200_pixels_per_frame": float(np.count_nonzero((zone > 0) & (zone < 1200))) / float(len(frames)),
            "support_ge250": finite_stats(zone_support),
            "avg_support_pixels_per_frame": float(zone_support.size) / float(len(frames)) if frames else 0.0,
            "avg_support_lt_500_pixels_per_frame": float(
                np.count_nonzero((zone >= 250) & (zone < 500))
            ) / float(len(frames)),
            "avg_support_lt_1200_pixels_per_frame": float(
                np.count_nonzero((zone >= 250) & (zone < 1200))
            ) / float(len(frames)),
        }
    return {
        "frame_count": len(frames),
        "valid": finite_stats(valid),
        "avg_valid_pixels": float(sum(item["valid_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_valid_ratio": float(sum(item["valid_ratio"] for item in per_frame)) / float(len(per_frame)),
        "avg_zero_pixels": float(sum(item["zero_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_eq_2_pixels": float(sum(item["eq_2_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_lt_250_pixels": float(sum(item["lt_250_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_lt_500_pixels": float(sum(item["lt_500_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_lt_1200_pixels": float(sum(item["lt_1200_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_valid_lt_500_pixels": float(sum(item["valid_lt_500_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_valid_lt_1200_pixels": float(sum(item["valid_lt_1200_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_support_pixels_ge250": float(sum(item["support_pixels_ge250"] for item in per_frame)) / float(len(per_frame)),
        "avg_support_lt_500_pixels": float(sum(item["support_lt_500_pixels"] for item in per_frame)) / float(len(per_frame)),
        "avg_support_lt_1200_pixels": float(sum(item["support_lt_1200_pixels"] for item in per_frame)) / float(len(per_frame)),
        "first_frame": per_frame[0],
        "last_frame": per_frame[-1],
        "zones": zone_summary,
    }


def summarize_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"count": 0}
    times = [int(item.get("recv_time_ns", 0)) for item in items if item.get("recv_time_ns")]
    packet_sizes = [int(item.get("packet_size", 0)) for item in items if item.get("packet_size")]
    expected_shape_count = sum(1 for item in items if item.get("expected_shape") is True)
    hz = None
    if len(times) >= 2 and times[-1] > times[0]:
        hz = float(len(times) - 1) / ((times[-1] - times[0]) / 1_000_000_000.0)
    return {
        "count": len(items),
        "duration_sec": ((times[-1] - times[0]) / 1_000_000_000.0) if len(times) >= 2 else None,
        "rate_hz": hz,
        "packet_size_unique": sorted(set(packet_sizes)),
        "packet_size_expected_count": sum(1 for size in packet_sizes if size == PACKET_SIZE),
        "expected_shape_count": expected_shape_count,
        "last": items[-1],
    }


def summarize_obstacles(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"count": 0}
    states: dict[str, int] = {}
    nearest: list[float] = []
    zone_states: dict[str, dict[str, int]] = {}
    for item in items:
        state = str(item.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
        if item.get("nearest_mm") is not None:
            nearest.append(float(item["nearest_mm"]))
        for zone in item.get("zones", []):
            label = str(zone.get("label") or zone.get("name") or "?")
            zstate = str(zone.get("state") or "unknown")
            zone_states.setdefault(label, {})
            zone_states[label][zstate] = zone_states[label].get(zstate, 0) + 1
    return {
        "count": len(items),
        "states": states,
        "nearest": finite_stats(np.asarray(nearest, dtype=np.float32)) if nearest else finite_stats(np.asarray([], dtype=np.float32)),
        "zone_states": zone_states,
        "last": items[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="", help="Specific session_* directory. Defaults to current session.")
    parser.add_argument("--condition", default="unlabeled", help="Physical test condition label.")
    parser.add_argument("--frames", type=int, default=180, help="Number of latest NPY depth frames to summarize.")
    parser.add_argument("--metadata-lines", type=int, default=300, help="Number of latest metadata lines to summarize.")
    parser.add_argument("--min-valid-mm", type=int, default=20)
    parser.add_argument("--max-valid-mm", type=int, default=10000)
    parser.add_argument("--out", default="", help="Output JSON path. Defaults under session/dtof_condition_reports.")
    args = parser.parse_args()

    session = Path(args.session).expanduser() if args.session else current_session()
    if not session.exists():
        raise SystemExit(f"session not found: {session}")
    depth_files = sorted((session / "dtof_depth_npy").glob("dtof_depth_*.npy"))
    selected_depth_files = depth_files[-max(1, args.frames):]
    frames = [np.load(path) for path in selected_depth_files]
    meta = read_jsonl(session / "dtof_metadata.jsonl")[-max(1, args.metadata_lines):]
    obstacles = read_jsonl(session / "dtof_obstacle_blocks.jsonl")[-max(1, args.metadata_lines):]
    raw_packet_path = session / "dtof_packets.bin"
    packet_bytes = raw_packet_path.stat().st_size if raw_packet_path.exists() else 0
    packet_count_by_size = packet_bytes // PACKET_SIZE if packet_bytes else 0

    report = {
        "condition": args.condition,
        "session": str(session),
        "depth_file_count_total": len(depth_files),
        "depth_file_count_used": len(selected_depth_files),
        "depth_first_file": selected_depth_files[0].name if selected_depth_files else None,
        "depth_last_file": selected_depth_files[-1].name if selected_depth_files else None,
        "raw_packet_bytes": packet_bytes,
        "raw_packet_count_by_size": packet_count_by_size,
        "expected_packet_size": PACKET_SIZE,
        "metadata": summarize_metadata(meta),
        "depth": summarize_depth_frames(frames, args.min_valid_mm, args.max_valid_mm),
        "obstacle_blocks": summarize_obstacles(obstacles),
    }

    if args.out:
        out_path = Path(args.out).expanduser()
    else:
        out_dir = session / "dtof_condition_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_condition = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.condition)
        out_path = out_dir / f"{safe_condition}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"DTOF_CONDITION_REPORT {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
