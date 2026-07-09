#!/usr/bin/env python3
"""Pure configuration and criteria helpers for board_parking_controller.

This module is intentionally stdlib-only and has no board/serial side effects.
It contains the parking success/perception defaults plus the safety/criteria
review helpers that were previously embedded in the monolithic controller.
"""

from __future__ import annotations

import json


DEFAULT_SUCCESS_CRITERIA = {
    "schema": "parking_success_criteria.v1",
    "version": "builtin",
    "done": {
        "slot_x_err_px_abs_max": 15.0,
        "slot_heading_err_deg_abs_max": 4.0,
        "slot_y_dist_cm_max": 10.0,
        "min_margin_px_min": 60.0,
        "required_stable_frames": 3,
    },
    "abort": {
        "min_margin_px_floor": 40.0,
        "vision_lost_sec": 0.5,
        "edge_recovery_enabled": True,
        "edge_recovery_min_margin_px": 30.0,
        "edge_recovery_predicted_min_margin_px": 40.0,
        "edge_recovery_min_margin_gain_px": 5.0,
        "edge_recovery_require_x_improve": True,
        "max_total_cm": 60.0,
        "max_steps": 12,
        "divergence_x_err_px": 200.0,
        "unreliable_geometry_defer_min_margin": True,
        "unreliable_geometry_defer_slot_x_divergence": True,
        "unreliable_geometry_visible_ratio_min": 0.28,
        "unreliable_geometry_hard_divergence_px": 300.0,
        "unreliable_geometry_defer_max_total_cm": 5.0,
        "unreliable_geometry_allow_cautious_planning": True,
        "unreliable_geometry_planning_visible_ratio_min": 0.06,
        "unreliable_geometry_planning_min_margin_px": 80.0,
        "unreliable_geometry_planning_min_confidence": 0.75,
        "unreliable_geometry_planning_max_slot_x_px": 300.0,
        "unreliable_geometry_planning_max_total_cm": 5.0,
    },
}

DEFAULT_PERCEPTION_FILTER = {
    "schema": "perception_filter.v1",
    "required_frames": 5,
    "gate_center_shift_cm": 3.0,
    "gate_yaw_shift_deg": 6.0,
    "gate_static_scale": 0.5,
    "outlier_accept_consecutive": 3,
    "hold_grace_sec": 1.0,
    "hold_max_frames": 4,
    "divergence_debounce_frames": 2,
    "line_risk_debounce_frames": 1,
    "post_motion_guard_enabled": True,
    "post_motion_guard_frames": 5,
    "post_motion_guard_max_heading_jump_deg": 12.0,
    "post_motion_guard_max_lateral_jump_cm": 6.0,
    "post_motion_guard_near_y_dist_cm": 35.0,
    "line_accumulator": {
        "enabled": False,
        "use_for_planning": False,
        "motion_capture": False,
        "min_track_weight": 3.0,
        "max_track_age_sec": 8.0,
        "decay_per_sec": 0.85,
        "moving_weight_scale": 0.7,
        "merge_angle_deg": 8.0,
        "merge_distance_cm": 5.0,
        "merge_overlap_ratio": 0.35,
        "require_edges_for_fused": ["left_edge", "right_edge", "entrance_edge", "back_edge"],
        "require_recent_raw_detection_sec": 0.7,
    },
}

def _deep_update(base, override):
    out = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_update(out[key], value)
        else:
            out[key] = value
    return out


def load_success_criteria(path):
    """Load parking done/abort thresholds, falling back to safe built-ins."""
    if not path:
        return json.loads(json.dumps(DEFAULT_SUCCESS_CRITERIA))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return json.loads(json.dumps(DEFAULT_SUCCESS_CRITERIA))
    return _deep_update(DEFAULT_SUCCESS_CRITERIA, data)


