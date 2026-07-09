#!/usr/bin/env python3
"""Offline tests for parking_rollout_optimizer."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parking_rollout_optimizer as ro  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINEMATICS_PATH = os.path.join(ROOT, "configs", "chassis_kinematics.json")
CONFIG_PATH = os.path.join(ROOT, "configs", "parking_rollout_optimizer_h1.json")
FORWARD_PATH = os.path.join(
    ROOT, "artifacts", "board_scan_20260708_005048",
    "opt__parking__autopark__terminal_shuffle_forward_kinematics.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class RolloutOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.kin = load_json(KINEMATICS_PATH)
        self.cfg = ro.merged_config(self.kin, load_json(CONFIG_PATH))
        self.table = ro.build_curvature_table(self.kin)
        self.forward = ro.load_forward_kinematics(FORWARD_PATH)

    def test_reverse_integrator_reduces_depth(self):
        pose = {"y_dist_cm": 40.0, "lateral_cm": 0.0, "heading_deg": 0.0}
        action = {"direction": "reverse", "command_cm": 4.0, "ste": 100}
        sim = ro.simulate_action(pose, action, self.cfg, self.table, self.forward)
        self.assertLess(sim["pose"]["y_dist_cm"], pose["y_dist_cm"])
        self.assertAlmostEqual(sim["pose"]["lateral_cm"], 0.0, places=6)

    def test_forward_integrator_increases_depth(self):
        pose = {"y_dist_cm": 10.0, "lateral_cm": 0.0, "heading_deg": 0.0}
        action = {"direction": "forward", "command_cm": 4.0, "ste": 100}
        sim = ro.simulate_action(pose, action, self.cfg, self.table, self.forward)
        self.assertGreater(sim["pose"]["y_dist_cm"], pose["y_dist_cm"])

    def test_forward_kinematics_preferred_when_available(self):
        pose = {"y_dist_cm": 10.0, "lateral_cm": 0.0, "heading_deg": 0.0}
        action = {"direction": "forward", "command_cm": 4.0, "ste": 60}
        sim = ro.simulate_action(pose, action, self.cfg, self.table, self.forward)
        self.assertEqual(sim["kinematics_source"], "terminal_shuffle_forward_kinematics")
        self.assertGreater(sim["deg_per_cm"], 0.0)

    def test_stage_action_sets(self):
        self.assertEqual(ro.stage_name_for_pose({"y_dist_cm": 45}, self.cfg), "early")
        self.assertEqual(ro.stage_name_for_pose({"y_dist_cm": 25}, self.cfg), "middle")
        self.assertEqual(ro.stage_name_for_pose({"y_dist_cm": 10}, self.cfg), "late")
        late_actions = ro.action_library("late", self.cfg)
        self.assertTrue(late_actions)
        self.assertNotIn(8.0, [a["command_cm"] for a in late_actions if a["direction"] == "forward"])
        self.assertEqual(sorted({a["command_cm"] for a in late_actions if a["direction"] == "forward"}), [4.0])

    def test_body_clearance_model_uses_vehicle_footprint(self):
        centered = ro.body_clearance_review(
            {"y_dist_cm": 20.0, "lateral_cm": 0.0, "heading_deg": 0.0},
            self.cfg)
        self.assertTrue(centered["enabled"])
        self.assertAlmostEqual(centered["min_side_clearance_cm"], 4.75, places=3)

        near_left = ro.body_clearance_review(
            {"y_dist_cm": 20.0, "lateral_cm": -4.0, "heading_deg": 0.0},
            self.cfg)
        self.assertLess(near_left["min_side_clearance_cm"], 1.0)
        self.assertEqual(near_left["measured_near_side"], "left")

    def test_clearance_review_hard_blocks_line_pressing_action(self):
        cfg = json.loads(json.dumps(self.cfg))
        cfg["side_clearance"]["hard_active_y_cm"] = 999.0
        cfg["side_clearance"]["allow_escape_when_already_violating"] = False
        pose = {"y_dist_cm": 25.0, "lateral_cm": -4.0, "heading_deg": 0.0}
        action = {"direction": "reverse", "command_cm": 7.0, "ste": 120}
        sim = ro.simulate_action(pose, action, cfg, self.table, self.forward)
        review = ro.trajectory_clearance_review(pose, action, sim, cfg)
        self.assertTrue(review["hard_block"])
        self.assertLess(review["min_side_clearance_cm"], cfg["side_clearance"]["hard_min_clearance_cm"])

    def test_optimizer_does_not_worsen_clearance_when_already_near_line(self):
        cfg = json.loads(json.dumps(self.cfg))
        cfg["side_clearance"]["hard_active_y_cm"] = 999.0
        cfg["side_clearance"]["escape_worsen_tolerance_cm"] = 0.0
        pose = {"y_dist_cm": 30.0, "lateral_cm": -4.0, "heading_deg": 0.0}
        start_clearance = ro.body_clearance_review(pose, cfg)["min_side_clearance_cm"]
        d = ro.decide(pose, cfg, self.table, self.forward)
        self.assertIn(d["mode"], ("reverse_arc", "forward_arc", "no_safe_candidate"))
        if d["mode"] in ("reverse_arc", "forward_arc"):
            self.assertGreaterEqual(d["best_sequence"][0]["clearance_review"]["min_side_clearance_cm"],
                                    start_clearance)

    def test_recent_failure_terminal_pose_uses_small_action_not_big_forward(self):
        d = ro.decide(
            {"y_dist_cm": 0.428, "lateral_cm": -0.908, "heading_deg": 4.088},
            self.cfg, self.table, self.forward)
        self.assertIn(d["mode"], ("reverse_arc", "forward_arc", "no_safe_candidate"))
        if d["mode"] == "forward_arc":
            self.assertLessEqual(d["command_cm"], 4.0)
        if d["mode"] in ("reverse_arc", "forward_arc"):
            self.assertNotEqual((d["signed_command_cm"], d["ste"]), (8.0, 110))
            self.assertLessEqual(abs(d["signed_command_cm"]), 5.0)

    def test_decision_json_serializable(self):
        d = ro.decide({"y_dist_cm": 45.0, "lateral_cm": -8.0, "heading_deg": 15.0},
                      self.cfg, self.table, self.forward)
        json.dumps(d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
