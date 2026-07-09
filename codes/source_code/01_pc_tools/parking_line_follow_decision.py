#!/usr/bin/env python3
"""Line-follow reverse parking decision core.

Replaces the heuristic phase/candidate/scoring decision stack with the
industry-standard corridor tracking law used by production park-assist
systems for the in-corridor reverse segment:

    slot frame state:  y (depth-to-go, cm), l (lateral, cm, left<0),
                       psi (heading error, deg, CW+)
    reverse motion:    dl/ds = sin(psi),  dpsi/ds = kappa(STE)

    control law:       kappa = -(2/lambda)*sin(psi) - (l - l_target)/lambda^2
                       (rad/cm, saturated to the measured curvature limits)

With critically damped gains the closed loop is  l'' + (2/lambda) l' +
(1/lambda^2) l = 0: no overshoot, convergence length ~3*lambda.  Under
saturation the same law degenerates to the classic max-curvature two-arc
"S" maneuver, so one law covers both the far/large-error capture phase
and the near/small-error trim phase.  Receding-horizon execution (one
short ARC, stop, re-measure, re-solve) is inherited from the existing
controller shell.

Curvature <-> STE uses only the measured rows of
configs/chassis_kinematics.json (linear interpolation between measured
servo points, clamped to the measured extremes).  Everything here is
pure standard library so the module runs on the board unchanged.

Deliberately loose gates (DIY car, operator nearby):
  - state bounds  |l| <= 40 cm, |psi| <= 65 deg (same as existing loose caps)
  - total-distance budget is enforced by the controller shell, not here
  - no clearance sampling, no cross-zero penalty, no phase mismatch blocks,
    no requires_measured blocks.

CLI:
  decide one step:   python parking_line_follow_decision.py --decide "45,-8,12"
  rollout preview:   python parking_line_follow_decision.py --rollout "45,-8,12"
  monte-carlo:       python parking_line_follow_decision.py --simulate --out report.json
"""

import argparse
import json
import math
import random


# ---------------------------------------------------------------------------
# Defaults (merged with chassis_kinematics.json + caller overrides).
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    # Control law.
    "lambda_ratio": 0.35,          # lambda = clamp(y_rem * ratio, min, max)
    "lambda_min_cm": 8.0,
    "lambda_max_cm": 16.0,
    # Targets / tolerances (overridden from controller success criteria).
    "target_y_cm": 10.0,
    "target_lateral_cm": 0.0,
    "success_lateral_tol_cm": 3.0,
    "success_heading_tol_deg": 5.0,
    # Command length schedule (commanded ARC D, cm; ground progress is
    # command - deadband + coast).
    "min_command_cm": 4.0,         # chassis arc_min_effective_cmd_cm
    "max_command_cm": 9.0,
    "mid_y_cm": 25.0,
    "mid_command_cm": 7.0,
    "near_y_cm": 12.0,
    "near_command_cm": 5.0,
    # Chassis response (overridden from chassis_kinematics.json).
    "deadband_cm": 1.95,
    "coast_cm": 0.275,
    # Loose state bounds (existing controller caps).
    "max_abs_lateral_cm": 40.0,
    "max_abs_heading_deg": 65.0,
    # Forward relocation (Reeds-Shepp style steered shuffle segment).
    # This chassis has weak steering authority (r_min 48-69 cm), so lateral
    # offsets beyond ~kappa*s^2/4 are physically unreachable in pure reverse;
    # the standard industrial answer is a forward segment that rotates the
    # heading toward the approach angle while regaining depth budget.
    "relocate_enable": True,
    "relocate_command_cm": 8.0,
    "shuffle_ste_candidates": (60, 75, 90, 100, 110, 120, 130),
    "shuffle_chain_max": 4,
    # Do not jump to a forward shuffle just because the reverse-only preview
    # misses the final heading box by a small amount.  In the real car this
    # looked bad: the controller moved forward even though a reasonable reverse
    # path still existed.  Prefer reverse when the reverse preview reaches depth,
    # lateral is already inside the box, and heading is only slightly outside.
    "reverse_prefer_heading_slack_deg": 0.0,
    # A forward relocation is allowed only if the *first* forward step points in
    # a useful direction.  Multi-step lookahead can otherwise choose a forward
    # step that initially makes the car more crooked and only looks good in a
    # noiseless model.  This is exactly the bad behavior seen in logs.
    "shuffle_first_step_min_heading_gain_deg": 0.25,
    "shuffle_first_step_allow_worsen_deg": 0.25,
    # Forward-arc yaw sign relative to the reverse calibration at the same
    # servo angle.  +1 = same yaw direction per servo angle; -1 = classic
    # Ackermann sign flip.  2026-07-04 log review found no forward ARC
    # evidence in SS928_hub and live D=+ shuffle samples showed the same STE
    # yaws opposite to reverse, so keep the default at -1.0.
    "forward_yaw_sign": -1.0,
    # Rollout / full policy simulation.
    "rollout_max_steps": 40,
    "policy_max_steps": 60,
    "policy_max_total_cm": 220.0,
    "depth_done_eps_cm": 0.0,
}

