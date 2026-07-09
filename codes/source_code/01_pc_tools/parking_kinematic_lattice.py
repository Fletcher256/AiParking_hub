#!/usr/bin/env python3
"""Measured-kinematics lattice planner for low-speed reverse parking.

This module is deliberately self-contained so it can run both on the board and
offline on a PC.  It replaces the earlier "accumulate visual lines / belief
keeps driving" idea with a conservative motion-primitive lattice:

  reliable current slot pose -> measured chassis primitive prediction
  -> rank bounded candidates -> execute only the first short primitive
  -> stop/observe/replan in the controller

The model does not assume ideal Ackermann steering.  It reads the project
`chassis_kinematics.json` table and uses measured `deg_per_cm` per servo value.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "parking_kinematic_lattice_plan.v1"
DEFAULT_SERVO_CENTER = 100.0
DEFAULT_DISTANCES_CM = (3.0, 4.0, 6.0)
DEFAULT_LOOKAHEAD_DEPTH = 2
DEFAULT_CAUTIOUS_CONFIG = {
    "enable": True,
    "min_confidence": 0.85,
    "min_visible_ratio": 0.08,
    "min_margin_px": 90.0,
    "min_pose_quality": 0.70,
    "min_y_dist_cm": 18.0,
    "max_y_dist_cm": 90.0,
    "max_abs_lateral_cm": 18.0,
    "max_abs_heading_deg": 32.0,
    "max_abs_x_err_px": 90.0,
    "max_corridor_extrapolation_px": 320.0,
    "max_distance_cm": 3.0,
    "lookahead_depth": 1,
    "allowed_statuses": ("complete", "trusted", "suspect", "disabled"),
    "allowed_quad_fit_statuses": ("complete", "partial_usable"),
    "allow_suspect_topology": True,
    "require_entry_edge_visible": True,
    "require_geometry_planning_allowed": True,
    "fatal_geometry_reasons": (
        "quad_not_four_points",
        "quad_area_too_small",
        "quad_self_intersect",
        "left_right_reversed",
        "quad_edge_crosses_interior",
        "quad_center_far_from_mask",
        "quad_mask_area_mismatch",
        "mask_fill_low",
        "near_image_border",
        "class_incomplete_hint",
    ),
}
DEFAULT_TERMINAL_CAUTIOUS_CONFIG = {
    "enable": True,
    # Terminal mode is still visual closed-loop, not blind reverse.  It exists
    # to finish the last visible centimeters with even shorter commands than
    # normal cautious mode, especially when the slot mask is close/partial.
    "min_confidence": 0.85,
    "min_visible_ratio": 0.05,
    "min_margin_px": 80.0,
    "min_pose_quality": 0.65,
    "min_y_dist_cm": 8.0,
    "max_y_dist_cm": 22.0,
    "max_abs_lateral_cm": 8.0,
    "max_abs_heading_deg": 14.0,
    "max_abs_x_err_px": 55.0,
    "max_corridor_extrapolation_px": 260.0,
    "max_distance_cm": 2.5,
    "lookahead_depth": 1,
    "allowed_statuses": ("complete", "trusted", "suspect", "disabled"),
    "allowed_quad_fit_statuses": ("complete", "partial_usable"),
    "allow_suspect_topology": True,
    "require_entry_edge_visible": False,
    "require_geometry_planning_allowed": True,
    "fatal_geometry_reasons": DEFAULT_CAUTIOUS_CONFIG["fatal_geometry_reasons"],
}
DEFAULT_LOW_CONF_CAUTIOUS_CONFIG = {
    "enable": True,
    # Recovery tier for the observed board behavior: after several correct
    # visual short steps the mask geometry can remain stable and spacious while
    # the detector confidence temporarily drops.  Keep this tier stricter on
    # geometry and shorter on motion than normal cautious mode.
    "min_confidence": 0.50,
    "min_visible_ratio": 0.18,
    "min_margin_px": 140.0,
    "min_pose_quality": 0.65,
    "min_y_dist_cm": 18.0,
    "max_y_dist_cm": 70.0,
    "max_abs_lateral_cm": 12.0,
    "max_abs_heading_deg": 28.0,
    "max_abs_x_err_px": 60.0,
    "max_corridor_extrapolation_px": 160.0,
    "max_distance_cm": 2.0,
    "lookahead_depth": 1,
    "max_consecutive_steps": 1,
    "allowed_statuses": ("complete", "trusted", "suspect", "disabled"),
    "allowed_quad_fit_statuses": ("complete",),
    "allow_suspect_topology": False,
    "require_entry_edge_visible": False,
    "require_geometry_planning_allowed": True,
    "require_corridor_sample_reliable": True,
    "fatal_geometry_reasons": DEFAULT_CAUTIOUS_CONFIG["fatal_geometry_reasons"],
}

FAST_LOOP_PROFILE_ALIASES = {"small_car_fast", "fast_loop", "efficiency_first"}
FAST_LOOP_FATAL_GEOMETRY_REASONS = (
    # Keep only shape/pathologies that make the polygon transform actively unsafe.
    # Soft visual imperfections (partial mask, non-four-point quad fit, border touch,
    # corridor extrapolation, class hints) are handled by shorter steps + replanning.
    "quad_area_too_small",
    "quad_self_intersect",
    "left_right_reversed",
    "quad_edge_crosses_interior",
)
FAST_LOOP_VISUAL_DEFAULTS = {
    "min_confidence": 0.40,
    "min_visible_ratio": 0.04,
    "require_can_refresh_geometry": False,
    "require_reliable_geometry": False,
    "require_corridor_sample_reliable": False,
}
FAST_LOOP_CAUTIOUS_OVERRIDES = {
    "min_confidence": 0.40,
    "min_visible_ratio": 0.04,
    "min_margin_px": 80.0,
    "min_pose_quality": 0.45,
    "min_y_dist_cm": 0.0,
    "max_y_dist_cm": 120.0,
    "max_abs_lateral_cm": 26.0,
    "max_abs_heading_deg": 40.0,
    "max_abs_x_err_px": 130.0,
    "max_corridor_extrapolation_px": 9999.0,
    "max_distance_cm": 2.0,
    "lookahead_depth": 1,
    "allowed_statuses": ("complete", "trusted", "suspect", "partial", "unknown", "disabled"),
    "allowed_quad_fit_statuses": ("complete", "partial_usable", "unknown", "cleaned", "fallback", "convex_hull"),
    "allow_suspect_topology": True,
    "require_entry_edge_visible": False,
    "require_geometry_planning_allowed": False,
    "fatal_geometry_reasons": FAST_LOOP_FATAL_GEOMETRY_REASONS,
}
FAST_LOOP_TERMINAL_CAUTIOUS_OVERRIDES = {
    "min_confidence": 0.35,
    "min_visible_ratio": 0.03,
    "min_margin_px": 70.0,
    "min_pose_quality": 0.40,
    "min_y_dist_cm": 0.0,
    "max_y_dist_cm": 35.0,
    "max_abs_lateral_cm": 14.0,
    "max_abs_heading_deg": 28.0,
    "max_abs_x_err_px": 95.0,
    "max_corridor_extrapolation_px": 9999.0,
    "max_distance_cm": 1.5,
    "lookahead_depth": 1,
    "allowed_statuses": ("complete", "trusted", "suspect", "partial", "unknown", "disabled"),
    "allowed_quad_fit_statuses": ("complete", "partial_usable", "unknown", "cleaned", "fallback", "convex_hull"),
    "allow_suspect_topology": True,
    "require_entry_edge_visible": False,
    "require_geometry_planning_allowed": False,
    "fatal_geometry_reasons": FAST_LOOP_FATAL_GEOMETRY_REASONS,
}
FAST_LOOP_LOW_CONF_CAUTIOUS_OVERRIDES = {
    "min_confidence": 0.35,
    "min_visible_ratio": 0.035,
    "min_margin_px": 90.0,
    "min_pose_quality": 0.40,
    "min_y_dist_cm": 0.0,
    "max_y_dist_cm": 120.0,
    "max_abs_lateral_cm": 24.0,
    "max_abs_heading_deg": 38.0,
    "max_abs_x_err_px": 120.0,
    "max_corridor_extrapolation_px": 9999.0,
    "max_distance_cm": 2.0,
    "lookahead_depth": 1,
    "max_consecutive_steps": 999,
    "allowed_statuses": ("complete", "trusted", "suspect", "partial", "unknown", "disabled"),
    "allowed_quad_fit_statuses": ("complete", "partial_usable", "unknown", "cleaned", "fallback", "convex_hull"),
    "allow_suspect_topology": True,
    "require_entry_edge_visible": False,
    "require_geometry_planning_allowed": False,
    "require_corridor_sample_reliable": False,
    "allow_mask_polygon_cleanup": True,
    "fatal_geometry_reasons": FAST_LOOP_FATAL_GEOMETRY_REASONS,
}


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def wrap_deg(angle: float) -> float:
    while angle > 180.0:
        angle -= 360.0
    while angle <= -180.0:
        angle += 360.0
    return angle


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _round(value: Any, digits: int = 3) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def _as_set(value: Any, default: Any = ()) -> set[str]:
    if value is None:
        value = default
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    try:
        return {str(part).strip() for part in value if str(part).strip()}
    except TypeError:
        return {str(value).strip()} if str(value).strip() else set()


def _merge_cautious_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_CAUTIOUS_CONFIG)
    for key, value in (config or {}).items():
        merged[key] = value
    return merged


def _merge_terminal_cautious_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_TERMINAL_CAUTIOUS_CONFIG)
    for key, value in (config or {}).items():
        merged[key] = value
    return merged


def _merge_low_conf_cautious_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_LOW_CONF_CAUTIOUS_CONFIG)
    for key, value in (config or {}).items():
        merged[key] = value
    return merged


def _profile_name(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    return str(cfg.get("safety_profile") or cfg.get("profile") or "standard").strip().lower()


def _is_fast_loop_profile(config_or_name: dict[str, Any] | str | None) -> bool:
    if isinstance(config_or_name, str):
        name = config_or_name.strip().lower()
    else:
        name = _profile_name(config_or_name)
    return name in FAST_LOOP_PROFILE_ALIASES


def _overlay_defaults(config: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    out = dict(config or {})
    for key, value in defaults.items():
        out.setdefault(key, value)
    return out


def _overlay_nested_defaults(config: dict[str, Any], key: str, defaults: dict[str, Any]) -> None:
    nested = dict(config.get(key) or {})
    for nested_key, value in defaults.items():
        nested.setdefault(nested_key, value)
    config[key] = nested


def _apply_visual_quality_profile(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(config or {})
    profile = _profile_name(cfg)
    cfg["safety_profile"] = profile
    if _is_fast_loop_profile(profile):
        cfg = _overlay_defaults(cfg, FAST_LOOP_VISUAL_DEFAULTS)
        _overlay_nested_defaults(cfg, "cautious", FAST_LOOP_CAUTIOUS_OVERRIDES)
        _overlay_nested_defaults(cfg, "terminal_cautious", FAST_LOOP_TERMINAL_CAUTIOUS_OVERRIDES)
        _overlay_nested_defaults(cfg, "low_conf_cautious", FAST_LOOP_LOW_CONF_CAUTIOUS_OVERRIDES)
    return cfg


def _kin_rows(kinematics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in (kinematics or {}).get("steer_curvature", []):
        if row.get("ste") is None or row.get("deg_per_cm") is None:
            continue
        try:
            rows.append(dict(row))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: to_float(r.get("ste")))
    return rows


def servo_center(kinematics: dict[str, Any], default: float = DEFAULT_SERVO_CENTER) -> float:
    return to_float((kinematics or {}).get("servo_center_trim_ste"), default)


def deg_per_cm_for_servo(kinematics: dict[str, Any], servo: float) -> tuple[float, str]:
    """Return measured/interpolated yaw change in deg per actual cm.

    Positive sign follows the STM32/board convention already captured in
    `chassis_signs.json`: clockwise yaw is positive.  For reverse parking this
    matches the existing response-model sign: right hard steering increases
    `slot_heading_err_deg`, left hard steering decreases it.
    """
    center = servo_center(kinematics)
    if abs(float(servo) - center) < 1e-6:
        return 0.0, "servo_center"
    rows = _kin_rows(kinematics)
    exact = [
        r for r in rows
        if int(round(to_float(r.get("ste")))) == int(round(float(servo)))
    ]
    if exact:
        return to_float(exact[0].get("deg_per_cm")), "measured_exact"
    if not rows:
        return 0.0, "missing_kinematics"
    below = None
    above = None
    for row in rows:
        ste = to_float(row.get("ste"))
        if ste < servo:
            below = row
        elif ste > servo and above is None:
            above = row
    if below is not None and above is not None:
        lo_ste = to_float(below.get("ste"))
        hi_ste = to_float(above.get("ste"))
        t = (float(servo) - lo_ste) / max(1e-6, hi_ste - lo_ste)
        lo = to_float(below.get("deg_per_cm"))
        hi = to_float(above.get("deg_per_cm"))
        return lo + (hi - lo) * t, "measured_interpolated"
    nearest = min(rows, key=lambda r: abs(to_float(r.get("ste")) - float(servo)))
    return to_float(nearest.get("deg_per_cm")), "nearest_measured"


def actual_progress_cm(kinematics: dict[str, Any], command_abs_cm: float, servo: float) -> tuple[float, dict[str, Any]]:
    """Estimate actual reverse progress for a commanded primitive.

    The board command uses negative D for reverse, but all planner state uses
    positive progress toward the slot.  The command deadband is measured on this
    specific chassis; clamp to the command magnitude to avoid optimistic travel.
    """
    center = servo_center(kinematics)
    command_abs_cm = abs(float(command_abs_cm))
    if command_abs_cm <= 0.0:
        return 0.0, {"command_abs_cm": 0.0, "reason": "zero_command"}
    if abs(float(servo) - center) < 1e-6:
        deadband = to_float(kinematics.get("move_deadband_cm"), to_float(kinematics.get("arc_deadband_cm"), 2.0))
    else:
        deadband = to_float(kinematics.get("arc_deadband_cm"), 2.0)
    coast = to_float(kinematics.get("coast_after_done_cm"), 0.0)
    # Keep a modest lower bound for 3cm micro-arcs; the real logs show they can
    # still move about 1cm after the deadband.
    progress = max(0.0, command_abs_cm - deadband + coast)
    if command_abs_cm >= 3.0 and progress < 0.8:
        progress = 0.8
    progress = min(command_abs_cm, progress)
    return progress, {
        "command_abs_cm": round(command_abs_cm, 3),
        "deadband_cm": round(deadband, 3),
        "coast_after_done_cm": round(coast, 3),
        "actual_progress_cm": round(progress, 3),
    }


def signed_px_per_lateral_cm(state: dict[str, Any]) -> float:
    lat = to_float(state.get("slot_lateral_cm"))
    x_px = to_float(state.get("slot_x_err_px"))
    if abs(lat) >= 1.0 and abs(x_px) >= 1.0:
        ratio = x_px / lat
        return math.copysign(clamp(abs(ratio), 1.0, 12.0), ratio)
    # Historical board geometry often has opposite signs for image x and ground
    # lateral, e.g. slot_lateral=-12cm with slot_x_err=+22px.
    return -4.0


def predict_after_primitive(
    state: dict[str, Any],
    primitive: dict[str, Any],
    kinematics: dict[str, Any],
) -> dict[str, Any]:
    command_cm = to_float(primitive.get("distance_cm"))
    servo = to_float(primitive.get("servo"), servo_center(kinematics))
    progress_cm, progress_meta = actual_progress_cm(kinematics, command_cm, servo)
    deg_per_cm, curvature_source = deg_per_cm_for_servo(kinematics, servo)
    dpsi_deg = deg_per_cm * progress_cm
    dpsi_rad = math.radians(dpsi_deg)
    yaw_mid = math.radians(dpsi_deg * 0.5)

    # Pose increment of the vehicle in the previous vehicle frame.
    dx = progress_cm * math.cos(yaw_mid)
    dy = -progress_cm * math.sin(yaw_mid)

    # Fixed slot target expressed in the new vehicle frame.
    x = to_float(state.get("slot_y_dist_cm"))
    y = to_float(state.get("slot_lateral_cm"))
    c = math.cos(dpsi_rad)
    s = math.sin(dpsi_rad)
    nx = c * (x - dx) - s * (y - dy)
    ny = s * (x - dx) + c * (y - dy)

    pred = dict(state)
    pred["slot_y_dist_cm"] = nx
    pred["slot_lateral_cm"] = ny
    pred["slot_heading_err_deg"] = wrap_deg(to_float(state.get("slot_heading_err_deg")) + dpsi_deg)

    px_per_cm = signed_px_per_lateral_cm(state)
    pred["slot_x_err_px"] = ny * px_per_cm
    if state.get("slot_entry_x_err_px") is not None:
        pred["slot_entry_x_err_px"] = pred["slot_x_err_px"]

    min_margin = to_float(state.get("min_margin_px"))
    margin_loss = (
        max(0.0, abs(ny) - abs(y)) * abs(px_per_cm) * 0.65
        + abs(dpsi_deg) * 1.8
        + progress_cm * 0.15
    )
    pred["min_margin_px"] = min_margin - margin_loss
    pred["line_risk"] = bool(pred["min_margin_px"] < 40.0)
    pred["_motion_model"] = {
        "servo": round(servo, 3),
        "distance_cm": round(command_cm, 3),
        "actual_progress_cm": round(progress_cm, 3),
        "deg_per_cm": round(deg_per_cm, 6),
        "dpsi_deg": round(dpsi_deg, 3),
        "dx_cm": round(dx, 3),
        "dy_cm": round(dy, 3),
        "curvature_source": curvature_source,
        "progress_model": progress_meta,
        "px_per_lateral_cm": round(px_per_cm, 3),
        "margin_loss_px": round(margin_loss, 3),
    }
    return pred


def visual_quality_review(state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _apply_visual_quality_profile(config)
    profile = _profile_name(cfg)
    min_conf = to_float(cfg.get("min_confidence"), 0.75)
    min_visible = to_float(cfg.get("min_visible_ratio"), 0.18)
    require_refresh = to_bool(cfg.get("require_can_refresh_geometry", True))
    require_reliable_geometry = to_bool(cfg.get("require_reliable_geometry", True))
    require_corridor_sample = to_bool(cfg.get("require_corridor_sample_reliable", True))
    cautious_cfg = _merge_cautious_config(cfg.get("cautious") or {})
    terminal_cfg = _merge_terminal_cautious_config(cfg.get("terminal_cautious") or {})
    low_conf_cfg = _merge_low_conf_cautious_config(cfg.get("low_conf_cautious") or {})

    status = state.get("slot_completeness_status")
    status_ok = status in ("complete", "trusted", "disabled")
    if status is None and not require_refresh:
        status_ok = True
    spike_suppressed = to_bool(state.get("spike_suppression_applied")) or to_bool(state.get("mask_polygon_cleanup_applied"))
    checks = {
        "stable": to_bool(state.get("stable")),
        "stable_enough": to_bool(state.get("stable_enough")),
        "line_margin_ok": to_bool(state.get("line_margin_ok")),
        "line_risk_clear": not to_bool(state.get("line_risk")),
        "no_mask_polygon_spike_suppression": not spike_suppressed,
        "confidence_ok": to_float(state.get("confidence")) >= min_conf,
        "visible_ratio_ok": to_float(state.get("slot_visible_ratio"), 1.0) >= min_visible,
        "entry_edge_visible": to_bool(state.get("entry_edge_visible")),
        "status_ok": status_ok,
        "can_refresh_geometry": (not require_refresh) or to_bool(state.get("slot_completeness_can_refresh_geometry")),
        "geometry_reliable": (not require_reliable_geometry) or to_bool(state.get("geometry_reliable")),
        "quad_topology_valid": (not require_reliable_geometry) or to_bool(state.get("quad_topology_valid")),
        "corridor_sample_reliable": (not require_corridor_sample) or to_bool(state.get("corridor_sample_reliable")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    strict_pass = not failed

    completeness_reasons = list(state.get("slot_completeness_reasons") or [])
    quad_reasons = list(state.get("quad_topology_reasons") or [])
    fit_reasons = list(state.get("quad_fit_reasons") or [])
    geometry_reasons = sorted(set(str(r) for r in completeness_reasons + quad_reasons + fit_reasons if str(r)))
    fatal_reasons = _as_set(cautious_cfg.get("fatal_geometry_reasons"), DEFAULT_CAUTIOUS_CONFIG["fatal_geometry_reasons"])
    fatal_hits = sorted(set(geometry_reasons).intersection(fatal_reasons))
    allowed_statuses = _as_set(cautious_cfg.get("allowed_statuses"), DEFAULT_CAUTIOUS_CONFIG["allowed_statuses"])
    allowed_fit_statuses = _as_set(
        cautious_cfg.get("allowed_quad_fit_statuses"),
        DEFAULT_CAUTIOUS_CONFIG["allowed_quad_fit_statuses"],
    )
    fit_status = state.get("quad_fit_status")
    topology_ok = (
        to_bool(state.get("quad_topology_valid")) or
        (to_bool(cautious_cfg.get("allow_suspect_topology", True)) and not fatal_hits)
    )
    corridor_extrap = to_float(state.get("corridor_sample_extrapolation_px"), 0.0)
    geometry_planning_ok = (
        (not to_bool(cautious_cfg.get("require_geometry_planning_allowed", True))) or
        to_bool(state.get("geometry_planning_allowed")) or
        to_bool(state.get("geometry_planning_usable"))
    )
    corridor_or_planning_ok = (
        to_bool(state.get("corridor_sample_reliable")) or
        (
            geometry_planning_ok and
            corridor_extrap <= to_float(cautious_cfg.get("max_corridor_extrapolation_px"), 320.0)
        )
    )
    y_dist = to_float(state.get("slot_y_dist_cm"))
    lat_abs = abs(to_float(state.get("slot_lateral_cm")))
    heading_abs = abs(to_float(state.get("slot_heading_err_deg")))
    x_abs = abs(to_float(state.get("slot_x_err_px")))
    cautious_checks = {
        "enabled": to_bool(cautious_cfg.get("enable", True)),
        "stable": to_bool(state.get("stable")),
        "stable_enough": to_bool(state.get("stable_enough")),
        "line_risk_clear": not to_bool(state.get("line_risk")),
        "line_margin_ok": to_bool(state.get("line_margin_ok")),
        "confidence_ok": to_float(state.get("confidence")) >= to_float(cautious_cfg.get("min_confidence"), 0.85),
        "visible_ratio_ok": to_float(state.get("slot_visible_ratio"), 0.0) >= to_float(cautious_cfg.get("min_visible_ratio"), 0.08),
        "entry_edge_visible": (
            (not to_bool(cautious_cfg.get("require_entry_edge_visible", True))) or
            to_bool(state.get("entry_edge_visible"))
        ),
        "status_allowed": (status in allowed_statuses) or (status is None and "unknown" in allowed_statuses),
        "quad_fit_allowed": (fit_status in allowed_fit_statuses) or (fit_status is None and "unknown" in allowed_fit_statuses),
        "no_fatal_geometry_reasons": not fatal_hits,
        "geometry_planning_allowed": geometry_planning_ok,
        "topology_or_nonfatal_suspect": topology_ok,
        "corridor_sample_or_planning": corridor_or_planning_ok,
        "margin_ok": to_float(state.get("min_margin_px")) >= to_float(cautious_cfg.get("min_margin_px"), 90.0),
        "pose_quality_ok": to_float(state.get("pose_quality")) >= to_float(cautious_cfg.get("min_pose_quality"), 0.70),
        "y_dist_min_ok": y_dist >= to_float(cautious_cfg.get("min_y_dist_cm"), 18.0),
        "y_dist_max_ok": y_dist <= to_float(cautious_cfg.get("max_y_dist_cm"), 90.0),
        "lateral_ok": lat_abs <= to_float(cautious_cfg.get("max_abs_lateral_cm"), 18.0),
        "heading_ok": heading_abs <= to_float(cautious_cfg.get("max_abs_heading_deg"), 32.0),
        "x_err_ok": x_abs <= to_float(cautious_cfg.get("max_abs_x_err_px"), 90.0),
    }
    cautious_failed = [name for name, ok in cautious_checks.items() if not ok]
    cautious_pass = (not strict_pass) and not cautious_failed
    terminal_fatal_reasons = _as_set(
        terminal_cfg.get("fatal_geometry_reasons"),
        DEFAULT_TERMINAL_CAUTIOUS_CONFIG["fatal_geometry_reasons"],
    )
    terminal_fatal_hits = sorted(set(geometry_reasons).intersection(terminal_fatal_reasons))
    terminal_allowed_statuses = _as_set(
        terminal_cfg.get("allowed_statuses"),
        DEFAULT_TERMINAL_CAUTIOUS_CONFIG["allowed_statuses"],
    )
    terminal_allowed_fit_statuses = _as_set(
        terminal_cfg.get("allowed_quad_fit_statuses"),
        DEFAULT_TERMINAL_CAUTIOUS_CONFIG["allowed_quad_fit_statuses"],
    )
    terminal_topology_ok = (
        to_bool(state.get("quad_topology_valid")) or
        (to_bool(terminal_cfg.get("allow_suspect_topology", True)) and not terminal_fatal_hits)
    )
    terminal_geometry_planning_ok = (
        (not to_bool(terminal_cfg.get("require_geometry_planning_allowed", True))) or
        to_bool(state.get("geometry_planning_allowed")) or
        to_bool(state.get("geometry_planning_usable"))
    )
    terminal_corridor_or_planning_ok = (
        to_bool(state.get("corridor_sample_reliable")) or
        (
            terminal_geometry_planning_ok and
            corridor_extrap <= to_float(terminal_cfg.get("max_corridor_extrapolation_px"), 260.0)
        )
    )
    terminal_checks = {
        "enabled": to_bool(terminal_cfg.get("enable", True)),
        "stable": to_bool(state.get("stable")),
        "stable_enough": to_bool(state.get("stable_enough")),
        "line_risk_clear": not to_bool(state.get("line_risk")),
        "line_margin_ok": to_bool(state.get("line_margin_ok")),
        "confidence_ok": to_float(state.get("confidence")) >= to_float(terminal_cfg.get("min_confidence"), 0.85),
        "visible_ratio_ok": to_float(state.get("slot_visible_ratio"), 0.0) >= to_float(terminal_cfg.get("min_visible_ratio"), 0.05),
        "entry_edge_visible": (
            (not to_bool(terminal_cfg.get("require_entry_edge_visible", False))) or
            to_bool(state.get("entry_edge_visible"))
        ),
        "status_allowed": (
            status in terminal_allowed_statuses or
            (status is None and "unknown" in terminal_allowed_statuses)
        ),
        "quad_fit_allowed": (
            fit_status in terminal_allowed_fit_statuses or
            (fit_status is None and "unknown" in terminal_allowed_fit_statuses)
        ),
        "no_fatal_geometry_reasons": not terminal_fatal_hits,
        "geometry_planning_allowed": terminal_geometry_planning_ok,
        "topology_or_nonfatal_suspect": terminal_topology_ok,
        "corridor_sample_or_planning": terminal_corridor_or_planning_ok,
        "margin_ok": to_float(state.get("min_margin_px")) >= to_float(terminal_cfg.get("min_margin_px"), 80.0),
        "pose_quality_ok": to_float(state.get("pose_quality")) >= to_float(terminal_cfg.get("min_pose_quality"), 0.65),
        "y_dist_min_ok": y_dist >= to_float(terminal_cfg.get("min_y_dist_cm"), 8.0),
        "y_dist_max_ok": y_dist <= to_float(terminal_cfg.get("max_y_dist_cm"), 22.0),
        "lateral_ok": lat_abs <= to_float(terminal_cfg.get("max_abs_lateral_cm"), 8.0),
        "heading_ok": heading_abs <= to_float(terminal_cfg.get("max_abs_heading_deg"), 14.0),
        "x_err_ok": x_abs <= to_float(terminal_cfg.get("max_abs_x_err_px"), 55.0),
    }
    terminal_failed = [name for name, ok in terminal_checks.items() if not ok]
    terminal_cautious_pass = not terminal_failed
    low_conf_fatal_reasons = _as_set(
        low_conf_cfg.get("fatal_geometry_reasons"),
        DEFAULT_LOW_CONF_CAUTIOUS_CONFIG["fatal_geometry_reasons"],
    )
    low_conf_fatal_hits = sorted(set(geometry_reasons).intersection(low_conf_fatal_reasons))
    low_conf_allowed_statuses = _as_set(
        low_conf_cfg.get("allowed_statuses"),
        DEFAULT_LOW_CONF_CAUTIOUS_CONFIG["allowed_statuses"],
    )
    low_conf_allowed_fit_statuses = _as_set(
        low_conf_cfg.get("allowed_quad_fit_statuses"),
        DEFAULT_LOW_CONF_CAUTIOUS_CONFIG["allowed_quad_fit_statuses"],
    )
    low_conf_topology_ok = (
        to_bool(state.get("quad_topology_valid")) or
        (to_bool(low_conf_cfg.get("allow_suspect_topology", False)) and not low_conf_fatal_hits)
    )
    low_conf_geometry_planning_ok = (
        (not to_bool(low_conf_cfg.get("require_geometry_planning_allowed", True))) or
        to_bool(state.get("geometry_planning_allowed")) or
        to_bool(state.get("geometry_planning_usable"))
    )
    low_conf_corridor_ok = (
        (not to_bool(low_conf_cfg.get("require_corridor_sample_reliable", True))) or
        to_bool(state.get("corridor_sample_reliable"))
    )
    low_conf_corridor_or_planning_ok = (
        low_conf_corridor_ok and
        low_conf_geometry_planning_ok and
        corridor_extrap <= to_float(low_conf_cfg.get("max_corridor_extrapolation_px"), 160.0)
    )
    low_conf_streak = int(to_float(state.get("low_conf_cautious_streak"), 0))
    low_conf_max_streak = max(0, int(to_float(low_conf_cfg.get("max_consecutive_steps"), 2)))
    low_conf_checks = {
        "enabled": to_bool(low_conf_cfg.get("enable", True)),
        "stable": to_bool(state.get("stable")),
        "stable_enough": to_bool(state.get("stable_enough")),
        "line_risk_clear": not to_bool(state.get("line_risk")),
        "line_margin_ok": to_bool(state.get("line_margin_ok")),
        "no_mask_polygon_spike_suppression": (
            (not spike_suppressed) or
            to_bool(low_conf_cfg.get("allow_mask_polygon_cleanup", False))
        ),
        "confidence_ok": to_float(state.get("confidence")) >= to_float(low_conf_cfg.get("min_confidence"), 0.50),
        "visible_ratio_ok": to_float(state.get("slot_visible_ratio"), 0.0) >= to_float(low_conf_cfg.get("min_visible_ratio"), 0.18),
        "entry_edge_visible": (
            (not to_bool(low_conf_cfg.get("require_entry_edge_visible", False))) or
            to_bool(state.get("entry_edge_visible"))
        ),
        "status_allowed": (
            status in low_conf_allowed_statuses or
            (status is None and "unknown" in low_conf_allowed_statuses)
        ),
        "quad_fit_allowed": (
            fit_status in low_conf_allowed_fit_statuses or
            (fit_status is None and "unknown" in low_conf_allowed_fit_statuses)
        ),
        "no_fatal_geometry_reasons": not low_conf_fatal_hits,
        "geometry_planning_allowed": low_conf_geometry_planning_ok,
        "topology_valid": low_conf_topology_ok,
        "corridor_sample_and_planning": low_conf_corridor_or_planning_ok,
        "margin_ok": to_float(state.get("min_margin_px")) >= to_float(low_conf_cfg.get("min_margin_px"), 140.0),
        "pose_quality_ok": to_float(state.get("pose_quality")) >= to_float(low_conf_cfg.get("min_pose_quality"), 0.65),
        "y_dist_min_ok": y_dist >= to_float(low_conf_cfg.get("min_y_dist_cm"), 18.0),
        "y_dist_max_ok": y_dist <= to_float(low_conf_cfg.get("max_y_dist_cm"), 70.0),
        "lateral_ok": lat_abs <= to_float(low_conf_cfg.get("max_abs_lateral_cm"), 12.0),
        "heading_ok": heading_abs <= to_float(low_conf_cfg.get("max_abs_heading_deg"), 28.0),
        "x_err_ok": x_abs <= to_float(low_conf_cfg.get("max_abs_x_err_px"), 60.0),
        "consecutive_step_cap_ok": low_conf_streak < low_conf_max_streak,
    }
    low_conf_failed = [name for name, ok in low_conf_checks.items() if not ok]
    low_conf_cautious_pass = not low_conf_failed
    if terminal_cautious_pass:
        tier = "terminal_cautious"
        reason = "small_car_terminal_cautious_visual_quality_pass"
    elif strict_pass:
        tier = "full"
        reason = "strict_visual_quality_pass"
    elif cautious_pass:
        tier = "cautious"
        reason = "small_car_cautious_visual_quality_pass"
    elif low_conf_cautious_pass:
        tier = "stable_geometry_low_conf_cautious"
        reason = "stable_geometry_low_conf_cautious_visual_quality_pass"
    else:
        tier = "reject"
        reason = "visual_quality_reject"
    return {
        "schema": "parking_lattice_visual_quality.v1",
        "pass": tier in ("full", "cautious", "terminal_cautious", "stable_geometry_low_conf_cautious"),
        "tier": tier,
        "strict_pass": strict_pass,
        "cautious_pass": cautious_pass,
        "terminal_cautious_pass": terminal_cautious_pass,
        "low_conf_cautious_pass": low_conf_cautious_pass,
        "reason": reason,
        "failed_checks": failed,
        "checks": checks,
        "cautious_failed_checks": cautious_failed,
        "cautious_checks": cautious_checks,
        "terminal_cautious_failed_checks": terminal_failed,
        "terminal_cautious_checks": terminal_checks,
        "low_conf_cautious_failed_checks": low_conf_failed,
        "low_conf_cautious_checks": low_conf_checks,
        "metrics": {
            "confidence": round(to_float(state.get("confidence")), 4),
            "slot_visible_ratio": round(to_float(state.get("slot_visible_ratio"), 0.0), 6),
            "slot_completeness_status": status,
            "slot_completeness_reasons": completeness_reasons,
            "geometry_action": state.get("geometry_action"),
            "geometry_planning_allowed": to_bool(state.get("geometry_planning_allowed")),
            "geometry_planning_usable": to_bool(state.get("geometry_planning_usable")),
            "quad_fit_status": fit_status,
            "quad_fit_input_source": state.get("quad_fit_input_source"),
            "spike_suppression_applied": spike_suppressed,
            "quad_topology_valid": to_bool(state.get("quad_topology_valid")),
            "quad_topology_reasons": quad_reasons,
            "quad_fit_reasons": fit_reasons,
            "fatal_geometry_reasons": fatal_hits,
            "terminal_fatal_geometry_reasons": terminal_fatal_hits,
            "low_conf_fatal_geometry_reasons": low_conf_fatal_hits,
            "corridor_sample_reliable": to_bool(state.get("corridor_sample_reliable")),
            "corridor_sample_y_source": state.get("corridor_sample_y_source"),
            "corridor_sample_extrapolation_px": _round(state.get("corridor_sample_extrapolation_px")),
            "min_margin_px": _round(state.get("min_margin_px")),
            "pose_quality": _round(state.get("pose_quality")),
            "slot_y_dist_cm": _round(y_dist),
            "slot_lateral_cm_abs": round(lat_abs, 3),
            "slot_heading_err_deg_abs": round(heading_abs, 3),
            "slot_x_err_px_abs": round(x_abs, 3),
            "low_conf_cautious_streak": low_conf_streak,
        },
        "thresholds": {
            "safety_profile": profile,
            "min_confidence": min_conf,
            "min_visible_ratio": min_visible,
            "require_can_refresh_geometry": require_refresh,
            "require_reliable_geometry": require_reliable_geometry,
            "require_corridor_sample_reliable": require_corridor_sample,
            "cautious": cautious_cfg,
            "terminal_cautious": terminal_cfg,
            "low_conf_cautious": low_conf_cfg,
        },
    }


def success_review(state: dict[str, Any], criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    done = (criteria or {}).get("done", {})
    x_abs = abs(to_float(state.get("slot_x_err_px")))
    heading_abs = abs(to_float(state.get("slot_heading_err_deg")))
    y_dist = to_float(state.get("slot_y_dist_cm"))
    min_margin = to_float(state.get("min_margin_px"))
    checks = {
        "slot_x_ok": x_abs <= to_float(done.get("slot_x_err_px_abs_max"), 15.0),
        "heading_ok": heading_abs <= to_float(done.get("slot_heading_err_deg_abs_max"), 4.0),
        "distance_ok": y_dist <= to_float(done.get("slot_y_dist_cm_max"), 10.0),
        "margin_ok": min_margin >= to_float(done.get("min_margin_px_min"), 60.0),
    }
    return {
        "schema": "parking_lattice_success_review.v1",
        "parked": all(checks.values()),
        "checks": checks,
        "metrics": {
            "slot_x_err_px_abs": round(x_abs, 3),
            "slot_heading_err_deg_abs": round(heading_abs, 3),
            "slot_y_dist_cm": round(y_dist, 3),
            "min_margin_px": round(min_margin, 3),
        },
    }


def build_primitives(kinematics: dict[str, Any], config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or {}
    center = servo_center(kinematics)
    distances = cfg.get("distances_cm") or DEFAULT_DISTANCES_CM
    servos = cfg.get("servos")
    if servos is None:
        measured = [to_float(r.get("ste")) for r in _kin_rows(kinematics)]
        servos = sorted(set([center] + measured))
    out: list[dict[str, Any]] = []
    for dist in distances:
        for servo in servos:
            dist_f = to_float(dist)
            servo_f = to_float(servo, center)
            action = "reverse_straight" if abs(servo_f - center) < 1e-6 else "reverse_arc"
            out.append({
                "id": f"{action}_{int(round(dist_f))}_ste{int(round(servo_f))}",
                "action": "ARC",
                "distance_cm": dist_f,
                "servo": servo_f,
                "command": "ARC D=-%.1f STE=%d V=1" % (dist_f, int(round(servo_f))),
            })
    return out


def cost_state(
    pred: dict[str, Any],
    current: dict[str, Any],
    criteria: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
    done = (criteria or {}).get("done", {})
    abort = (criteria or {}).get("abort", {})
    target_y = to_float(done.get("slot_y_dist_cm_max"), 10.0) * 0.8
    min_margin_target = max(60.0, to_float(done.get("min_margin_px_min"), 60.0) + 20.0)
    y_dist = to_float(pred.get("slot_y_dist_cm"))
    x_abs = abs(to_float(pred.get("slot_x_err_px")))
    lat_abs = abs(to_float(pred.get("slot_lateral_cm")))
    heading_abs = abs(to_float(pred.get("slot_heading_err_deg")))
    min_margin = to_float(pred.get("min_margin_px"))
    progress = max(0.0, to_float(current.get("slot_y_dist_cm")) - y_dist)
    overshoot = max(0.0, -y_dist)
    margin_shortfall = max(0.0, min_margin_target - min_margin)
    line_risk = 1.0 if min_margin < to_float(abort.get("min_margin_px_floor"), 40.0) else 0.0
    model = pred.get("_motion_model") or {}
    steer_cost = abs(to_float(model.get("servo"), DEFAULT_SERVO_CENTER) - DEFAULT_SERVO_CENTER) / 45.0
    fast_loop = _is_fast_loop_profile(config)
    if fast_loop:
        # Efficiency-first small-car tuning: prefer making visible progress and
        # let hard blocks + short stop/observe/replan handle uncertainty.
        weights = {
            "x": 0.40,
            "lat": 5.0,
            "heading": 3.5,
            "target_y": 1.1,
            "progress": -2.4,
            "overshoot": 45.0,
            "margin": 2.0,
            "line_risk": 1000.0,
            "steer": 1.0,
        }
    else:
        weights = {
            "x": 0.55,
            "lat": 7.0,
            "heading": 5.0,
            "target_y": 1.6,
            "progress": -1.1,
            "overshoot": 40.0,
            "margin": 3.0,
            "line_risk": 1000.0,
            "steer": 2.0,
        }
    parts = {
        "slot_x_err_abs": x_abs * weights["x"],
        "slot_lateral_abs": lat_abs * weights["lat"],
        "heading_abs": heading_abs * weights["heading"],
        "y_target_abs": abs(y_dist - target_y) * weights["target_y"],
        "progress_bonus": progress * weights["progress"],
        "overshoot": overshoot * weights["overshoot"],
        "margin_shortfall": margin_shortfall * weights["margin"],
        "line_risk": line_risk * weights["line_risk"],
        "steer_cost": steer_cost * weights["steer"],
    }
    return round(sum(parts.values()), 3), {k: round(v, 3) for k, v in parts.items()}


def _block_reasons(pred: dict[str, Any], criteria: dict[str, Any] | None = None) -> list[str]:
    abort = (criteria or {}).get("abort", {})
    reasons = []
    if to_float(pred.get("min_margin_px")) < to_float(abort.get("min_margin_px_floor"), 40.0):
        reasons.append("predicted_margin_below_floor")
    if to_float(pred.get("slot_y_dist_cm")) < -2.0:
        reasons.append("predicted_depth_overshoot")
    if abs(to_float(pred.get("slot_heading_err_deg"))) > 45.0:
        reasons.append("predicted_heading_excessive")
    if abs(to_float(pred.get("slot_lateral_cm"))) > 35.0:
        reasons.append("predicted_lateral_excessive")
    return reasons


def _sequence_cost(
    final_state: dict[str, Any],
    current: dict[str, Any],
    criteria: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
    return cost_state(final_state, current, criteria, config)


def plan_kinematic_lattice(
    state: dict[str, Any],
    kinematics: dict[str, Any],
    criteria: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    safety_profile = _profile_name(cfg)
    if safety_profile == "standard":
        safety_profile = _profile_name(cfg.get("visual_quality") or {})
    visual_cfg = dict(cfg.get("visual_quality") or {})
    if safety_profile != "standard":
        visual_cfg.setdefault("safety_profile", safety_profile)
    cfg["safety_profile"] = safety_profile
    visual = visual_quality_review(state, visual_cfg)
    success = success_review(state, criteria)
    visual_tier = visual.get("tier", "full" if visual.get("pass") else "reject")
    base = {
        "schema": SCHEMA,
        "strategy": "kinematic_lattice_replanner",
        "safety_profile": safety_profile,
        "mode": visual_tier,
        "pre_state": {k: _round(v) for k, v in (state or {}).items() if not str(k).startswith("_")},
        "visual_quality": visual,
        "success_review": success,
    }
    if not visual.get("pass"):
        return base | {
            "status": "wait_unreliable_visual",
            "chosen": {
                "action_id": "WAIT",
                "command": "WAIT",
                "reason": "current_visual_pose_not_reliable",
            },
            "candidates": [],
        }
    if success.get("parked"):
        return base | {
            "status": "parked",
            "chosen": {
                "action_id": "STOP",
                "command": "STOP",
                "reason": "current_visual_success_confirmed",
            },
            "candidates": [],
        }

    primitive_cfg = dict(cfg.get("primitives") or {})
    depth = max(1, int(to_float(cfg.get("lookahead_depth"), DEFAULT_LOOKAHEAD_DEPTH)))
    depth = min(depth, 3)
    if visual_tier in ("cautious", "terminal_cautious", "stable_geometry_low_conf_cautious"):
        visual_cfg = _apply_visual_quality_profile(visual_cfg)
        if visual_tier == "terminal_cautious":
            tier_cfg = _merge_terminal_cautious_config(visual_cfg.get("terminal_cautious") or {})
            default_max_dist = 2.5
            default_depth = 1
        elif visual_tier == "stable_geometry_low_conf_cautious":
            tier_cfg = _merge_low_conf_cautious_config(visual_cfg.get("low_conf_cautious") or {})
            default_max_dist = 2.0
            default_depth = 1
        else:
            tier_cfg = _merge_cautious_config(visual_cfg.get("cautious") or {})
            default_max_dist = 3.0
            default_depth = 1
        max_dist = max(1.0, to_float(tier_cfg.get("max_distance_cm"), default_max_dist))
        distances = primitive_cfg.get("distances_cm") or DEFAULT_DISTANCES_CM
        short_distances = [to_float(d) for d in distances if 0.0 < to_float(d) <= max_dist + 1e-6]
        if not short_distances:
            short_distances = [max_dist]
        primitive_cfg["distances_cm"] = sorted(set(round(d, 3) for d in short_distances))
        depth = min(depth, max(1, int(to_float(tier_cfg.get("lookahead_depth"), default_depth))))
    primitives = build_primitives(kinematics, primitive_cfg)
    first_step_best: dict[str, dict[str, Any]] = {}

    def expand(prefix: list[dict[str, Any]], cur_state: dict[str, Any], remaining: int) -> None:
        for primitive in primitives:
            pred = predict_after_primitive(cur_state, primitive, kinematics)
            reasons = _block_reasons(pred, criteria)
            if reasons:
                cost, parts = cost_state(pred, state, criteria, cfg)
                candidate = {
                    "sequence": [p["id"] for p in prefix + [primitive]],
                    "first_action": primitive,
                    "tier": visual_tier,
                    "predicted": compact_predicted_state(pred),
                    "score": cost + 500.0,
                    "cost_parts": parts,
                    "hard_blocked": True,
                    "block_reasons": reasons,
                }
            else:
                cost, parts = _sequence_cost(pred, state, criteria, cfg)
                candidate = {
                    "sequence": [p["id"] for p in prefix + [primitive]],
                    "first_action": primitive,
                    "tier": visual_tier,
                    "predicted": compact_predicted_state(pred),
                    "score": cost,
                    "cost_parts": parts,
                    "hard_blocked": False,
                    "block_reasons": [],
                }
                if remaining > 1:
                    expand(prefix + [primitive], pred, remaining - 1)
            first_id = primitive["id"]
            prev = first_step_best.get(first_id)
            if prev is None or candidate["score"] < prev["score"]:
                first_step_best[first_id] = candidate

    expand([], dict(state), depth)
    candidates = sorted(first_step_best.values(), key=lambda c: (c.get("hard_blocked", False), c["score"]))
    eligible = [c for c in candidates if not c.get("hard_blocked")]
    safe_tier = visual_tier in ("cautious", "terminal_cautious", "stable_geometry_low_conf_cautious")
    if not eligible:
        stop_status = (
            "stop_no_safe_%s_primitive" % visual_tier
            if safe_tier else
            "stop_no_safe_primitive"
        )
        stop_reason = (
            "no_safe_%s_kinematic_primitive" % visual_tier
            if safe_tier else
            "no_safe_kinematic_primitive"
        )
        return base | {
            "status": stop_status,
            "chosen": {
                "action_id": "STOP",
                "command": "STOP",
                "reason": stop_reason,
            },
            "candidates": candidates[:12],
        }
    best = eligible[0]
    first = best["first_action"]
    chosen = {
        "action_id": first["id"],
        "command": first["command"],
        "reason": (
            "%s_short_step_replan" % visual_tier
            if safe_tier else
            "best_measured_kinematic_lattice"
        ),
        "tier": visual_tier,
        "score": best["score"],
        "servo": first["servo"],
        "step": first["distance_cm"],
        "predicted": best["predicted"],
        "sequence": best["sequence"],
    }
    return base | {
        "status": "ok_%s" % visual_tier if safe_tier else "ok",
        "chosen": chosen,
        "candidates": candidates[:12],
    }


def compact_predicted_state(pred: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot_y_dist_cm": round(to_float(pred.get("slot_y_dist_cm")), 3),
        "slot_lateral_cm": round(to_float(pred.get("slot_lateral_cm")), 3),
        "slot_x_err_px": round(to_float(pred.get("slot_x_err_px")), 3),
        "slot_heading_err_deg": round(to_float(pred.get("slot_heading_err_deg")), 3),
        "min_margin_px": round(to_float(pred.get("min_margin_px")), 3),
        "line_risk": to_bool(pred.get("line_risk")),
        "motion_model": pred.get("_motion_model"),
    }


def controller_action_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    chosen = plan.get("chosen") or {}
    command = chosen.get("command", "WAIT")
    if command == "WAIT":
        action = "WAIT"
        step = 0.0
        servo = DEFAULT_SERVO_CENTER
    elif command == "STOP":
        action = "STOP"
        step = 0.0
        servo = DEFAULT_SERVO_CENTER
    else:
        action = "ARC"
        step = to_float(chosen.get("step"))
        servo = to_float(chosen.get("servo"), DEFAULT_SERVO_CENTER)
    return {
        "state": "KINEMATIC_LATTICE_REPLANNER",
        "action": action,
        "cmd": command,
        "step": step,
        "servo": servo,
        "reason": chosen.get("reason", plan.get("status")),
        "binding": {
            "action_id": chosen.get("action_id"),
            "score": chosen.get("score"),
            "status": plan.get("status"),
            "tier": chosen.get("tier", plan.get("mode")),
        },
        "kinematic_lattice": plan,
    }


def flat_state_from_rel_state(rel: dict[str, Any], stable: bool | None = None) -> dict[str, Any]:
    image = rel.get("image") or {}
    corridor = rel.get("corridor") or {}
    ground = rel.get("ground_estimate") or {}
    gates = rel.get("gates") or {}
    visibility = rel.get("visibility") or rel.get("vision") or {}
    completeness = rel.get("completeness") or {}
    geometry = rel.get("geometry") or {}
    return {
        "stable": to_bool(rel.get("stable", stable if stable is not None else True)),
        "stable_enough": to_bool(gates.get("stable_enough", True)),
        "line_margin_ok": to_bool(gates.get("line_margin_ok", True)),
        "heading_ok": to_bool(gates.get("heading_ok", True)),
        "lateral_ok": to_bool(gates.get("lateral_ok", True)),
        "line_risk": to_bool(corridor.get("line_risk", False)),
        "phase_hint": rel.get("phase_hint") or "unknown",
        "confidence": to_float(rel.get("confidence")),
        "pose_quality": to_float(rel.get("pose_quality")),
        "slot_x_err_px": to_float(corridor.get("slot_x_err_px")),
        "slot_entry_x_err_px": to_float(corridor.get("slot_entry_x_err_px")),
        "slot_heading_err_deg": to_float(image.get("slot_heading_err_deg")),
        "left_margin_px": to_float(corridor.get("left_margin_px")),
        "right_margin_px": to_float(corridor.get("right_margin_px")),
        "min_margin_px": to_float(corridor.get("min_margin_px")),
        "slot_y_dist_cm": to_float(ground.get("slot_y_dist_cm")),
        "slot_lateral_cm": to_float(ground.get("slot_lateral_cm")),
        "slot_visible_ratio": to_float(visibility.get("slot_visible_ratio"), 0.0),
        "entry_edge_visible": to_bool(visibility.get("entry_edge_visible", True)),
        "slot_completeness_status": completeness.get("status"),
        "slot_completeness_can_refresh_geometry": to_bool(completeness.get("can_refresh_geometry")),
        "slot_completeness_reasons": list(completeness.get("reasons") or []),
        "geometry_reliable": to_bool(geometry.get("geometry_reliable", gates.get("geometry_reliable", True))),
        "geometry_hard_gate_allowed": to_bool(
            geometry.get("geometry_hard_gate_allowed", gates.get("geometry_hard_gate_allowed", True))),
        "geometry_planning_allowed": to_bool(
            geometry.get("geometry_planning_allowed", gates.get("geometry_planning_allowed", True))),
        "geometry_planning_usable": to_bool(
            geometry.get("geometry_planning_usable", geometry.get("geometry_reliable", True))),
        "quad_topology_valid": to_bool(geometry.get("quad_topology_valid", gates.get("quad_topology_valid", True))),
        "quad_topology_status": geometry.get("quad_topology_status"),
        "quad_topology_reasons": list(geometry.get("quad_topology_reasons") or []),
        "corridor_sample_reliable": to_bool(
            corridor.get("corridor_sample_reliable", geometry.get("corridor_sample_reliable", True))),
        "corridor_sample_y_source": corridor.get("sample_y_source", geometry.get("corridor_sample_y_source")),
        "corridor_sample_extrapolation_px": to_float(
            corridor.get("sample_extrapolation_px", geometry.get("corridor_sample_extrapolation_px")), 0.0),
        "quad_fit_status": geometry.get("quad_fit_status"),
        "quad_fit_input_source": geometry.get("quad_fit_input_source"),
        "spike_suppression_applied": to_bool(
            geometry.get("spike_suppression_applied", (rel.get("vision") or {}).get("spike_suppression_applied", False))),
        "quad_fit_reasons": list(geometry.get("quad_fit_reasons") or []),
        "geometry_action": geometry.get("geometry_action"),
    }


def replay_jsonl(paths: list[Path], kinematics: dict[str, Any], criteria: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    rows = []
    counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rel = obj.get("slot_relative_state")
                if not isinstance(rel, dict):
                    continue
                state = flat_state_from_rel_state(rel, stable=to_bool(obj.get("stable")))
                plan = plan_kinematic_lattice(state, kinematics, criteria, config)
                chosen = plan.get("chosen") or {}
                action_id = str(chosen.get("action_id"))
                status = str(plan.get("status"))
                counts[action_id] = counts.get(action_id, 0) + 1
                status_counts[status] = status_counts.get(status, 0) + 1
                rows.append({
                    "file": str(path),
                    "lineno": lineno,
                    "event": obj.get("event"),
                    "stable": obj.get("stable"),
                    "status": status,
                    "chosen": chosen,
                    "visual_failed_checks": (plan.get("visual_quality") or {}).get("failed_checks"),
                    "pre_state": {k: _round(v) for k, v in state.items() if k in (
                        "slot_y_dist_cm", "slot_lateral_cm", "slot_x_err_px",
                        "slot_heading_err_deg", "min_margin_px", "slot_visible_ratio",
                        "slot_completeness_status", "geometry_reliable",
                        "quad_topology_valid", "corridor_sample_reliable")},
                })
    return {
        "schema": "parking_kinematic_lattice_replay.v1",
        "input_files": [str(p) for p in paths],
        "rows": rows,
        "row_count": len(rows),
        "chosen_counts": counts,
        "status_counts": status_counts,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline measured-kinematics lattice replay")
    ap.add_argument("--kinematics", default="configs/chassis_kinematics.json")
    ap.add_argument("--criteria", default="configs/parking_success_criteria.json")
    ap.add_argument("--config", default="")
    ap.add_argument("--lattice-safety-profile",
                    choices=["standard", "small_car_fast", "fast_loop", "efficiency_first"],
                    default="",
                    help="override replay config safety profile")
    ap.add_argument("--replay", nargs="+", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    kinematics = load_json(args.kinematics)
    criteria = load_json(args.criteria)
    config = load_json(args.config) if args.config else {}
    if args.lattice_safety_profile:
        config["safety_profile"] = args.lattice_safety_profile
    report = replay_jsonl([Path(p) for p in args.replay], kinematics, criteria, config)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({
        "row_count": report["row_count"],
        "chosen_counts": report["chosen_counts"],
        "status_counts": report["status_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