def load_perception_filter(path):
    """Load perception filtering thresholds, falling back to conservative built-ins."""
    if not path:
        return json.loads(json.dumps(DEFAULT_PERCEPTION_FILTER))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return json.loads(json.dumps(DEFAULT_PERCEPTION_FILTER))
    return _deep_update(DEFAULT_PERCEPTION_FILTER, {k: v for k, v in data.items() if v is not None})

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _criteria_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def slot_x_divergence_defer_review(slot_state, abort, slot_x_abs, steps=0, total_cm=0.0):
    """Review whether an early slot-x divergence abort is based on unreliable geometry."""
    visibility = slot_state.get("visibility") or {}
    vision = slot_state.get("vision") or {}
    completeness = slot_state.get("completeness") or {}
    gates = slot_state.get("gates") or {}
    line_accum = slot_state.get("line_accumulator") or {}
    geometry = slot_state.get("geometry") or {}

    enabled = _criteria_bool(abort.get("unreliable_geometry_defer_slot_x_divergence"), True)
    visible_min = _num(abort.get("unreliable_geometry_visible_ratio_min"), 0.28)
    hard_px = _num(abort.get("unreliable_geometry_hard_divergence_px"), 300.0)
    max_total = _num(abort.get("unreliable_geometry_defer_max_total_cm"), 5.0)
    visible_ratio = _num(
        visibility.get("slot_visible_ratio", vision.get("slot_visible_ratio")), 0.0)
    status = completeness.get("status") or vision.get("slot_completeness_status") or "unknown"
    can_refresh = _criteria_bool(
        completeness.get("can_refresh_geometry", gates.get("slot_geometry_complete")), True)
    geometry_reliable = _criteria_bool(
        geometry.get("geometry_reliable", gates.get("geometry_reliable")), True)
    quad_topology_valid = _criteria_bool(
        geometry.get("quad_topology_valid", gates.get("quad_topology_valid")), True)
    geometry_hard_gate_allowed = _criteria_bool(
        geometry.get("geometry_hard_gate_allowed", gates.get("geometry_hard_gate_allowed")), geometry_reliable)
    quad_fit_status = geometry.get("quad_fit_status") or gates.get("quad_fit_status")
    quad_fit_status_known = quad_fit_status is not None
    quad_fit_hard_gate_ok = (
        quad_fit_status in ("complete", "trusted")
        if quad_fit_status_known else
        bool(geometry_hard_gate_allowed and geometry_reliable and quad_topology_valid)
    )
    fused_available = line_accum.get("fused_available")

    low_visible = visible_ratio < visible_min
    incomplete = status not in ("complete", "trusted")
    stale_or_suspect_geometry = (
        incomplete or low_visible or not can_refresh or
        not geometry_reliable or not quad_topology_valid or
        not geometry_hard_gate_allowed or not quad_fit_hard_gate_ok
    )
    early = int(steps) <= 0 or _num(total_cm) <= max_total
    hard_divergence = slot_x_abs > hard_px
    hard_gate_blocked = not geometry_hard_gate_allowed
    defer = bool(
        enabled and
        stale_or_suspect_geometry and
        (early or hard_gate_blocked) and
        not hard_divergence
    )
    return {
        "schema": "slot_x_divergence_defer_review.v1",
        "divergence_deferred": defer,
        "reason": (
            "slot_x_divergence_deferred_unreliable_geometry"
            if defer else "slot_x_divergence_hard_abort_allowed"),
        "checks": {
            "enabled": enabled,
            "early_motion": early,
            "hard_gate_blocked": hard_gate_blocked,
            "unreliable_geometry": stale_or_suspect_geometry,
            "low_visible_ratio": low_visible,
            "incomplete_geometry": incomplete,
            "can_refresh_geometry": can_refresh,
            "geometry_reliable": geometry_reliable,
            "quad_topology_valid": quad_topology_valid,
            "geometry_hard_gate_allowed": geometry_hard_gate_allowed,
            "quad_fit_status_known": quad_fit_status_known,
            "quad_fit_hard_gate_ok": quad_fit_hard_gate_ok,
            "hard_divergence": hard_divergence,
        },
        "metrics": {
            "raw_slot_x_err_px": round(slot_x_abs, 3),
            "slot_visible_ratio": round(visible_ratio, 6),
            "completeness_status": status,
            "completeness_reasons": list(completeness.get("reasons") or []),
            "quad_fit_status": quad_fit_status or "unknown",
            "quad_fit_score": geometry.get("quad_fit_score"),
            "quad_fit_source": geometry.get("quad_fit_source"),
            "quad_fit_reasons": list(geometry.get("quad_fit_reasons") or []),
            "entrance_reliable": geometry.get("entrance_reliable"),
            "side_edges_reliable": geometry.get("side_edges_reliable"),
            "corridor_sample_reliable": geometry.get("corridor_sample_reliable"),
            "corridor_sample_extrapolation_px": geometry.get("corridor_sample_extrapolation_px"),
            "geometry_hard_gate_allowed": geometry_hard_gate_allowed,
            "quad_topology_status": geometry.get("quad_topology_status"),
            "quad_topology_reasons": list(geometry.get("quad_topology_reasons") or []),
            "line_accumulator_fused_available": fused_available,
            "line_accumulator_fused_reject_reason": line_accum.get("fused_reject_reason"),
            "steps": int(steps),
            "total_cm": round(_num(total_cm), 3),
        },
        "thresholds": {
            "visible_ratio_min": visible_min,
            "hard_divergence_px": hard_px,
            "defer_max_total_cm": max_total,
        },
    }