SERVO_CENTER_DEFAULT = 100


def _to_float(value, default=0.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(v) or math.isinf(v):
        return float(default)
    return v


def wrap_deg(a):
    a = _to_float(a, 0.0)
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


def merged_config(kinematics=None, overrides=None):
    cfg = dict(DEFAULT_CONFIG)
    kin = kinematics or {}
    if kin.get("arc_deadband_cm") is not None:
        cfg["deadband_cm"] = _to_float(kin.get("arc_deadband_cm"), cfg["deadband_cm"])
    if kin.get("coast_after_done_cm") is not None:
        cfg["coast_cm"] = _to_float(kin.get("coast_after_done_cm"), cfg["coast_cm"])
    if kin.get("arc_min_effective_cmd_cm") is not None:
        cfg["min_command_cm"] = max(
            cfg["min_command_cm"],
            _to_float(kin.get("arc_min_effective_cmd_cm"), cfg["min_command_cm"]))
    for key, value in (overrides or {}).items():
        if key not in cfg or value is None:
            continue
        if isinstance(cfg[key], bool):
            cfg[key] = bool(value)
        elif isinstance(cfg[key], (list, tuple)):
            cfg[key] = tuple(int(round(_to_float(v))) for v in value)
        else:
            cfg[key] = _to_float(value, cfg[key])
    return cfg


# ---------------------------------------------------------------------------
# Measured curvature table.
# ---------------------------------------------------------------------------

def build_curvature_table(kinematics):
    """Sorted [(ste, deg_per_cm, cv)] from measured rows + explicit center=0.

    Only measured servo points are used; between points curvature is linear
    in servo angle, beyond the extremes it clamps (right side saturates at
    the last distinct measured curvature, e.g. STE=130 == STE=140).
    """
    kin = kinematics or {}
    center = int(round(_to_float(kin.get("servo_center_trim_ste"), SERVO_CENTER_DEFAULT)))
    rows = {}
    for row in kin.get("steer_curvature", []) or []:
        ste = row.get("ste")
        k = row.get("deg_per_cm")
        if ste is None or k is None:
            continue
        ste = int(round(_to_float(ste)))
        rows[ste] = (
            _to_float(k),
            _to_float(row.get("cv_abs_deg_per_cm"), 0.08),
        )
    rows[center] = (0.0, 0.0)
    table = sorted((ste, k, cv) for ste, (k, cv) in rows.items())
    # Drop trailing duplicates of the saturated curvature so the inverse
    # mapping stays one-to-one (keep the lowest servo angle that reaches it).
    dedup = []
    for ste, k, cv in table:
        if dedup and abs(k - dedup[-1][1]) < 1e-9 and k != 0.0:
            continue
        dedup.append((ste, k, cv))
    if len(dedup) < 3:
        raise ValueError("curvature table needs >=3 measured points, got %d" % len(dedup))
    return dedup


def curvature_limits(table):
    """(most-left deg_per_cm (negative), most-right deg_per_cm (positive))."""
    ks = [k for _, k, _ in table]
    return min(ks), max(ks)


def deg_per_cm_for_ste(table, ste):
    ste = _to_float(ste)
    if ste <= table[0][0]:
        return table[0][1]
    if ste >= table[-1][0]:
        return table[-1][1]
    for (s0, k0, _), (s1, k1, _) in zip(table, table[1:]):
        if s0 <= ste <= s1:
            if s1 == s0:
                return k0
            t = (ste - s0) / float(s1 - s0)
            return k0 + t * (k1 - k0)
    return table[-1][1]


def cv_for_ste(table, ste):
    ste = _to_float(ste)
    best = min(table, key=lambda row: abs(row[0] - ste))
    return best[2] if best[2] > 0.0 else 0.08


def ste_for_deg_per_cm(table, k):
    """Inverse of deg_per_cm_for_ste, returned as int servo angle."""
    k = _to_float(k)
    if k <= table[0][1]:
        return int(table[0][0])
    if k >= table[-1][1]:
        return int(table[-1][0])
    for (s0, k0, _), (s1, k1, _) in zip(table, table[1:]):
        lo, hi = min(k0, k1), max(k0, k1)
        if lo <= k <= hi:
            if abs(k1 - k0) < 1e-12:
                return int(round((s0 + s1) / 2.0))
            t = (k - k0) / (k1 - k0)
            return int(round(s0 + t * (s1 - s0)))
    return int(table[-1][0])


# ---------------------------------------------------------------------------
# Motion model (matches the controller's fixed slot-frame integrator).
# ---------------------------------------------------------------------------

def integrate_reverse(pose, ground_cm, deg_per_cm):
    """One reverse arc segment in the slot frame (midpoint heading)."""
    d = max(0.0, _to_float(ground_cm))
    yaw_delta = _to_float(deg_per_cm) * d
    psi0 = wrap_deg(pose["heading_deg"])
    theta_mid = math.radians(wrap_deg(psi0 + 0.5 * yaw_delta))
    return {
        "y_dist_cm": pose["y_dist_cm"] - d * math.cos(theta_mid),
        "lateral_cm": pose["lateral_cm"] + d * math.sin(theta_mid),
        "heading_deg": wrap_deg(psi0 + yaw_delta),
    }


def integrate_forward(pose, ground_cm, deg_per_cm, forward_yaw_sign=-1.0):
    """Forward arc segment.

    ``forward_yaw_sign`` maps the reverse-calibrated deg_per_cm onto forward
    motion: +1 = same yaw direction per servo angle, -1 = classic Ackermann
    sign flip (current default after 2026-07-04 log review).
    """
    d = max(0.0, _to_float(ground_cm))
    yaw_delta = _to_float(forward_yaw_sign, -1.0) * _to_float(deg_per_cm) * d
    psi0 = wrap_deg(pose["heading_deg"])
    theta_mid = math.radians(wrap_deg(psi0 + 0.5 * yaw_delta))
    return {
        "y_dist_cm": pose["y_dist_cm"] + d * math.cos(theta_mid),
        "lateral_cm": pose["lateral_cm"] - d * math.sin(theta_mid),
        "heading_deg": wrap_deg(psi0 + yaw_delta),
    }


def integrate_forward_straight(pose, ground_cm):
    return integrate_forward(pose, ground_cm, 0.0)


def expected_ground_progress(command_cm, cfg):
    return max(0.0, _to_float(command_cm) - cfg["deadband_cm"] + cfg["coast_cm"])


def command_for_ground(ground_cm, cfg):
    return _to_float(ground_cm) + cfg["deadband_cm"] - cfg["coast_cm"]


# ---------------------------------------------------------------------------
# Control law.
# ---------------------------------------------------------------------------

def line_follow_curvature(pose, cfg, table):
    """Desired curvature (deg/cm) + diagnostic terms for one replan."""
    y_rem = pose["y_dist_cm"] - cfg["target_y_cm"]
    lam = max(cfg["lambda_min_cm"],
              min(cfg["lambda_max_cm"], max(0.0, y_rem) * cfg["lambda_ratio"]))
    l_err = pose["lateral_cm"] - cfg["target_lateral_cm"]
    theta = math.radians(wrap_deg(pose["heading_deg"]))
    heading_term = -(2.0 / lam) * math.sin(theta)
    lateral_term = -l_err / (lam * lam)
    kappa_rad = heading_term + lateral_term
    kappa_deg = math.degrees(kappa_rad)
    k_left, k_right = curvature_limits(table)
    saturated = kappa_deg < k_left or kappa_deg > k_right
    kappa_deg = max(k_left, min(k_right, kappa_deg))
    return {
        "lambda_cm": round(lam, 3),
        "lateral_error_cm": round(l_err, 3),
        "heading_term_rad_per_cm": round(heading_term, 6),
        "lateral_term_rad_per_cm": round(lateral_term, 6),
        "desired_deg_per_cm": round(kappa_deg, 6),
        "saturated": bool(saturated),
    }


def command_length_for_pose(pose, cfg):
    """Commanded ARC D (cm) — long steps far out, short steps near the slot,
    depth-capped so the step cannot blow through the target depth."""
    y_rem = pose["y_dist_cm"] - cfg["target_y_cm"]
    if y_rem > cfg["mid_y_cm"]:
        cmd = cfg["max_command_cm"]
    elif y_rem > cfg["near_y_cm"]:
        cmd = cfg["mid_command_cm"]
    else:
        cmd = cfg["near_command_cm"]
    theta = math.radians(wrap_deg(pose["heading_deg"]))
    cos_t = max(0.5, math.cos(theta))
    depth_cap = command_for_ground(max(0.0, y_rem) / cos_t, cfg)
    cmd = min(cmd, depth_cap)
    return max(cfg["min_command_cm"], round(cmd * 2.0) / 2.0)


# ---------------------------------------------------------------------------
# Closed-loop rollout (policy-consistent feasibility preview).
# ---------------------------------------------------------------------------

def rollout(pose, cfg, table):
    """Simulate the exact reverse policy (no noise, no relocations) until the
    target depth is reached.  Cheap (<40 iterations of closed-form math)."""
    cur = dict(pose)
    total = 0.0
    steps = []
    reached_depth = False
    for _ in range(int(cfg["rollout_max_steps"])):
        y_rem = cur["y_dist_cm"] - cfg["target_y_cm"]
        if y_rem <= cfg["depth_done_eps_cm"]:
            reached_depth = True
            break
        law = line_follow_curvature(cur, cfg, table)
        ste = ste_for_deg_per_cm(table, law["desired_deg_per_cm"])
        k_q = deg_per_cm_for_ste(table, ste)
        command = command_length_for_pose(cur, cfg)
        ground = expected_ground_progress(command, cfg)
        if ground <= 0.0:
            break
        cur = integrate_reverse(cur, ground, k_q)
        total += ground
        steps.append({
            "ste": ste,
            "command_cm": command,
            "pose": {k: round(v, 3) for k, v in cur.items()},
        })
    l_err = cur["lateral_cm"] - cfg["target_lateral_cm"]
    psi = wrap_deg(cur["heading_deg"])
    feasible = (
        reached_depth and
        abs(l_err) <= cfg["success_lateral_tol_cm"] and
        abs(psi) <= cfg["success_heading_tol_deg"]
    )
    return {
        "reached_depth": bool(reached_depth),
        "feasible": bool(feasible),
        "final_pose": {k: round(v, 3) for k, v in cur.items()},
        "final_lateral_error_cm": round(l_err, 3),
        "final_heading_deg": round(psi, 3),
        "total_ground_cm": round(total, 3),
        "step_count": len(steps),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Forward shuffle search (one-branch lookahead over the same exact rollout).
# ---------------------------------------------------------------------------

def _rollout_score(result, extra_path_cm, cfg):
    """Lower is better.  Feasibility dominates; excess-over-tolerance error
    next; total path length breaks ties (smoothness: fewer wasted cm)."""
    lat_excess = max(0.0, abs(result["final_lateral_error_cm"]) -
                     cfg["success_lateral_tol_cm"])
    head_excess = max(0.0, abs(result["final_heading_deg"]) -
                      cfg["success_heading_tol_deg"])
    score = 0.0 if result["feasible"] else 1000.0
    if not result["reached_depth"]:
        score += 500.0
    score += 10.0 * lat_excess + 3.0 * head_excess
    score += 0.15 * (result["total_ground_cm"] + max(0.0, extra_path_cm))
    return score


def _reverse_preview_close_enough(preview, cfg):
    """Return True when reverse-only is good enough to keep trying reverse.

    This is not the final parked verdict.  It is only a forward-shuffle
    admission gate: a small heading miss should not force a forward relocation
    if reverse is still reducing the error and reaches the target depth.
    """
    if not preview.get("reached_depth"):
        return False
    lat_ok = (
        abs(_to_float(preview.get("final_lateral_error_cm"), 999.0))
        <= cfg["success_lateral_tol_cm"]
    )
    heading_soft = (
        abs(_to_float(preview.get("final_heading_deg"), 999.0))
        <= cfg["success_heading_tol_deg"]
        + max(0.0, _to_float(cfg.get("reverse_prefer_heading_slack_deg"), 0.0))
    )
    return bool(lat_ok and heading_soft)


def _forward_first_step_review(pose, pose_f, cfg):
    """Gate whether the first forward step itself points the car usefully."""
    heading0 = abs(wrap_deg(pose.get("heading_deg", 0.0)))
    heading1 = abs(wrap_deg(pose_f.get("heading_deg", 0.0)))
    lateral0 = abs(
        _to_float(pose.get("lateral_cm"), 0.0)
        - _to_float(cfg.get("target_lateral_cm"), 0.0)
    )
    gain = heading0 - heading1
    min_gain = max(0.0, _to_float(
        cfg.get("shuffle_first_step_min_heading_gain_deg"), 0.25))
    allow_worsen = max(0.0, _to_float(
        cfg.get("shuffle_first_step_allow_worsen_deg"), 0.25))
    heading_over_tol = heading0 > cfg["success_heading_tol_deg"]
    lateral_over_tol = lateral0 > cfg["success_lateral_tol_cm"]
    if heading_over_tol and gain < min_gain:
        return {
            "pass": False,
            "reason": "first_forward_step_does_not_improve_heading",
            "heading_abs_before_deg": round(heading0, 3),
            "heading_abs_after_deg": round(heading1, 3),
            "heading_gain_deg": round(gain, 3),
            "min_gain_deg": round(min_gain, 3),
        }
    if (not heading_over_tol) and (not lateral_over_tol) and heading1 > heading0 + allow_worsen:
        return {
            "pass": False,
            "reason": "first_forward_step_worsens_heading",
            "heading_abs_before_deg": round(heading0, 3),
            "heading_abs_after_deg": round(heading1, 3),
            "heading_gain_deg": round(gain, 3),
            "allow_worsen_deg": round(allow_worsen, 3),
        }
    return {
        "pass": True,
        "reason": "ok",
        "heading_abs_before_deg": round(heading0, 3),
        "heading_abs_after_deg": round(heading1, 3),
        "heading_gain_deg": round(gain, 3),
        "lateral_abs_before_cm": round(lateral0, 3),
    }


def _best_shuffle(pose, cfg, table, reverse_preview):
    """Evaluate forward arc candidates by simulating the exact reverse policy
    from the post-shuffle pose.  Returns a decision fragment, or None when
    continuing in reverse scores at least as well as every shuffle."""
    fwd_command = cfg["relocate_command_cm"]
    fwd_ground = expected_ground_progress(fwd_command, cfg)
    continue_score = _rollout_score(reverse_preview, 0.0, cfg)
    chain_max = int(cfg.get("shuffle_chain_max", 4))
    best = None
    rejected_first_step = []
    for ste in cfg.get("shuffle_ste_candidates", (60, 75, 90, 100, 110, 120, 130)):
        k_q = deg_per_cm_for_ste(table, ste)
        pose_f = dict(pose)
        first_step_pose = integrate_forward(
            pose, fwd_ground, k_q, cfg.get("forward_yaw_sign", -1.0))
        first_review = _forward_first_step_review(pose, first_step_pose, cfg)
        if not first_review["pass"]:
            item = {"ste": int(ste), "review": first_review}
            rejected_first_step.append(item)
            continue
        # Evaluate chains of 1..N identical forward steps; deep deficits only
        # pay off after several shuffles, which a 1-step lookahead cannot see.
        # Receding horizon: only the first forward step is ever executed.
        for chain in range(1, chain_max + 1):
            pose_f = integrate_forward(pose_f, fwd_ground, k_q,
                                       cfg.get("forward_yaw_sign", -1.0))
            if (abs(pose_f["lateral_cm"]) > cfg["max_abs_lateral_cm"] or
                    abs(pose_f["heading_deg"]) > cfg["max_abs_heading_deg"]):
                break
            after = rollout(pose_f, cfg, table)
            score = _rollout_score(after, chain * fwd_ground, cfg)
            if best is None or score < best["score"]:
                best = {"score": score, "ste": int(ste), "k_q": k_q,
                        "chain": chain,
                        "pose_f": dict(pose_f), "after": after,
                        "first_step_review": first_review}
    if best is None or best["score"] + 1.0 >= continue_score:
        return None
    after_log = dict(best["after"])
    after_log.pop("steps", None)
    first_step_pose = integrate_forward(pose, fwd_ground, best["k_q"],
                                        cfg.get("forward_yaw_sign", -1.0))
    return {
        "mode": "forward_relocate",
        "reason": "reverse_only_infeasible_steered_shuffle",
        "command_cm": round(fwd_command, 3),
        "signed_command_cm": round(fwd_command, 3),
        "ste": int(best["ste"]),
        "quantized_deg_per_cm": round(best["k_q"], 6),
        "expected_ground_cm": round(fwd_ground, 3),
        "predicted_pose": {k: round(v, 3) for k, v in first_step_pose.items()},
        "shuffle_chain_planned": int(best["chain"]),
        "shuffle_score": round(best["score"], 3),
        "continue_reverse_score": round(continue_score, 3),
        "rollout_after_shuffle": after_log,
        "first_forward_step_review": best.get("first_step_review"),
        "rejected_forward_first_steps": rejected_first_step[:8],
    }


# ---------------------------------------------------------------------------
# Single-step decision.
# ---------------------------------------------------------------------------

def decide(pose, cfg, table):
    """One receding-horizon decision from the current slot-frame pose.

    Returns a dict with "mode" in:
      reverse_arc      — execute ARC D=-command STE=ste
      forward_relocate — execute ARC D=+command STE=center (straight)
      depth_reached    — at/inside target depth; shell judges success/trim
      stop_bounds      — pose outside the loose state bounds
    """
    pose = {
        "y_dist_cm": _to_float(pose.get("y_dist_cm"), 999.0),
        "lateral_cm": _to_float(pose.get("lateral_cm"), 0.0),
        "heading_deg": wrap_deg(_to_float(pose.get("heading_deg"), 0.0)),
    }
    base = {"schema": "parking_line_follow_decision.v1", "pose": dict(pose)}
    if (abs(pose["lateral_cm"]) > cfg["max_abs_lateral_cm"] or
            abs(pose["heading_deg"]) > cfg["max_abs_heading_deg"]):
        base.update({"mode": "stop_bounds",
                     "reason": "pose_outside_loose_bounds"})
        return base
    y_rem = pose["y_dist_cm"] - cfg["target_y_cm"]
    if y_rem <= cfg["depth_done_eps_cm"]:
        base.update({"mode": "depth_reached", "reason": "at_target_depth"})
        return base

    law = line_follow_curvature(pose, cfg, table)
    ste = ste_for_deg_per_cm(table, law["desired_deg_per_cm"])
    k_q = deg_per_cm_for_ste(table, ste)
    command = command_length_for_pose(pose, cfg)
    ground = expected_ground_progress(command, cfg)
    preview = rollout(pose, cfg, table)
    preview_log = dict(preview)
    preview_log.pop("steps", None)

    # Precision rule: if the closed-loop preview does not land inside the
    # success box, consider a Reeds-Shepp style forward shuffle segment.
    # The loose-gate philosophy applies to safety blocks, not to precision.
    reverse_close_enough = _reverse_preview_close_enough(preview, cfg)
    if cfg["relocate_enable"] and not preview["feasible"] and not reverse_close_enough:
        shuffle = _best_shuffle(pose, cfg, table, preview)
        if shuffle is not None:
            shuffle["law"] = law
            base.update(shuffle)
            return base

    base.update({
        "mode": "reverse_arc",
        "reason": "line_follow_step",
        "ste": int(ste),
        "quantized_deg_per_cm": round(k_q, 6),
        "command_cm": round(command, 3),
        "signed_command_cm": round(-command, 3),
        "expected_ground_cm": round(ground, 3),
        "predicted_pose": {k: round(v, 3)
                           for k, v in integrate_reverse(pose, ground, k_q).items()},
        "law": law,
        "rollout": preview_log,
        "forward_relocate_suppressed": (
            {
                "reason": "reverse_preview_close_enough",
                "reverse_prefer_heading_slack_deg": round(
                    max(0.0, _to_float(cfg.get("reverse_prefer_heading_slack_deg"), 0.0)), 3),
            }
            if reverse_close_enough and not preview["feasible"] else None
        ),
    })
    return base


# ---------------------------------------------------------------------------
# Monte-Carlo validation (uses the measured per-row curvature CV).
# ---------------------------------------------------------------------------

DEFAULT_NOISE = {
    # Systematic curvature scale error per run + per-step scatter using each
    # measured row's own CV from chassis_kinematics.json.
    "curvature_bias_sd": 0.05,
    "deadband_sd": 0.30,
    "coast_sd": 0.15,
    # Estimate error growth per executed step (odometry/IMU drift)...
    "odom_step_sd": (0.30, 0.25, 0.40),
    # ...re-anchored by a visual correction with probability vision_p.
    "vision_sd": (1.00, 0.80, 0.80),
    "vision_p": 0.70,
    # Initial lock quality.
    "init_est_sd": (1.5, 1.2, 1.5),
}


def simulate_policy(pose0, cfg, table, rng=None, noise=None):
    """Full closed loop of the exact decide() policy.

    rng=None -> deterministic noiseless plant with perfect state estimate
    (used for design-envelope verification); otherwise the plant applies
    curvature/deadband noise and decide() sees a drifting estimate that is
    re-anchored by simulated visual corrections.
    """
    nz = dict(DEFAULT_NOISE)
    nz.update(noise or {})
    truth = dict(pose0)
    if rng is None:
        est_err = [0.0, 0.0, 0.0]
        curvature_bias = 1.0
    else:
        est_err = [rng.gauss(0.0, sd) for sd in nz["init_est_sd"]]
        curvature_bias = rng.gauss(1.0, nz["curvature_bias_sd"])
    total = 0.0
    relocates = 0
    outcome = "max_steps"
    steps = 0
    for _ in range(int(cfg["policy_max_steps"])):
        est = {
            "y_dist_cm": truth["y_dist_cm"] + est_err[0],
            "lateral_cm": truth["lateral_cm"] + est_err[1],
            "heading_deg": wrap_deg(truth["heading_deg"] + est_err[2]),
        }
        decision = decide(est, cfg, table)
        mode = decision["mode"]
        if mode == "depth_reached":
            outcome = "depth_reached"
            break
        if mode == "stop_bounds":
            outcome = "stop_bounds"
            break
        command = decision["command_cm"]
        if rng is None:
            actual = expected_ground_progress(command, cfg)
            k_scale = 1.0
        else:
            actual = max(0.0, command -
                         max(0.0, rng.gauss(cfg["deadband_cm"], nz["deadband_sd"])) +
                         max(0.0, rng.gauss(cfg["coast_cm"], nz["coast_sd"])))
            k_scale = curvature_bias * (
                1.0 + rng.gauss(0.0, cv_for_ste(table, decision["ste"])))
        k_true = deg_per_cm_for_ste(table, decision["ste"]) * k_scale
        if mode == "forward_relocate":
            relocates += 1
            truth = integrate_forward(truth, actual, k_true,
                                      cfg.get("forward_yaw_sign", -1.0))
        else:
            truth = integrate_reverse(truth, actual, k_true)
        total += actual
        steps += 1
        if total > cfg["policy_max_total_cm"]:
            outcome = "total_budget"
            break
        if rng is not None:
            est_err = [e + rng.gauss(0.0, sd)
                       for e, sd in zip(est_err, nz["odom_step_sd"])]
            if rng.random() < nz["vision_p"]:
                est_err = [rng.gauss(0.0, sd) for sd in nz["vision_sd"]]
    l_err = truth["lateral_cm"] - cfg["target_lateral_cm"]
    psi = wrap_deg(truth["heading_deg"])
    return {
        "outcome": outcome,
        "steps": steps,
        "relocates": relocates,
        "total_ground_cm": round(total, 2),
        "final_true_pose": {k: round(v, 3) for k, v in truth.items()},
        "final_lateral_error_cm": round(l_err, 3),
        "final_heading_deg": round(psi, 3),
        "success_3cm_5deg": bool(outcome == "depth_reached" and
                                 abs(l_err) <= 3.0 and abs(psi) <= 5.0),
        "success_5cm_8deg": bool(outcome == "depth_reached" and
                                 abs(l_err) <= 5.0 and abs(psi) <= 8.0),
        "success_2cm_3deg": bool(outcome == "depth_reached" and
                                 abs(l_err) <= 2.0 and abs(psi) <= 3.0),
    }


def simulate_run(pose0, cfg, table, rng, **kwargs):
    return simulate_policy(pose0, cfg, table, rng=rng, noise=kwargs or None)


def _percentile(sorted_values, q):
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def simulate_grid(cfg, table, seeds=30,
                  y_values=(35.0, 45.0, 55.0),
                  lateral_values=(-12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0),
                  heading_values=(-20.0, -10.0, 0.0, 10.0, 20.0),
                  seed0=20260704):
    runs = []
    for y0 in y_values:
        for l0 in lateral_values:
            for h0 in heading_values:
                for s in range(seeds):
                    rng = random.Random(seed0 + hash((y0, l0, h0, s)) % (2 ** 31))
                    result = simulate_run(
                        {"y_dist_cm": y0, "lateral_cm": l0, "heading_deg": h0},
                        cfg, table, rng)
                    result["start"] = {"y": y0, "lateral": l0, "heading": h0, "seed": s}
                    runs.append(result)
    n = len(runs)
    lat_abs = sorted(abs(r["final_lateral_error_cm"]) for r in runs)
    head_abs = sorted(abs(r["final_heading_deg"]) for r in runs)
    steps_sorted = sorted(r["steps"] for r in runs)
    summary = {
        "schema": "parking_line_follow_mc_summary.v1",
        "runs": n,
        "success_rate_2cm_3deg": round(sum(r["success_2cm_3deg"] for r in runs) / n, 4),
        "success_rate_3cm_5deg": round(sum(r["success_3cm_5deg"] for r in runs) / n, 4),
        "success_rate_5cm_8deg": round(sum(r["success_5cm_8deg"] for r in runs) / n, 4),
        "outcomes": {},
        "final_abs_lateral_cm": {
            "p50": _percentile(lat_abs, 0.50),
            "p90": _percentile(lat_abs, 0.90),
            "p99": _percentile(lat_abs, 0.99),
        },
        "final_abs_heading_deg": {
            "p50": _percentile(head_abs, 0.50),
            "p90": _percentile(head_abs, 0.90),
            "p99": _percentile(head_abs, 0.99),
        },
        "steps": {
            "p50": _percentile(steps_sorted, 0.50),
            "p90": _percentile(steps_sorted, 0.90),
            "max": steps_sorted[-1] if steps_sorted else None,
        },
        "relocate_runs": sum(1 for r in runs if r["relocates"] > 0),
    }
    for r in runs:
        summary["outcomes"][r["outcome"]] = summary["outcomes"].get(r["outcome"], 0) + 1
    worst = sorted(runs, key=lambda r: (r["success_3cm_5deg"],
                                        -abs(r["final_lateral_error_cm"])))[:10]
    return summary, runs, worst


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_pose(text):
    parts = [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]
    if len(parts) != 3:
        raise ValueError("pose must be 'y_dist_cm,lateral_cm,heading_deg'")
    return {
        "y_dist_cm": float(parts[0]),
        "lateral_cm": float(parts[1]),
        "heading_deg": float(parts[2]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kinematics", default="configs/chassis_kinematics.json")
    ap.add_argument("--decide", help="pose 'y,lateral,heading' -> one decision")
    ap.add_argument("--rollout", help="pose 'y,lateral,heading' -> full policy preview")
    ap.add_argument("--simulate", action="store_true", help="run monte-carlo grid")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--out", help="write JSON report here")
    ap.add_argument("--target-y-cm", type=float, default=None)
    ap.add_argument("--target-lateral-cm", type=float, default=None)
    ap.add_argument("--success-lateral-tol-cm", type=float, default=None)
    ap.add_argument("--success-heading-tol-deg", type=float, default=None)
    ap.add_argument("--lambda-max-cm", type=float, default=None)
    ap.add_argument("--forward-yaw-sign", type=float, default=None,
                    choices=[-1.0, 1.0],
                    help="-1 classic Ackermann sign flip (default); +1 if "
                         "forward yaw is confirmed same direction as reverse")
    args = ap.parse_args()

    with open(args.kinematics, "r", encoding="utf-8") as fh:
        kinematics = json.load(fh)
    overrides = {
        "target_y_cm": args.target_y_cm,
        "target_lateral_cm": args.target_lateral_cm,
        "success_lateral_tol_cm": args.success_lateral_tol_cm,
        "success_heading_tol_deg": args.success_heading_tol_deg,
        "lambda_max_cm": args.lambda_max_cm,
        "forward_yaw_sign": args.forward_yaw_sign,
    }
    cfg = merged_config(kinematics, overrides)
    table = build_curvature_table(kinematics)

    if args.decide:
        print(json.dumps(decide(_parse_pose(args.decide), cfg, table),
                         indent=2, sort_keys=True))
        return
    if args.rollout:
        print(json.dumps(rollout(_parse_pose(args.rollout), cfg, table),
                         indent=2, sort_keys=True))
        return
    if args.simulate:
        summary, runs, worst = simulate_grid(cfg, table, seeds=args.seeds)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump({"summary": summary, "worst_runs": worst,
                           "config": cfg,
                           "curvature_table": [
                               {"ste": s, "deg_per_cm": k, "cv": cv}
                               for s, k, cv in table]},
                          fh, indent=2, sort_keys=True)
            print("report -> %s" % args.out)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
