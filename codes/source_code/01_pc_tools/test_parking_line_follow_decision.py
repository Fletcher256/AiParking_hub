#!/usr/bin/env python3
"""Unit tests for parking_line_follow_decision (pure stdlib, offline)."""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parking_line_follow_decision as lfd  # noqa: E402

KINEMATICS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "configs",
    "chassis_kinematics.json")


def load_kinematics():
    with open(KINEMATICS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TableTests(unittest.TestCase):
    def setUp(self):
        self.kin = load_kinematics()
        self.table = lfd.build_curvature_table(self.kin)

    def test_table_monotonic_in_ste(self):
        ks = [k for _, k, _ in self.table]
        self.assertEqual(ks, sorted(ks))
        self.assertLess(ks[0], 0.0)   # left extreme
        self.assertGreater(ks[-1], 0.0)  # right extreme

    def test_center_is_zero(self):
        self.assertAlmostEqual(lfd.deg_per_cm_for_ste(self.table, 100), 0.0, places=9)

    def test_measured_rows_roundtrip(self):
        for row in self.kin["steer_curvature"]:
            ste = int(row["ste"])
            if ste >= 140:  # saturated duplicate of 130 is dropped by design
                continue
            k = lfd.deg_per_cm_for_ste(self.table, ste)
            self.assertAlmostEqual(k, float(row["deg_per_cm"]), places=6)
            self.assertEqual(lfd.ste_for_deg_per_cm(self.table, k), ste)

    def test_inverse_clamps_to_measured_extremes(self):
        self.assertEqual(lfd.ste_for_deg_per_cm(self.table, -99.0), 60)
        self.assertEqual(lfd.ste_for_deg_per_cm(self.table, +99.0), 130)


class LawSignTests(unittest.TestCase):
    """Sign conventions: lateral left<0, heading CW+, STE>center = right."""

    def setUp(self):
        self.kin = load_kinematics()
        self.table = lfd.build_curvature_table(self.kin)
        self.cfg = lfd.merged_config(self.kin)

    def decide(self, y, lat, heading):
        return lfd.decide({"y_dist_cm": y, "lateral_cm": lat,
                           "heading_deg": heading}, self.cfg, self.table)

    def test_positive_lateral_steers_left(self):
        # +-4cm at y=50 stays inside the pure-reverse envelope.
        d = self.decide(50.0, 4.0, 0.0)
        self.assertEqual(d["mode"], "reverse_arc")
        self.assertLess(d["ste"], 100)

    def test_negative_lateral_steers_right(self):
        d = self.decide(50.0, -4.0, 0.0)
        self.assertEqual(d["mode"], "reverse_arc")
        self.assertGreater(d["ste"], 100)

    def test_positive_heading_alone_steers_left(self):
        d = self.decide(45.0, 0.0, 15.0)
        self.assertEqual(d["mode"], "reverse_arc")
        self.assertLess(d["ste"], 100)

    def test_aligned_pose_goes_straight(self):
        d = self.decide(45.0, 0.0, 0.0)
        self.assertEqual(d["mode"], "reverse_arc")
        self.assertEqual(d["ste"], 100)

    def test_at_depth_reports_depth_reached(self):
        d = self.decide(10.0, 0.5, 1.0)
        self.assertEqual(d["mode"], "depth_reached")

    def test_bounds_stop(self):
        d = self.decide(45.0, 41.0, 0.0)
        self.assertEqual(d["mode"], "stop_bounds")
        d = self.decide(45.0, 0.0, 70.0)
        self.assertEqual(d["mode"], "stop_bounds")


class ConvergenceTests(unittest.TestCase):
    """Noise-free closed loop must converge from the whole design envelope."""

    def setUp(self):
        self.kin = load_kinematics()
        self.table = lfd.build_curvature_table(self.kin)
        self.cfg = lfd.merged_config(self.kin)

    def test_noiseless_full_policy_grid_converges(self):
        """Whole design envelope, shuffle segments allowed."""
        failures = []
        for y0 in (35.0, 45.0, 55.0):
            for l0 in (-12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0):
                for h0 in (-20.0, -10.0, 0.0, 10.0, 20.0):
                    r = lfd.simulate_policy(
                        {"y_dist_cm": y0, "lateral_cm": l0, "heading_deg": h0},
                        self.cfg, self.table)
                    ok = (r["outcome"] == "depth_reached" and
                          abs(r["final_lateral_error_cm"]) <=
                          self.cfg["success_lateral_tol_cm"] and
                          abs(r["final_heading_deg"]) <=
                          self.cfg["success_heading_tol_deg"])
                    if not ok:
                        failures.append(((y0, l0, h0), r["outcome"],
                                         r["final_true_pose"],
                                         r["total_ground_cm"]))
        self.assertEqual(failures, [],
                         "noiseless policy runs not converged: %s" % failures[:8])

    def test_noiseless_pure_reverse_envelope_converges(self):
        """Within the chassis' pure-reverse capability (weak steering:
        r_min 48-69cm) the reverse-only rollout must converge with no
        shuffle.  Wrong-signed heading extremes are excluded on purpose —
        they are physically outside the pure-reverse envelope."""
        cases = [
            (45.0, 4.0, 0.0), (45.0, -4.0, 0.0),
            (45.0, 0.0, 10.0), (45.0, 0.0, -10.0),
            (55.0, 6.0, 0.0), (55.0, -6.0, 0.0),
            (55.0, 0.0, 12.0), (55.0, 0.0, -12.0),
            (45.0, 4.0, -10.0), (55.0, -6.0, 10.0),  # helpful-signed heading
        ]
        failures = []
        for y0, l0, h0 in cases:
            r = lfd.rollout({"y_dist_cm": y0, "lateral_cm": l0,
                             "heading_deg": h0}, self.cfg, self.table)
            if not r["feasible"]:
                failures.append(((y0, l0, h0), r["final_pose"]))
        self.assertEqual(failures, [],
                         "pure-reverse envelope not converged: %s" % failures[:8])

    def test_rollout_flags_infeasible_pose(self):
        # 10cm lateral with only ~5cm depth budget cannot converge in reverse.
        r = lfd.rollout({"y_dist_cm": 15.0, "lateral_cm": 10.0,
                         "heading_deg": 0.0}, self.cfg, self.table)
        self.assertFalse(r["feasible"])

    def test_infeasible_pose_relocates_forward_with_steer(self):
        d = lfd.decide({"y_dist_cm": 15.0, "lateral_cm": 10.0,
                        "heading_deg": 0.0}, self.cfg, self.table)
        self.assertEqual(d["mode"], "forward_relocate")
        self.assertGreater(d["signed_command_cm"], 0.0)
        self.assertIsInstance(d["ste"], int)
        # l_err > 0 wants approach heading psi < 0 for the next reverse cut.
        # forward_yaw_sign=-1 (classic Ackermann flip, current default) means
        # negative forward yaw needs reverse-calibrated kappa > 0 -> right.
        self.assertEqual(self.cfg["forward_yaw_sign"], -1.0)
        self.assertGreater(d["ste"], 100)

    def test_reverse_close_enough_suppresses_unneeded_forward(self):
        cfg = dict(self.cfg)
        cfg.update({
            "target_y_cm": 2.5,
            "success_lateral_tol_cm": 4.0,
            "success_heading_tol_deg": 6.0,
            "reverse_prefer_heading_slack_deg": 2.0,
        })
        d = lfd.decide({"y_dist_cm": 8.174, "lateral_cm": -2.48,
                        "heading_deg": 11.084}, cfg, self.table)
        self.assertEqual(d["mode"], "reverse_arc")
        self.assertEqual(
            (d.get("forward_relocate_suppressed") or {}).get("reason"),
            "reverse_preview_close_enough",
        )
        self.assertLessEqual(
            abs(d["rollout"]["final_heading_deg"]),
            cfg["success_heading_tol_deg"] + cfg["reverse_prefer_heading_slack_deg"],
        )

    def test_forward_heading_correction_must_improve_first_step(self):
        cfg = dict(self.cfg)
        cfg.update({
            "target_y_cm": 2.5,
            "success_lateral_tol_cm": 1.0,
            "success_heading_tol_deg": 6.0,
            "reverse_prefer_heading_slack_deg": 0.0,
        })
        d = lfd.decide({"y_dist_cm": 25.0, "lateral_cm": 1.2,
                        "heading_deg": 25.0}, cfg, self.table)
        self.assertEqual(d["mode"], "forward_relocate")
        self.assertGreater(d["ste"], 100)
        self.assertGreater(
            (d.get("first_forward_step_review") or {}).get("heading_gain_deg", 0.0),
            0.0,
        )
        rejected_ste = {
            row["ste"] for row in d.get("rejected_forward_first_steps") or []
        }
        self.assertIn(60, rejected_ste)
        self.assertIn(75, rejected_ste)

    def test_forward_yaw_sign_flips_shuffle_side(self):
        """Guard the knob: same-sign convention must choose the opposite
        steering side for the same forward shuffle pose."""
        cfg_flip = dict(self.cfg)
        cfg_flip["forward_yaw_sign"] = 1.0
        d = lfd.decide({"y_dist_cm": 15.0, "lateral_cm": 10.0,
                        "heading_deg": 0.0}, cfg_flip, self.table)
        self.assertEqual(d["mode"], "forward_relocate")
        self.assertLess(d["ste"], 100)

    def test_step_is_depth_capped(self):
        d = lfd.decide({"y_dist_cm": 13.0, "lateral_cm": 0.0,
                        "heading_deg": 0.0}, self.cfg, self.table)
        self.assertEqual(d["mode"], "reverse_arc")
        # ground progress must not exceed remaining depth by more than ~1cm
        self.assertLessEqual(d["expected_ground_cm"],
                             13.0 - self.cfg["target_y_cm"] + 1.0)

    def test_decision_json_serializable(self):
        d = lfd.decide({"y_dist_cm": 45.0, "lateral_cm": -7.0,
                        "heading_deg": 12.0}, self.cfg, self.table)
        json.dumps(d)


class MotionModelTests(unittest.TestCase):
    def test_reverse_straight_reduces_y_only(self):
        p = lfd.integrate_reverse(
            {"y_dist_cm": 40.0, "lateral_cm": 2.0, "heading_deg": 0.0}, 5.0, 0.0)
        self.assertAlmostEqual(p["y_dist_cm"], 35.0, places=6)
        self.assertAlmostEqual(p["lateral_cm"], 2.0, places=6)

    def test_reverse_with_heading_moves_lateral(self):
        p = lfd.integrate_reverse(
            {"y_dist_cm": 40.0, "lateral_cm": 0.0, "heading_deg": 30.0}, 10.0, 0.0)
        self.assertAlmostEqual(p["lateral_cm"], 10.0 * math.sin(math.radians(30.0)),
                               places=6)

    def test_forward_straight_undoes_reverse_straight(self):
        p0 = {"y_dist_cm": 40.0, "lateral_cm": 3.0, "heading_deg": 10.0}
        p1 = lfd.integrate_reverse(p0, 6.0, 0.0)
        p2 = lfd.integrate_forward_straight(p1, 6.0)
        for key in p0:
            self.assertAlmostEqual(p2[key], p0[key], places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