def min_margin_defer_review(slot_state, abort, min_margin, line_risk=False):
    """Review whether a low-margin abort came from unreliable raw quad geometry."""
    visibility = slot_state.get("visibility") or {}
    vision = slot_state.get("vision") or {}
    completeness = slot_state.get("completeness") or {}
    gates = slot_state.get("gates") or {}
    line_accum = slot_state.get("line_accumulator") or {}
    geometry = slot_state.get("geometry") or {}

    enabled = _criteria_bool(abort.get("unreliable_geometry_defer_min_margin"), True)
    visible_min = _num(abort.get("unreliable_geometry_visible_ratio_min"), 0.28)
    floor = _num(abort.get("min_margin_px_floor"), 40.0)
    visible_ratio = _num(
        visibility.get("slot_visible_ratio", vision.get("slot_visible_ratio")), 0.0)
    status = completeness.get("status") or vision.get("slot_completeness_status") or "unknown"
    can_refresh = _criteria_bool(
        completeness.get("can_refresh_geometry", gates.get("slot_geometry_complete")), True)
    geometry_reliable = _criteria_bool(
        geometry.get("geometry_reliable", gates.get("geometry_reliable")), True)
    quad_topology_valid = _criteria_bool(
        geometry.get("quad_topology_valid", gates.get("quad_topology_valid")), True)
    geometry_hard_gate_allowed = _criteria_bool(
        geometry.get("geometry_hard_gate_allowed", gates.get("geometry_hard_gate_allowed")), geometry_reliable)
    quad_fit_status = geometry.get("quad_fit_status") or gates.get("quad_fit_status")
    quad_fit_hard_gate_ok = (
        quad_fit_status in ("complete", "trusted")
        if quad_fit_status is not None else
        bool(geometry_hard_gate_allowed and geometry_reliable and quad_topology_valid)
    )
    low_visible = visible_ratio < visible_min
    incomplete = status not in ("complete", "trusted")
    unreliable_geometry = (
        incomplete or low_visible or not can_refresh or
        not geometry_reliable or not quad_topology_valid or
        not geometry_hard_gate_allowed or not quad_fit_hard_gate_ok
    )
    defer = bool(enabled and not line_risk and unreliable_geometry)
    return {
        "schema": "min_margin_defer_review.v1",
        "min_margin_deferred_unreliable_geometry": defer,
        "reason": (
            "min_margin_deferred_unreliable_raw_quad"
            if defer else "min_margin_hard_abort_allowed"),
        "checks": {
            "enabled": enabled,
            "line_risk": bool(line_risk),
            "unreliable_geometry": bool(unreliable_geometry),
            "low_visible_ratio": bool(low_visible),
            "incomplete_geometry": bool(incomplete),
            "can_refresh_geometry": bool(can_refresh),
            "geometry_reliable": bool(geometry_reliable),
            "quad_topology_valid": bool(quad_topology_valid),
            "geometry_hard_gate_allowed": bool(geometry_hard_gate_allowed),
        },
        "metrics": {
            "raw_min_margin_px": round(_num(min_margin), 3),
            "min_margin_floor_px": round(floor, 3),
            "slot_visible_ratio": round(visible_ratio, 6),
            "completeness_status": status,
            "completeness_reasons": list(completeness.get("reasons") or []),
            "quad_fit_status": quad_fit_status or "unknown",
            "quad_fit_score": geometry.get("quad_fit_score"),
            "quad_fit_source": geometry.get("quad_fit_source"),
            "quad_fit_reasons": list(geometry.get("quad_fit_reasons") or []),
            "geometry_hard_gate_allowed": bool(geometry_hard_gate_allowed),
            "quad_topology_status": geometry.get("quad_topology_status"),
            "quad_topology_reasons": list(geometry.get("quad_topology_reasons") or []),
            "line_accumulator_fused_available": line_accum.get("fused_available"),
            "line_accumulator_fused_reject_reason": line_accum.get("fused_reject_reason"),
        },
        "thresholds": {
            "visible_ratio_min": visible_min,
            "min_margin_floor_px": floor,
        },
    }


