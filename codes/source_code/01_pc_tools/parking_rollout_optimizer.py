#!/usr/bin/env python3
"""Full-range rollout optimizer for H1 reverse parking.

Pure-stdlib decision core.  It searches short measured-action sequences with a
kinematic model, returns only the first action, and expects the controller shell
to stop, observe, and replan after every motion.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SERVO_CENTER_DEFAULT = 100

DEFAULT_CONFIG: dict[str, Any] = {
    "target_y_cm": 1.5,
    "target_lateral_cm": 0.0,
    "success_lateral_tol_cm": 2.0,
    "success_heading_tol_deg": 3.0,
    "max_abs_lateral_cm": 40.0,
    "max_abs_heading_deg": 65.0,
    "deadband_cm": 1.95,
    "coast_cm": 0.275,
    "min_command_cm": 4.0,
    "forward_yaw_sign": -1.0,
    "max_forward_total_cm": 16.0,
    "max_direction_switch_count": 6,
    "min_score_improve_for_switch": 5.0,
    "no_improve_stop_count": 3,
    "overdeep_free_cm": 2.0,
    "overdeep_hard_cm": 8.0,
    "forward_kinematics_json": "",
    "side_clearance": {
        "enabled": True,
        "slot_half_width_cm": 12.25,
        "car_width_cm": 15.0,
        "car_length_cm": 20.0,
        "rear_axle_to_body_center_cm": 7.0,
        "target_clearance_cm": 3.0,
        "soft_min_clearance_cm": 2.0,
        "hard_min_clearance_cm": 1.0,
        "hard_active_y_cm": 35.0,
        "penalty_weight": 16.0,
        "late_weight_scale": 1.6,
        "long_step_weight_scale": 1.25,
        "near_side_enabled": True,
        "near_side_min_clearance_cm": 3.0,
        "near_side_weight": 22.0,
        "near_side_early_y_cm": 25.0,
        "near_side_early_scale": 1.3,
        "sample_fractions": [0.25, 0.5, 0.75, 1.0],
        "short_step_sample_fractions": [0.5, 1.0],
        "locked_near_side": "",
        "allow_escape_when_already_violating": True,
        "escape_worsen_tolerance_cm": 0.25,
    },
    "stage_thresholds": {"early_y_cm": 35.0, "late_y_cm": 15.0},
    "stages": {
        "early": {
            "horizon": 6,
            "beam_width": 32,
            "reverse_distances_cm": [7.0, 9.0],
            "forward_distances_cm": [6.0, 8.0],
            "ste_candidates": [60, 75, 85, 100, 115, 130, 140],
            "weights": {
                "heading": 18.0,
                "lateral": 10.0,
                "y": 5.0,
                "forward": 3.0,
                "switch": 8.0,
                "step": 1.0,
            },
        },
        "middle": {
            "horizon": 6,
            "beam_width": 48,
            "reverse_distances_cm": [5.0, 7.0],
            "forward_distances_cm": [4.0, 6.0],
            "ste_candidates": [60, 70, 80, 90, 100, 110, 120, 130, 140],
            "weights": {
                "heading": 24.0,
                "lateral": 14.0,
                "y": 6.0,
                "forward": 4.0,
                "switch": 10.0,
                "step": 1.0,
            },
        },
        "late": {
            "horizon": 5,
            "beam_width": 64,
            "reverse_distances_cm": [4.0, 5.0],
            "forward_distances_cm": [4.0],
            "ste_candidates": [60, 70, 80, 90, 100, 110, 120, 130, 140],
            "weights": {
                "heading": 35.0,
                "lateral": 18.0,
                "y": 8.0,
                "forward": 5.0,
                "switch": 12.0,
                "step": 1.0,
            },
        },
    },
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return v


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def wrap_deg(a: Any) -> float:
    a = _to_float(a, 0.0)
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


def _deep_update(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in (src or {}).items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_update(dst[key], value)
        else:
            dst[key] = value
    return dst


def _jsonable_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(cfg))


def merged_config(kinematics: dict[str, Any] | None = None,
                  overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _jsonable_config(DEFAULT_CONFIG)
    kin = kinematics or {}
    if kin.get("arc_deadband_cm") is not None:
        cfg["deadband_cm"] = _to_float(kin.get("arc_deadband_cm"), cfg["deadband_cm"])
    if kin.get("coast_after_done_cm") is not None:
        cfg["coast_cm"] = _to_float(kin.get("coast_after_done_cm"), cfg["coast_cm"])
    if kin.get("arc_min_effective_cmd_cm") is not None:
        cfg["min_command_cm"] = max(
            _to_float(cfg["min_command_cm"]),
            _to_float(kin.get("arc_min_effective_cmd_cm"), cfg["min_command_cm"]),
        )
    _deep_update(cfg, overrides or {})
    return cfg


# ---------------------------------------------------------------------------
# Curvature tables.
# ---------------------------------------------------------------------------


def build_curvature_table(kinematics: dict[str, Any]) -> list[tuple[int, float, float]]:
    kin = kinematics or {}
    center = _to_int(kin.get("servo_center_trim_ste"), SERVO_CENTER_DEFAULT)
    rows: dict[int, tuple[float, float]] = {}
    for row in kin.get("steer_curvature", []) or []:
        if row.get("ste") is None or row.get("deg_per_cm") is None:
            continue
        ste = _to_int(row.get("ste"), center)
        rows[ste] = (
            _to_float(row.get("deg_per_cm"), 0.0),
            _to_float(row.get("cv_abs_deg_per_cm"), 0.08),
        )
    rows[center] = (0.0, 0.0)
    table = sorted((ste, k, cv) for ste, (k, cv) in rows.items())
    dedup: list[tuple[int, float, float]] = []
    for ste, k, cv in table:
        if dedup and abs(k - dedup[-1][1]) < 1e-9 and k != 0.0:
            continue
        dedup.append((ste, k, cv))
    if len(dedup) < 3:
        raise ValueError("curvature table needs >=3 measured points")
    return dedup


def deg_per_cm_for_ste(table: list[tuple[int, float, float]], ste: int) -> float:
    ste = int(round(ste))
    if ste <= table[0][0]:
        return float(table[0][1])
    if ste >= table[-1][0]:
        return float(table[-1][1])
    for (s0, k0, _), (s1, k1, _) in zip(table, table[1:]):
        if s0 <= ste <= s1:
            if s1 == s0:
                return float(k0)
            t = (ste - s0) / float(s1 - s0)
            return float(k0 + t * (k1 - k0))
    return float(table[-1][1])


def load_forward_kinematics(path: str | Path | None) -> dict[str, Any]:
    path = str(path or "").strip()
    if not path:
        return {"schema": "missing", "steer_curvature": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {"schema": "missing_or_invalid", "steer_curvature": [], "error": str(exc)}
    if not isinstance(data, dict):
        return {"schema": "invalid", "steer_curvature": []}
    return data


def forward_row_for_ste(forward_table: dict[str, Any] | None, ste: int) -> dict[str, Any] | None:
    if not isinstance(forward_table, dict):
        return None
    rows = forward_table.get("steer_curvature") or []
    exact = None
    nearest = None
    nearest_gap = 999999
    for row in rows:
        if not isinstance(row, dict) or row.get("ste") is None or row.get("deg_per_cm") is None:
            continue
        rste = _to_int(row.get("ste"), 0)
        if rste == int(ste):
            exact = row
            break
        gap = abs(rste - int(ste))
        if gap < nearest_gap:
            nearest_gap = gap
            nearest = row
    if exact is not None:
        return exact
    # Nearest measured forward row is acceptable only for dense late search
    # neighbors; otherwise the reverse-table sign fallback is safer.
    return nearest if nearest is not None and nearest_gap <= 5 else None


def forward_deg_per_cm_for_ste(reverse_table: list[tuple[int, float, float]],
                               forward_table: dict[str, Any] | None,
                               ste: int,
                               cfg: dict[str, Any]) -> tuple[float, str, dict[str, Any] | None]:
    row = forward_row_for_ste(forward_table, ste)
    if row is not None:
        return _to_float(row.get("deg_per_cm"), 0.0), "terminal_shuffle_forward_kinematics", row
    sign = _to_float(cfg.get("forward_yaw_sign"), -1.0)
    return sign * deg_per_cm_for_ste(reverse_table, ste), "reverse_curve_sign_inverted" if sign < 0 else "reverse_curve_same_sign", None


# ---------------------------------------------------------------------------
# Motion and scoring.
# ---------------------------------------------------------------------------


def normalize_pose(pose: dict[str, Any]) -> dict[str, float]:
    return {
        "y_dist_cm": _to_float(pose.get("y_dist_cm"), 999.0),
        "lateral_cm": _to_float(pose.get("lateral_cm"), 0.0),
        "heading_deg": wrap_deg(pose.get("heading_deg")),
    }


def expected_ground_progress(command_cm: Any, cfg: dict[str, Any]) -> float:
    return max(0.0, _to_float(command_cm, 0.0) - _to_float(cfg.get("deadband_cm"), 1.95)
               + _to_float(cfg.get("coast_cm"), 0.275))


def _integrate(pose: dict[str, float], ground_cm: float, yaw_delta_deg: float,
               direction: str) -> dict[str, float]:
    d = max(0.0, _to_float(ground_cm, 0.0))
    psi0 = wrap_deg(pose.get("heading_deg"))
    yaw_delta = _to_float(yaw_delta_deg, 0.0)
    theta_mid = math.radians(wrap_deg(psi0 + 0.5 * yaw_delta))
    if direction == "forward":
        y = pose["y_dist_cm"] + d * math.cos(theta_mid)
        lat = pose["lateral_cm"] - d * math.sin(theta_mid)
    else:
        y = pose["y_dist_cm"] - d * math.cos(theta_mid)
        lat = pose["lateral_cm"] + d * math.sin(theta_mid)
    return {"y_dist_cm": y, "lateral_cm": lat, "heading_deg": wrap_deg(psi0 + yaw_delta)}


def simulate_action(pose: dict[str, Any], action: dict[str, Any], cfg: dict[str, Any],
                    reverse_table: list[tuple[int, float, float]],
                    forward_table: dict[str, Any] | None = None) -> dict[str, Any]:
    p = normalize_pose(pose)
    direction = str(action.get("direction") or "reverse").lower()
    ste = _to_int(action.get("ste"), SERVO_CENTER_DEFAULT)
    command_cm = max(_to_float(cfg.get("min_command_cm"), 4.0),
                     _to_float(action.get("command_cm"), 0.0))
    ground = expected_ground_progress(command_cm, cfg)
    if direction == "forward":
        deg_per_cm, source, frow = forward_deg_per_cm_for_ste(reverse_table, forward_table, ste, cfg)
    else:
        deg_per_cm, source, frow = deg_per_cm_for_ste(reverse_table, ste), "chassis_kinematics", None
    yaw_delta = deg_per_cm * ground
    pred = _integrate(p, ground, yaw_delta, direction)
    return {
        "pose": pred,
        "expected_ground_cm": round(float(ground), 3),
        "deg_per_cm": round(float(deg_per_cm), 6),
        "yaw_delta_deg": round(float(yaw_delta), 3),
        "kinematics_source": source,
        "forward_kinematics_row": frow,
    }


def side_clearance_config(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("side_clearance") or {}
    return raw if isinstance(raw, dict) else {}


def side_clearance_enabled(cfg: dict[str, Any]) -> bool:
    return bool(side_clearance_config(cfg).get("enabled", False))


def _float_list(value: Any, default: list[float]) -> list[float]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return list(default)
    out = []
    for item in parts:
        v = _to_float(item, math.nan)
        if math.isnan(v) or math.isinf(v):
            continue
        out.append(float(v))
    return out or list(default)


def clearance_sample_fractions(command_cm: Any, cfg: dict[str, Any]) -> list[float]:
    sc = side_clearance_config(cfg)
    default = [0.25, 0.5, 0.75, 1.0]
    if _to_float(command_cm, 0.0) <= 4.001:
        vals = _float_list(sc.get("short_step_sample_fractions"), [0.5, 1.0])
    else:
        vals = _float_list(sc.get("sample_fractions"), default)
    vals = sorted({round(float(v), 6) for v in vals if 0.0 < float(v) <= 1.0})
    if 1.0 not in vals:
        vals.append(1.0)
    return vals or [1.0]


def body_clearance_review(pose: dict[str, Any], cfg: dict[str, Any],
                          stage: str = "candidate", distance_cm: Any = None,
                          fraction: Any = None, near_side: str | None = None) -> dict[str, Any]:
    """Review vehicle body envelope against the left/right slot lines.

    The pose is a rear-axle-center style parking pose in centimeters.  The
    side lines are modeled as lateral = +/- slot_half_width_cm.  This mirrors
    the controller shell's H1 body-clearance calculation but stays pure
    stdlib so the optimizer can reject risky rollouts before choosing a move.
    """
    p = normalize_pose(pose)
    sc = side_clearance_config(cfg)
    slot_half_width = _to_float(sc.get("slot_half_width_cm"), 12.25)
    car_width = max(0.0, _to_float(sc.get("car_width_cm"), 15.0))
    car_length = max(0.0, _to_float(sc.get("car_length_cm"), 20.0))
    rear_axle_to_body_center = _to_float(sc.get("rear_axle_to_body_center_cm"), 7.0)
    car_half_width = car_width * 0.5
    car_half_length = car_length * 0.5
    front_overhang = max(0.0, car_half_length + rear_axle_to_body_center)
    rear_overhang = max(0.0, car_half_length - rear_axle_to_body_center)
    heading_rad = math.radians(p["heading_deg"])
    corner_specs = [
        ("rear_left", -rear_overhang, -car_half_width),
        ("rear_right", -rear_overhang, car_half_width),
        ("front_left", front_overhang, -car_half_width),
        ("front_right", front_overhang, car_half_width),
    ]
    laterals = []
    corners = []
    for name, long_cm, side_cm in corner_specs:
        lat = p["lateral_cm"] + side_cm * math.cos(heading_rad) + long_cm * math.sin(heading_rad)
        laterals.append(lat)
        corners.append({
            "name": name,
            "long_cm": round(float(long_cm), 3),
            "side_cm": round(float(side_cm), 3),
            "lateral_cm": round(float(lat), 3),
        })
    left_body_edge = min(laterals) if laterals else p["lateral_cm"]
    right_body_edge = max(laterals) if laterals else p["lateral_cm"]
    left_line = -float(slot_half_width)
    right_line = float(slot_half_width)
    left_clearance = float(left_body_edge) - left_line
    right_clearance = right_line - float(right_body_edge)
    min_clearance = min(left_clearance, right_clearance)
    measured_near_side = "left" if left_clearance <= right_clearance else "right"
    locked_near_side = str(near_side or sc.get("locked_near_side") or "").strip().lower()
    if locked_near_side not in ("left", "right", "center"):
        locked_near_side = measured_near_side
    if locked_near_side == "left":
        near_clearance = left_clearance
    elif locked_near_side == "right":
        near_clearance = right_clearance
    else:
        near_clearance = min_clearance

    target = _to_float(sc.get("target_clearance_cm"), 3.0)
    soft_min = _to_float(sc.get("soft_min_clearance_cm"), 2.0)
    hard_min = _to_float(sc.get("hard_min_clearance_cm"), 1.0)
    weight = max(0.0, _to_float(sc.get("penalty_weight"), 16.0))
    penalty = 0.0
    if side_clearance_enabled(cfg) and min_clearance < target:
        penalty = ((target - min_clearance) ** 2) * weight
        if min_clearance < soft_min:
            penalty *= 1.35
    if side_clearance_enabled(cfg) and p["y_dist_cm"] <= 25.0:
        penalty *= max(0.0, _to_float(sc.get("late_weight_scale"), 1.6))
    if side_clearance_enabled(cfg) and _to_float(distance_cm, 0.0) >= 6.0:
        penalty *= max(0.0, _to_float(sc.get("long_step_weight_scale"), 1.25))

    near_enabled = bool(sc.get("near_side_enabled", False))
    near_min = _to_float(sc.get("near_side_min_clearance_cm"), 3.0)
    near_weight = max(0.0, _to_float(sc.get("near_side_weight"), 22.0))
    near_debt = max(0.0, near_min - near_clearance)
    near_penalty = (near_debt ** 2) * near_weight if side_clearance_enabled(cfg) and near_enabled else 0.0
    near_early_applied = bool(
        side_clearance_enabled(cfg) and near_enabled and
        p["y_dist_cm"] > _to_float(sc.get("near_side_early_y_cm"), 25.0)
    )
    if near_early_applied:
        near_penalty *= max(0.0, _to_float(sc.get("near_side_early_scale"), 1.3))

    hard_active = bool(p["y_dist_cm"] <= _to_float(sc.get("hard_active_y_cm"), 35.0))
    hard_block = bool(side_clearance_enabled(cfg) and hard_active and min_clearance < hard_min)
    return {
        "schema": "parking_rollout_body_clearance_review.v1",
        "enabled": bool(side_clearance_enabled(cfg)),
        "stage": stage,
        "fraction": None if fraction is None else round(float(fraction), 3),
        "pose": {k: round(v, 3) for k, v in p.items()},
        "slot_half_width_cm": round(float(slot_half_width), 3),
        "car_width_cm": round(float(car_width), 3),
        "car_length_cm": round(float(car_length), 3),
        "rear_axle_to_body_center_cm": round(float(rear_axle_to_body_center), 3),
        "left_body_edge_cm": round(float(left_body_edge), 3),
        "right_body_edge_cm": round(float(right_body_edge), 3),
        "body_corner_lateral_samples": corners,
        "left_clearance_cm": round(float(left_clearance), 3),
        "right_clearance_cm": round(float(right_clearance), 3),
        "min_side_clearance_cm": round(float(min_clearance), 3),
        "near_side": locked_near_side,
        "measured_near_side": measured_near_side,
        "near_side_clearance_cm": round(float(near_clearance), 3),
        "side_clearance_target_cm": round(float(target), 3),
        "side_clearance_soft_min_cm": round(float(soft_min), 3),
        "side_clearance_hard_min_cm": round(float(hard_min), 3),
        "clearance_penalty": round(float(penalty), 3),
        "near_side_clearance_enabled": bool(near_enabled),
        "near_side_min_clearance_cm": round(float(near_min), 3),
        "near_side_penalty": round(float(near_penalty), 3),
        "near_side_early_scale_applied": bool(near_early_applied),
        "hard_active_y_cm": round(_to_float(sc.get("hard_active_y_cm"), 35.0), 3),
        "hard_active": bool(hard_active),
        "hard_block": bool(hard_block),
        "block_reason": "body_clearance_below_hard_min" if hard_block else "ok",
        "lateral_sign_convention": "lateral<0 means closer_to_left_line",
    }


def trajectory_clearance_review(start_pose: dict[str, Any], action: dict[str, Any],
                                sim: dict[str, Any], cfg: dict[str, Any],
                                near_side: str | None = None) -> dict[str, Any]:
    enabled = side_clearance_enabled(cfg)
    command_cm = _to_float(action.get("command_cm"), 0.0)
    direction = str(action.get("direction") or "reverse").lower()
    ground = _to_float(sim.get("expected_ground_cm"), 0.0)
    yaw_delta = _to_float(sim.get("yaw_delta_deg"), 0.0)
    start = normalize_pose(start_pose)
    start_item = body_clearance_review(
        start, cfg, stage="trajectory_start", distance_cm=command_cm,
        fraction=0.0, near_side=near_side)
    samples = []
    min_item = None
    min_near_item = None
    max_penalty = 0.0
    max_near_penalty = 0.0
    hard_block = False
    fractions = clearance_sample_fractions(command_cm, cfg)
    for frac in fractions:
        sample_pose = _integrate(start, ground * float(frac), yaw_delta * float(frac), direction)
        item = body_clearance_review(
            sample_pose, cfg, stage="trajectory_sample", distance_cm=command_cm,
            fraction=frac, near_side=near_side)
        samples.append(item)
        max_penalty = max(max_penalty, _to_float(item.get("clearance_penalty"), 0.0))
        max_near_penalty = max(max_near_penalty, _to_float(item.get("near_side_penalty"), 0.0))
        if min_item is None or _to_float(item.get("min_side_clearance_cm"), 999.0) < _to_float(min_item.get("min_side_clearance_cm"), 999.0):
            min_item = item
        if min_near_item is None or _to_float(item.get("near_side_clearance_cm"), 999.0) < _to_float(min_near_item.get("near_side_clearance_cm"), 999.0):
            min_near_item = item
        if item.get("hard_block"):
            hard_block = True

    sc = side_clearance_config(cfg)
    start_min = _to_float(start_item.get("min_side_clearance_cm"), 999.0)
    traj_min = _to_float((min_item or {}).get("min_side_clearance_cm"), start_min)
    hard_min = _to_float(sc.get("hard_min_clearance_cm"), 1.0)
    if hard_block and bool(sc.get("allow_escape_when_already_violating", True)) and start_min < hard_min:
        tolerance = max(0.0, _to_float(sc.get("escape_worsen_tolerance_cm"), 0.25))
        if traj_min >= start_min - tolerance:
            hard_block = False

    return {
        "schema": "parking_rollout_trajectory_clearance_review.v1",
        "enabled": bool(enabled),
        "distance_cm": round(float(command_cm), 3),
        "direction": direction,
        "sample_fractions": [round(float(f), 3) for f in fractions],
        "start_min_side_clearance_cm": start_item.get("min_side_clearance_cm"),
        "min_side_clearance_cm": None if min_item is None else min_item.get("min_side_clearance_cm"),
        "min_clearance_fraction": None if min_item is None else min_item.get("fraction"),
        "near_side": None if min_item is None else min_item.get("near_side"),
        "near_side_clearance_cm": None if min_near_item is None else min_near_item.get("near_side_clearance_cm"),
        "clearance_penalty": round(float(max_penalty), 3),
        "near_side_penalty": round(float(max_near_penalty), 3),
        "total_clearance_penalty": round(float(max_penalty + max_near_penalty), 3),
        "hard_block": bool(hard_block),
        "block_reason": "body_clearance_below_hard_min" if hard_block else "ok",
        "samples": samples,
    }


def success(pose: dict[str, Any], cfg: dict[str, Any]) -> bool:
    p = normalize_pose(pose)
    return (
        p["y_dist_cm"] <= _to_float(cfg.get("target_y_cm"), 1.5) and
        abs(p["lateral_cm"] - _to_float(cfg.get("target_lateral_cm"), 0.0)) <= _to_float(cfg.get("success_lateral_tol_cm"), 2.0) and
        abs(wrap_deg(p["heading_deg"])) <= _to_float(cfg.get("success_heading_tol_deg"), 3.0)
    )


def stage_name_for_pose(pose: dict[str, Any], cfg: dict[str, Any]) -> str:
    y = normalize_pose(pose)["y_dist_cm"]
    th = cfg.get("stage_thresholds") or {}
    early_y = _to_float(th.get("early_y_cm"), 35.0)
    late_y = _to_float(th.get("late_y_cm"), 15.0)
    if y > early_y:
        return "early"
    if y > late_y:
        return "middle"
    return "late"


def stage_config(stage: str, cfg: dict[str, Any]) -> dict[str, Any]:
    stages = cfg.get("stages") or {}
    return dict(stages.get(stage) or stages.get("late") or {})


def action_library(stage: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    scfg = stage_config(stage, cfg)
    stes = [_to_int(v, SERVO_CENTER_DEFAULT) for v in scfg.get("ste_candidates", [])]
    actions: list[dict[str, Any]] = []
    for dist in scfg.get("reverse_distances_cm", []) or []:
        for ste in stes:
            actions.append({"direction": "reverse", "command_cm": _to_float(dist), "signed_command_cm": -_to_float(dist), "ste": ste})
    for dist in scfg.get("forward_distances_cm", []) or []:
        for ste in stes:
            actions.append({"direction": "forward", "command_cm": _to_float(dist), "signed_command_cm": _to_float(dist), "ste": ste})
    # Stable deterministic order: reverse first, shorter first, then near center.
    actions.sort(key=lambda a: (0 if a["direction"] == "reverse" else 1,
                                a["command_cm"], abs(a["ste"] - SERVO_CENTER_DEFAULT), a["ste"]))
    return actions


def score_pose(pose: dict[str, Any], cfg: dict[str, Any], weights: dict[str, Any],
               action_count: int = 0, forward_total_cm: float = 0.0,
               switch_count: int = 0, clearance_penalty: float = 0.0,
               min_side_clearance_cm: float | None = None) -> dict[str, Any]:
    p = normalize_pose(pose)
    target_y = _to_float(cfg.get("target_y_cm"), 1.5)
    target_lat = _to_float(cfg.get("target_lateral_cm"), 0.0)
    lat_abs = abs(p["lateral_cm"] - target_lat)
    head_abs = abs(wrap_deg(p["heading_deg"]))
    y_above = max(0.0, p["y_dist_cm"] - target_y)
    overdeep = max(0.0, target_y - p["y_dist_cm"] - _to_float(cfg.get("overdeep_free_cm"), 2.0))
    heading_tol = _to_float(cfg.get("success_heading_tol_deg"), 3.0)
    lateral_tol = _to_float(cfg.get("success_lateral_tol_cm"), 2.0)
    score = 0.0
    score += _to_float(weights.get("heading"), 35.0) * head_abs
    score += _to_float(weights.get("lateral"), 18.0) * lat_abs
    score += _to_float(weights.get("y"), 8.0) * y_above
    score += _to_float(weights.get("y"), 8.0) * 1.8 * overdeep
    score += _to_float(weights.get("forward"), 5.0) * max(0.0, forward_total_cm)
    score += _to_float(weights.get("switch"), 12.0) * max(0, switch_count)
    score += _to_float(weights.get("step"), 1.0) * max(0, action_count)
    score += max(0.0, _to_float(clearance_penalty, 0.0))
    if head_abs > heading_tol:
        score += 80.0 + 20.0 * (head_abs - heading_tol) ** 2
    if lat_abs > lateral_tol:
        score += 80.0 + 12.0 * (lat_abs - lateral_tol) ** 2
    if y_above > 0.0:
        score += 60.0 + 8.0 * y_above ** 2
    if target_y - p["y_dist_cm"] > _to_float(cfg.get("overdeep_hard_cm"), 8.0):
        score += 1000.0
    ok = success(p, cfg)
    if ok:
        score -= 5000.0
    return {
        "score": round(float(score), 3),
        "success": bool(ok),
        "heading_abs_deg": round(float(head_abs), 3),
        "lateral_abs_cm": round(float(lat_abs), 3),
        "y_above_target_cm": round(float(y_above), 3),
        "overdeep_penalty_cm": round(float(overdeep), 3),
        "action_count": int(action_count),
        "forward_total_cm": round(float(forward_total_cm), 3),
        "switch_count": int(switch_count),
        "clearance_penalty": round(max(0.0, _to_float(clearance_penalty, 0.0)), 3),
        "min_side_clearance_cm": (
            None if min_side_clearance_cm is None
            else round(_to_float(min_side_clearance_cm, 0.0), 3)
        ),
    }


def _state_ok(pose: dict[str, Any], cfg: dict[str, Any]) -> bool:
    p = normalize_pose(pose)
    return (
        abs(p["lateral_cm"] - _to_float(cfg.get("target_lateral_cm"), 0.0)) <= _to_float(cfg.get("max_abs_lateral_cm"), 40.0) and
        abs(wrap_deg(p["heading_deg"])) <= _to_float(cfg.get("max_abs_heading_deg"), 65.0)
    )


def beam_search(pose: dict[str, Any], cfg: dict[str, Any],
                reverse_table: list[tuple[int, float, float]],
                forward_table: dict[str, Any] | None = None,
                history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    start = normalize_pose(pose)
    stage = stage_name_for_pose(start, cfg)
    scfg = stage_config(stage, cfg)
    horizon = max(1, _to_int(scfg.get("horizon"), 5))
    beam_width = max(1, _to_int(scfg.get("beam_width"), 64))
    weights = scfg.get("weights") or {}
    actions = action_library(stage, cfg)
    locked_near_side = str(side_clearance_config(cfg).get("locked_near_side") or "").strip().lower()
    if locked_near_side not in ("left", "right", "center"):
        locked_near_side = None
    initial_clearance = body_clearance_review(start, cfg, stage="initial", near_side=locked_near_side)
    initial_score = score_pose(
        start, cfg, weights,
        clearance_penalty=0.0,
        min_side_clearance_cm=initial_clearance.get("min_side_clearance_cm"),
    )
    beam = [{
        "pose": start,
        "actions": [],
        "forward_total_cm": 0.0,
        "switch_count": 0,
        "last_direction": None,
        "clearance_penalty": 0.0,
        "min_side_clearance_cm": initial_clearance.get("min_side_clearance_cm"),
        "score_review": initial_score,
    }]
    best = None
    layers = []
    max_forward_total = _to_float(cfg.get("max_forward_total_cm"), 16.0)
    max_switch_count = _to_int(cfg.get("max_direction_switch_count"), 6)
    for depth in range(1, horizon + 1):
        expanded = []
        for node in beam:
            for action in actions:
                sim = simulate_action(node["pose"], action, cfg, reverse_table, forward_table)
                pred = sim["pose"]
                if not _state_ok(pred, cfg):
                    continue
                clearance_review = trajectory_clearance_review(
                    node["pose"], action, sim, cfg, near_side=locked_near_side)
                if clearance_review.get("hard_block"):
                    continue
                action_clearance_penalty = _to_float(
                    clearance_review.get("total_clearance_penalty"), 0.0)
                clearance_penalty = max(
                    _to_float(node.get("clearance_penalty"), 0.0),
                    action_clearance_penalty,
                )
                node_min_clearance = _to_float(node.get("min_side_clearance_cm"), 999.0)
                action_min_clearance = _to_float(
                    clearance_review.get("min_side_clearance_cm"), node_min_clearance)
                min_side_clearance = min(node_min_clearance, action_min_clearance)
                fwd_total = node["forward_total_cm"]
                if action["direction"] == "forward":
                    fwd_total += action["command_cm"]
                if fwd_total > max_forward_total:
                    continue
                switch_count = node["switch_count"]
                if node["last_direction"] and node["last_direction"] != action["direction"]:
                    switch_count += 1
                if switch_count > max_switch_count:
                    continue
                hist_actions = list(node["actions"]) + [dict(action, **{
                    "expected_ground_cm": sim["expected_ground_cm"],
                    "deg_per_cm": sim["deg_per_cm"],
                    "yaw_delta_deg": sim["yaw_delta_deg"],
                    "kinematics_source": sim["kinematics_source"],
                    "predicted_pose": {k: round(v, 3) for k, v in pred.items()},
                    "clearance_review": {
                        "enabled": clearance_review.get("enabled"),
                        "min_side_clearance_cm": clearance_review.get("min_side_clearance_cm"),
                        "near_side_clearance_cm": clearance_review.get("near_side_clearance_cm"),
                        "total_clearance_penalty": clearance_review.get("total_clearance_penalty"),
                        "hard_block": clearance_review.get("hard_block"),
                    },
                })]
                sr = score_pose(
                    pred, cfg, weights, len(hist_actions), fwd_total, switch_count,
                    clearance_penalty=clearance_penalty,
                    min_side_clearance_cm=min_side_clearance,
                )
                item = {
                    "pose": pred,
                    "actions": hist_actions,
                    "forward_total_cm": fwd_total,
                    "switch_count": switch_count,
                    "last_direction": action["direction"],
                    "clearance_penalty": clearance_penalty,
                    "min_side_clearance_cm": min_side_clearance,
                    "score_review": sr,
                }
                expanded.append(item)
        expanded.sort(key=lambda n: (
            not n["score_review"].get("success"),
            n["score_review"]["score"],
            -_to_float(n.get("min_side_clearance_cm"), -999.0),
            n["forward_total_cm"],
            n["switch_count"],
        ))
        beam = expanded[:beam_width]
        layers.append({
            "depth": depth,
            "candidate_count": len(expanded),
            "kept_count": len(beam),
            "best_score": None if not beam else beam[0]["score_review"]["score"],
            "best_pose": None if not beam else {k: round(v, 3) for k, v in beam[0]["pose"].items()},
            "best_min_side_clearance_cm": None if not beam else beam[0]["score_review"].get("min_side_clearance_cm"),
        })
        if beam and (best is None or (beam[0]["score_review"]["score"], beam[0]["forward_total_cm"]) < (best["score_review"]["score"], best["forward_total_cm"])):
            best = beam[0]
        if beam and beam[0]["score_review"].get("success"):
            best = beam[0]
            break
    return {
        "schema": "parking_rollout_optimizer_search.v1",
        "stage": stage,
        "horizon": horizon,
        "beam_width": beam_width,
        "action_count_per_node": len(actions),
        "initial_score": initial_score,
        "best": best,
        "layers": layers,
    }


def decide(pose: dict[str, Any], cfg: dict[str, Any],
           reverse_table: list[tuple[int, float, float]],
           forward_table: dict[str, Any] | None = None,
           history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    p = normalize_pose(pose)
    base = {"schema": "parking_rollout_optimizer_decision.v1", "pose": {k: round(v, 3) for k, v in p.items()}}
    if not _state_ok(p, cfg):
        base.update({"mode": "stop_bounds", "reason": "pose_outside_rollout_bounds"})
        return base
    if success(p, cfg):
        base.update({"mode": "depth_reached", "reason": "already_in_success_box"})
        return base
    search = beam_search(p, cfg, reverse_table, forward_table, history=history)
    best = search.get("best")
    if not best or not best.get("actions"):
        base.update({"mode": "no_safe_candidate", "reason": "rollout_no_safe_candidate", "search": {k: v for k, v in search.items() if k != "best"}})
        return base
    first = best["actions"][0]
    mode = "forward_arc" if first["direction"] == "forward" else "reverse_arc"
    compact_best = {
        "score_review": best.get("score_review"),
        "final_pose": {k: round(v, 3) for k, v in best.get("pose", {}).items()},
        "sequence": best.get("actions", [])[:8],
        "sequence_len": len(best.get("actions", [])),
        "forward_total_cm": round(_to_float(best.get("forward_total_cm"), 0.0), 3),
        "switch_count": int(best.get("switch_count", 0)),
        "min_side_clearance_cm": best.get("score_review", {}).get("min_side_clearance_cm"),
        "clearance_penalty": best.get("score_review", {}).get("clearance_penalty"),
    }
    search_log = {k: v for k, v in search.items() if k != "best"}
    search_log["best"] = compact_best
    base.update({
        "mode": mode,
        "reason": "rollout_optimizer_first_action",
        "stage": search.get("stage"),
        "ste": int(first["ste"]),
        "command_cm": round(float(first["command_cm"]), 3),
        "signed_command_cm": round(float(first["signed_command_cm"]), 3),
        "expected_ground_cm": first.get("expected_ground_cm"),
        "deg_per_cm": first.get("deg_per_cm"),
        "predicted_yaw_delta_deg": first.get("yaw_delta_deg"),
        "predicted_pose": first.get("predicted_pose"),
        "kinematics_source": first.get("kinematics_source"),
        "score": compact_best["score_review"].get("score"),
        "score_review": compact_best["score_review"],
        "min_side_clearance_cm": compact_best.get("min_side_clearance_cm"),
        "clearance_penalty": compact_best.get("clearance_penalty"),
        "best_sequence": compact_best["sequence"],
        "search": search_log,
    })
    return base


# ---------------------------------------------------------------------------
# CLI helpers.
# ---------------------------------------------------------------------------


def _parse_pose(text: str) -> dict[str, float]:
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise ValueError("pose must be y_dist_cm,lateral_cm,heading_deg")
    return {"y_dist_cm": float(parts[0]), "lateral_cm": float(parts[1]), "heading_deg": float(parts[2])}


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def replay_jsonl(path: str, cfg: dict[str, Any], reverse_table: list[tuple[int, float, float]],
                 forward_table: dict[str, Any] | None = None, limit: int = 0) -> dict[str, Any]:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("event") != "diy_path_step":
                continue
            pose = obj.get("estimated_pose_before") or obj.get("estimated_pose_after_correction") or {}
            if not pose:
                continue
            d = decide(pose, cfg, reverse_table, forward_table)
            old = obj.get("chosen_action") or {}
            rows.append({
                "step": obj.get("steps") or obj.get("step_index"),
                "pose": normalize_pose(pose),
                "old_cmd": old.get("cmd") or (old.get("action") or {}).get("cmd"),
                "new_mode": d.get("mode"),
                "new_cmd": None if d.get("mode") not in ("reverse_arc", "forward_arc") else "ARC D=%+.1f STE=%d V=1" % (d.get("signed_command_cm"), d.get("ste")),
                "stage": d.get("stage"),
                "score": d.get("score"),
            })
            if limit and len(rows) >= limit:
                break
    return {"schema": "parking_rollout_optimizer_replay.v1", "source": path, "rows": rows, "count": len(rows)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kinematics", default="configs/chassis_kinematics.json")
    ap.add_argument("--forward-kinematics", default="")
    ap.add_argument("--config", default="")
    ap.add_argument("--decide", default="")
    ap.add_argument("--replay-jsonl", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    kin = _load_json(args.kinematics)
    overrides = _load_json(args.config) if args.config else {}
    cfg = merged_config(kin, overrides)
    fwd_path = args.forward_kinematics or cfg.get("forward_kinematics_json") or ""
    fwd = load_forward_kinematics(fwd_path)
    table = build_curvature_table(kin)
    if args.decide:
        print(json.dumps(decide(_parse_pose(args.decide), cfg, table, fwd), ensure_ascii=False, indent=2))
        return 0
    if args.replay_jsonl:
        print(json.dumps(replay_jsonl(args.replay_jsonl, cfg, table, fwd, limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    ap.error("provide --decide or --replay-jsonl")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