def unreliable_geometry_planning_review(slot_state, abort, steps=0, total_cm=0.0):
    """Decide whether suspect raw geometry is usable only for cautious startup planning."""
    visibility = slot_state.get("visibility") or {}
    vision = slot_state.get("vision") or {}
    completeness = slot_state.get("completeness") or {}
    gates = slot_state.get("gates") or {}
    corridor = slot_state.get("corridor") or {}
    geometry = slot_state.get("geometry") or {}

    enabled = _criteria_bool(abort.get("unreliable_geometry_allow_cautious_planning"), True)
    visible_min = _num(abort.get("unreliable_geometry_planning_visible_ratio_min"), 0.06)
    min_margin_required = _num(abort.get("unreliable_geometry_planning_min_margin_px"), 80.0)
    min_confidence = _num(abort.get("unreliable_geometry_planning_min_confidence"), 0.75)
    max_slot_x = _num(
        abort.get(
            "unreliable_geometry_planning_max_slot_x_px",
            abort.get("unreliable_geometry_hard_divergence_px", 300.0),
        ),
        300.0,
    )
    max_total = _num(
        abort.get(
            "unreliable_geometry_planning_max_total_cm",
            abort.get("unreliable_geometry_defer_max_total_cm", 5.0),
        ),
        5.0,
    )
    visible_ratio = _num(
        visibility.get("slot_visible_ratio", vision.get("slot_visible_ratio")), 0.0)
    confidence = _num(slot_state.get("confidence"), 0.0)
    status = completeness.get("status") or vision.get("slot_completeness_status") or "unknown"
    can_refresh = _criteria_bool(
        completeness.get("can_refresh_geometry", gates.get("slot_geometry_complete")), True)
    can_use_visibility = _criteria_bool(
        completeness.get("can_use_as_visibility", gates.get("slot_geometry_usable_visibility")), True)
    geometry_reliable = _criteria_bool(
        geometry.get("geometry_reliable", gates.get("geometry_reliable")), True)
    quad_topology_valid = _criteria_bool(
        geometry.get("quad_topology_valid", gates.get("quad_topology_valid")), True)
    quad_fit_status = geometry.get("quad_fit_status") or gates.get("quad_fit_status")
    quad_fit_status_allowed = (
        quad_fit_status in ("complete", "partial_usable")
        if quad_fit_status is not None else
        True
    )
    geometry_planning_allowed = _criteria_bool(
        geometry.get("geometry_planning_allowed", gates.get("geometry_planning_allowed")),
        bool(quad_fit_status_allowed and quad_topology_valid),
    )
    min_margin = _num(corridor.get("min_margin_px"), -9999.0)
    slot_x_abs = abs(_num(corridor.get("slot_x_err_px"), 9999.0))
    line_risk = bool(corridor.get("line_risk"))
    reasons = set(completeness.get("reasons") or [])
    topology_reasons = set(geometry.get("quad_topology_reasons") or [])
    perspective_reasons = {
        "angle_not_rectangular",
        "diagonal_mismatch",
        "opposite_side_mismatch",
        "opposite_width_mismatch",
    }
    partial_planning_reasons = set(perspective_reasons)
    partial_planning_reasons.update({
        "corridor_sample_extrapolated",
        "corridor_sample_unreliable",
        "entrance_unreliable",
        "side_edges_unreliable",
    })
    fatal_topology_reasons = {
        "quad_not_four_points",
        "quad_area_too_small",
        "quad_self_intersect",
        "left_right_reversed",
        "quad_edge_crosses_interior",
    }
    reference_block = any(str(reason).startswith("reference_") for reason in reasons)
    topology_block = bool(topology_reasons & fatal_topology_reasons)
    reason_blocked = bool(
        reference_block or
        (reasons - partial_planning_reasons) or
        topology_block or
        not quad_fit_status_allowed
    )
    topology_or_fit_planning_ok = bool(quad_topology_valid or geometry_planning_allowed)
    hard_gate_unreliable = bool(
        not geometry_reliable or
        not can_refresh or
        status not in ("complete", "trusted") or
        visible_ratio < _num(abort.get("unreliable_geometry_visible_ratio_min"), 0.28)
    )
    early = int(steps) <= 0 or _num(total_cm) <= max_total
    status_allowed = status in ("suspect", "complete", "trusted")
    planning_usable = bool(
        enabled and
        hard_gate_unreliable and
        early and
        status_allowed and
        can_use_visibility and
        topology_or_fit_planning_ok and
        geometry_planning_allowed and
        not line_risk and
        not reason_blocked and
        visible_ratio >= visible_min and
        confidence >= min_confidence and
        min_margin >= min_margin_required and
        slot_x_abs <= max_slot_x
    )
    failed = []
    checks = {
        "enabled": enabled,
        "hard_gate_unreliable": hard_gate_unreliable,
        "early_motion": early,
        "status_allowed": status_allowed,
        "can_use_as_visibility": can_use_visibility,
        "topology_or_fit_planning_ok": topology_or_fit_planning_ok,
        "quad_topology_valid": quad_topology_valid,
        "geometry_planning_allowed": geometry_planning_allowed,
        "quad_fit_status_allowed": quad_fit_status_allowed,
        "line_risk_ok": not line_risk,
        "reasons_ok": not reason_blocked,
        "visible_ratio_ok": visible_ratio >= visible_min,
        "confidence_ok": confidence >= min_confidence,
        "min_margin_ok": min_margin >= min_margin_required,
        "slot_x_not_extreme": slot_x_abs <= max_slot_x,
    }
    for key, ok in checks.items():
        if key == "quad_topology_valid" and topology_or_fit_planning_ok:
            continue
        if not ok:
            failed.append(key)
    return {
        "schema": "unreliable_geometry_planning_review.v1",
        "planning_usable": planning_usable,
        "reason": (
            "cautious_visual_planning_allowed"
            if planning_usable else "raw_geometry_unreliable_wait_or_belief"),
        "failed_checks": failed,
        "checks": checks,
        "metrics": {
            "slot_visible_ratio": round(visible_ratio, 6),
            "confidence": round(confidence, 4),
            "min_margin_px": round(min_margin, 3),
            "slot_x_err_px_abs": round(slot_x_abs, 3),
            "steps": int(steps),
            "total_cm": round(_num(total_cm), 3),
            "slot_completeness_status": status,
            "slot_completeness_reasons": sorted(reasons),
            "quad_fit_status": quad_fit_status or "unknown",
            "quad_fit_score": geometry.get("quad_fit_score"),
            "quad_fit_source": geometry.get("quad_fit_source"),
            "quad_fit_reasons": list(geometry.get("quad_fit_reasons") or []),
            "quad_topology_status": geometry.get("quad_topology_status"),
            "quad_topology_reasons": sorted(topology_reasons),
            "geometry_reliable": bool(geometry_reliable),
            "geometry_planning_allowed": bool(geometry_planning_allowed),
            "can_refresh_geometry": bool(can_refresh),
        },
        "thresholds": {
            "visible_ratio_min": round(visible_min, 6),
            "min_margin_px": round(min_margin_required, 3),
            "min_confidence": round(min_confidence, 4),
            "max_slot_x_px": round(max_slot_x, 3),
            "max_total_cm": round(max_total, 3),
        },
    }


def evaluate_parking_criteria(slot_state, criteria, steps=0, total_cm=0.0):
    """Evaluate configured parked/abort gates against slot_relative_state."""
    done = criteria.get("done", {})
    abort = criteria.get("abort", {})
    corridor = slot_state.get("corridor") or {}
    image = slot_state.get("image") or {}
    ground = slot_state.get("ground_estimate") or {}
    gates = slot_state.get("gates") or {}

    slot_x_abs = abs(_num(corridor.get("slot_x_err_px")))
    heading_abs = abs(_num(image.get("slot_heading_err_deg")))
    y_dist = _num(ground.get("slot_y_dist_cm"))
    min_margin = _num(corridor.get("min_margin_px"), 9999.0)
    stable_frames = int(_num(slot_state.get("stable_frames"), 0))
    required_stable = int(_num(done.get("required_stable_frames"), 3))
    line_risk = bool(corridor.get("line_risk"))
    max_steps = int(_num(abort.get("max_steps"), 12))

    done_checks = {
        "slot_x_err_px_abs": round(slot_x_abs, 3),
        "slot_x_ok": slot_x_abs <= _num(done.get("slot_x_err_px_abs_max"), 15.0),
        "slot_heading_err_deg_abs": round(heading_abs, 3),
        "heading_ok": heading_abs <= _num(done.get("slot_heading_err_deg_abs_max"), 4.0),
        "slot_y_dist_cm": round(y_dist, 3),
        "distance_ok": y_dist <= _num(done.get("slot_y_dist_cm_max"), 10.0),
        "min_margin_px": round(min_margin, 3),
        "margin_ok": min_margin >= _num(done.get("min_margin_px_min"), 60.0),
        "stable_frames": stable_frames,
        "required_stable_frames": required_stable,
        "stable_ok": stable_frames >= required_stable and bool(gates.get("stable_enough", True)),
        "line_risk": line_risk,
    }
    abort_checks = {
        "min_margin_floor_ok": min_margin >= _num(abort.get("min_margin_px_floor"), 40.0),
        "slot_x_divergence_ok": slot_x_abs <= _num(abort.get("divergence_x_err_px"), 200.0),
        "max_steps_ok": True if max_steps <= 0 else int(steps) < max_steps,
        "max_total_cm_ok": _num(total_cm) < _num(abort.get("max_total_cm"), 60.0),
        "line_risk_ok": not line_risk,
    }
    min_margin_defer = None
    if not abort_checks["min_margin_floor_ok"]:
        min_margin_defer = min_margin_defer_review(
            slot_state, abort, min_margin, line_risk=line_risk)
        if min_margin_defer.get("min_margin_deferred_unreliable_geometry"):
            abort_checks["min_margin_floor_ok"] = True
    slot_x_defer = None
    if not abort_checks["slot_x_divergence_ok"]:
        slot_x_defer = slot_x_divergence_defer_review(
            slot_state, abort, slot_x_abs, steps=steps, total_cm=total_cm)
        if slot_x_defer.get("divergence_deferred"):
            abort_checks["slot_x_divergence_ok"] = True
    abort_reason_map = {
        "min_margin_floor_ok": "min_margin_below_floor",
        "slot_x_divergence_ok": "slot_x_error_diverged",
        "max_steps_ok": "max_steps_reached",
        "max_total_cm_ok": "max_total_cm_reached",
        "line_risk_ok": "line_risk",
    }
    abort_reasons = [abort_reason_map.get(key, key) for key, ok in abort_checks.items() if not ok]
    if abort_reasons:
        return {
            "verdict": "aborted",
            "reason": abort_reasons[0],
            "exit_code": 6,
            "done": done_checks,
            "abort": abort_checks,
            "min_margin_defer": min_margin_defer,
            "slot_x_divergence_defer": slot_x_defer,
        }
    parked = (
        done_checks["slot_x_ok"] and
        done_checks["heading_ok"] and
        done_checks["distance_ok"] and
        done_checks["margin_ok"] and
        done_checks["stable_ok"] and
        not line_risk
    )
    if parked:
        return {
            "verdict": "parked",
            "reason": "success_criteria_met",
            "exit_code": 0,
            "done": done_checks,
            "abort": abort_checks,
            "min_margin_defer": min_margin_defer,
            "slot_x_divergence_defer": slot_x_defer,
        }
    deferred = bool(
        (min_margin_defer and min_margin_defer.get("min_margin_deferred_unreliable_geometry")) or
        (slot_x_defer and slot_x_defer.get("divergence_deferred"))
    )
    if min_margin_defer and min_margin_defer.get("min_margin_deferred_unreliable_geometry"):
        reason = "min_margin_deferred_unreliable_raw_quad"
    elif slot_x_defer and slot_x_defer.get("divergence_deferred"):
        reason = "slot_x_divergence_deferred_unreliable_geometry"
    else:
        reason = "criteria_not_met"
    return {
        "verdict": "defer_unreliable_geometry" if deferred else "continue",
        "reason": reason,
        "exit_code": None,
        "done": done_checks,
        "abort": abort_checks,
        "min_margin_defer": min_margin_defer,
        "slot_x_divergence_defer": slot_x_defer,
    }
