#!/usr/bin/env python3
"""Integration test: line_follow decision core inside the controller shell.

Calls h1_structured_phase_build_reference_plan directly with
--diy-path-structured-decision line_follow and checks the plan.v2 contract
the execution shell relies on.  Offline, no board, no motion.
"""

import argparse
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import board_parking_controller as bpc  # noqa: E402

KINEMATICS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "configs",
    "chassis_kinematics.json")
ROLLOUT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "configs",
    "parking_rollout_optimizer_h1.json")
FORWARD_KINEMATICS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "artifacts",
    "board_scan_20260708_005048",
    "opt__parking__autopark__terminal_shuffle_forward_kinematics.json")


def make_args(decision="line_follow"):
    return argparse.Namespace(
        diy_path_profile="h1_structured_phase_parking",
        diy_path_structured_decision=decision,
        diy_path_line_follow_config_json="",
        diy_path_rollout_optimizer_config_json=ROLLOUT_CONFIG_PATH,
        diy_path_terminal_shuffle_forward_kinematics_json=FORWARD_KINEMATICS_PATH,
        diy_path_step_cm=4.0,
        diy_path_max_total_cm=150.0,
        diy_path_target_y_dist_cm=10.0,
        diy_path_target_lateral_cm=0.0,
        diy_path_lateral_tol_cm=3.0,
        diy_path_heading_tol_deg=5.0,
    )


def make_stop_review_args():
    args = make_args()
    args.diy_path_effective_target_y_cm = 1.5
    args.diy_path_success_lateral_target_cm = 0.0
    args.diy_path_success_lateral_tol_cm = 4.0
    args.diy_path_success_heading_tol_deg = 3.0
    args.diy_path_bottom_depth_success_relax_enable = True
    args.diy_path_bottom_depth_success_y_cm = 2.0
    args.diy_path_bottom_depth_success_heading_tol_deg = 10.0
    args.diy_path_bottom_depth_success_heading_relax_cap_deg = 3.0
    args.diy_path_terminal_shuffle_enable = True
    args.diy_path_terminal_shuffle_heading_trigger_deg = 3.0
    args.diy_path_success_max_visionless_steps = 2
    args.diy_path_success_ignore_visionless_steps = True
    args.diy_path_success_max_visual_odom_lateral_delta_cm = 6.0
    args.diy_path_success_max_visual_odom_y_delta_cm = 12.0
    args.diy_path_lateral_estimator_v2_enable = True
    args.diy_path_lateral_estimator_success_use_uncertainty = False
    args.diy_path_lateral_estimator_success_uncertainty_scale = 0.75
    args.diy_path_max_visionless_steps = 10
    args.diy_path_odom_no_progress_stop_count = 2
    args.diy_path_max_total_cm = 150.0
    args.diy_path_max_steps = 24
    args.diy_path_fullset_action_enable = True
    args.diy_path_side_clearance_target_cm = 0.5
    args.diy_path_side_clearance_min_cm = -8.0
    args.diy_path_near_side_clearance_enable = True
    args.diy_path_near_side_min_clearance_cm = 2.5
    args.diy_path_near_side_clearance_weight = 10.0
    args.diy_path_near_side_clearance_early_y_cm = 25.0
    args.diy_path_near_side_clearance_early_scale = 1.5
    args.diy_path_clearance_hard_active_y_cm = 8.0
    args.diy_path_side_clearance_hard_block_cm = -18.0
    return args


def load_kinematics():
    with open(KINEMATICS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class LineFollowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.kin = load_kinematics()
        self.args = make_args()

    def build(self, pose, args=None):
        return bpc.h1_structured_phase_build_reference_plan(
            pose, args or self.args, self.kin, reason="test")

    def test_module_available(self):
        self.assertIsNotNone(bpc.line_follow_decide)
        self.assertTrue(bpc.h1_line_follow_decision_enabled(self.args))
        rollout_args = make_args(decision="rollout_optimizer")
        self.assertIsNotNone(bpc.rollout_optimizer_decide)
        self.assertTrue(bpc.h1_rollout_optimizer_decision_enabled(rollout_args))

    def test_rollout_optimizer_plan_contract(self):
        args = make_args(decision="rollout_optimizer")
        args.diy_path_effective_target_y_cm = 1.5
        args.diy_path_success_lateral_target_cm = 0.0
        args.diy_path_success_lateral_tol_cm = 2.0
        args.diy_path_success_heading_tol_deg = 3.0
        plan = self.build({"y_dist_cm": 45.0, "lateral_cm": -8.0, "heading_deg": 15.0},
                          args=args)
        self.assertEqual(plan["schema"], "diy_first_frame_path_plan.v2")
        self.assertTrue(plan["success_predicted"])
        row = plan["planned_actions"][0]
        self.assertTrue(row["structured_phase_policy_bypass"])
        self.assertIn(row["direction"], ("reverse", "forward"))
        self.assertIn("rollout_optimizer", row["structured_phase"])
        self.assertEqual((plan["candidate_config"] or {}).get("decision_core"),
                         "rollout_optimizer")
        rollout_cfg = (plan["candidate_config"] or {}).get("rollout_optimizer_config") or {}
        side_clearance = rollout_cfg.get("side_clearance") or {}
        self.assertTrue(side_clearance.get("enabled"))
        self.assertGreaterEqual(side_clearance.get("hard_min_clearance_cm"), 1.0)
        self.assertIn("min_side_clearance_cm", row["rollout_optimizer_score"])
        json.dumps(plan)

    def test_reverse_step_plan_contract(self):
        plan = self.build({"y_dist_cm": 45.0, "lateral_cm": -4.0, "heading_deg": 8.0})
        self.assertEqual(plan["schema"], "diy_first_frame_path_plan.v2")
        self.assertTrue(plan["success_predicted"])
        actions = plan["planned_actions"]
        self.assertEqual(len(actions), 1)
        row = actions[0]
        self.assertEqual(row["direction"], "reverse")
        self.assertTrue(row["structured_phase_policy_bypass"])
        self.assertFalse(row["hard_block"])
        self.assertLess(row["signed_distance_cm"], 0.0)
        self.assertIn("ARC D=-", row["cmd"])
        self.assertIn("STE=%d" % row["ste"], row["cmd"])
        # steer direction: lateral -4 with heading +8 -> desired kappa from
        # the law; just require a valid measured-range servo angle
        self.assertGreaterEqual(row["ste"], 60)
        self.assertLessEqual(row["ste"], 130)
        self.assertEqual(len(plan["planned_states"]), 2)
        json.dumps(plan)  # must be JSONL-loggable

    def test_shuffle_plan_is_forward_arc(self):
        plan = self.build({"y_dist_cm": 15.0, "lateral_cm": 10.0, "heading_deg": 0.0})
        row = plan["planned_actions"][0]
        self.assertEqual(row["direction"], "forward")
        self.assertGreater(row["signed_distance_cm"], 0.0)
        self.assertIn("ARC D=", row["cmd"])
        self.assertEqual(row["structured_phase"], "line_follow_forward_relocate")
        self.assertIn(row["forward_kinematics_source"],
                      ("terminal_shuffle_forward_kinematics",
                       "reverse_curve_same_sign",
                       "reverse_curve_sign_inverted"))

    def test_depth_reached_returns_empty_actions(self):
        plan = self.build({"y_dist_cm": 10.0, "lateral_cm": 0.5, "heading_deg": 1.0})
        self.assertEqual(plan["planned_actions"], [])
        self.assertFalse(plan["success_predicted"])
        self.assertEqual(plan["structured_phase_review"]["phase"],
                         "line_follow_depth_reached")

    def test_bounds_stop_returns_empty_actions(self):
        plan = self.build({"y_dist_cm": 45.0, "lateral_cm": 45.0, "heading_deg": 0.0})
        self.assertEqual(plan["planned_actions"], [])
        self.assertEqual(plan["structured_phase_review"]["phase"],
                         "line_follow_stop_bounds")

    def test_legacy_decision_still_uses_structured_scoring(self):
        plan = self.build({"y_dist_cm": 45.0, "lateral_cm": -4.0, "heading_deg": 8.0},
                          args=make_args(decision="legacy"))
        cc = plan.get("candidate_config") or {}
        self.assertEqual(cc.get("schema"), "h1_structured_phase_candidate_config.v1")

    def test_config_json_override(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump({"max_command_cm": 6.0}, fh)
            path = fh.name
        try:
            args = make_args()
            args.diy_path_line_follow_config_json = path
            plan = self.build({"y_dist_cm": 55.0, "lateral_cm": 0.0,
                               "heading_deg": 0.0}, args=args)
            row = plan["planned_actions"][0]
            self.assertLessEqual(row["distance_cm"], 6.0)
        finally:
            os.unlink(path)

    def test_bottom_depth_relax_does_not_accept_crooked_terminal_pose(self):
        args = make_stop_review_args()
        pose = {"y_dist_cm": 0.351, "lateral_cm": -1.104, "heading_deg": 6.768}
        state = {
            "pose": pose,
            "steps": 12,
            "visionless_steps": 6,
            "no_progress_count": 0,
            "total_reverse_cm": 68.5,
            "near_side": "left",
            "last_visual_seen_step": 6,
            "last_visual_review": {"tier": "none", "reason": "no_fresh_yolo"},
            "lateral_estimator": {
                "enabled": True,
                "fused_lateral_cm": -1.104,
                "lateral_uncertainty_cm": 6.042,
                "visionless_steps": 6,
            },
        }
        review = bpc.diy_path_stop_review(state, args)
        self.assertEqual(review["effective_target_y_cm"], 1.5)
        self.assertEqual(review["success_heading_tol_deg"], 3.0)
        self.assertFalse(review["checks"]["heading_ok"])
        self.assertFalse(review["checks"]["parked"])
        self.assertFalse(review["success"])
        self.assertFalse(review["terminal_observed_success"])

        still_crooked_pose = dict(pose, heading_deg=5.8)
        still_crooked_state = dict(state, pose=still_crooked_pose)
        still_crooked_review = bpc.diy_path_stop_review(still_crooked_state, args)
        self.assertFalse(still_crooked_review["checks"]["heading_ok"])
        self.assertFalse(still_crooked_review["success"])

        straight_pose = dict(pose, heading_deg=2.8)
        straight_state = dict(state, pose=straight_pose)
        straight_review = bpc.diy_path_stop_review(straight_state, args)
        self.assertTrue(straight_review["checks"]["heading_ok"])
        self.assertTrue(straight_review["success"])

    def test_success_requires_one_cm_deeper_target(self):
        args = make_stop_review_args()
        state = {
            "pose": {"y_dist_cm": 2.414, "lateral_cm": -1.341, "heading_deg": 2.8},
            "steps": 8,
            "visionless_steps": 0,
            "no_progress_count": 0,
            "total_reverse_cm": 56.4,
            "last_visual_review": {"tier": "ok", "reason": "fresh"},
            "lateral_estimator": {"enabled": False},
        }
        review = bpc.diy_path_stop_review(state, args)
        self.assertEqual(review["effective_target_y_cm"], 1.5)
        self.assertFalse(review["checks"]["y_target_reached"])
        self.assertFalse(review["success"])

        state["pose"] = {"y_dist_cm": 1.4, "lateral_cm": -1.341, "heading_deg": 2.8}
        review = bpc.diy_path_stop_review(state, args)
        self.assertTrue(review["checks"]["y_target_reached"])
        self.assertTrue(review["success"])

    def test_done_progress_overrides_late_guard_stop(self):
        """Regression for 2026-07-07 real run.

        The STM32 completed the ARC and reported D=7.9, but the controller had
        appended GUARD_STOP because live TLM progress was unavailable.  A valid
        MOVE/ARC DONE with measured progress must not be reported as
        stm32_command_failed.
        """
        motion_response = (
            "ACK 1008 ARC\r\n"
            "DONE 1008 ARC X=0.1 Y=-7.9 D=7.9 YAW=13.1\r\n"
            "DONE 10008 STOP\r\n"
            "\n"
            "GUARD_STOP reason=stalled_no_progress max_tlm_d_cm=0.000 min_progress_cm=0.400"
        )
        args = argparse.Namespace(
            strategy="diy_first_frame_path_parking",
            diy_path_require_imu_ok=True,
            motion_min_progress_cm=0.4,
            _last_execute_logged_motion_result={
                "motion_response": motion_response,
                "motion_events": bpc.parse_stm32_events(motion_response),
                "pre_servo_response": "",
            },
        )
        st = {
            "yaw": 11.3,
            "d": 10.8,
            "imu": "OK",
            "raw": "STAT 1007 MODE=IDLE RUN=PARKING DIR=-1 SPD=0 ANG=100.0 "
                   "YAW=11.3 X=-0.9 Y=5.0 D=10.8 VEL=0.0 DROP=0 IMU=OK",
        }
        st_after = {
            "yaw": 13.3,
            "d": 7.9,
            "imu": "OK",
            "raw": "STAT 1009 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=100.0 "
                   "YAW=13.3 X=0.1 Y=-7.9 D=7.9 VEL=0.0 DROP=0 IMU=OK",
        }
        result = bpc.diy_fast_odom_motion_result(
            {"cmd": "ARC D=-9.0 STE=105 V=1", "step": 9.0},
            st,
            st_after,
            args._last_execute_logged_motion_result["motion_events"],
            args,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "ok")
        self.assertTrue(result["guard_stop"])
        self.assertTrue(result["guard_stop_overridden"])
        self.assertFalse(result["guard_stop_blocking"])
        self.assertEqual(result["odom_progress_cm"], 7.9)
        self.assertAlmostEqual(result["yaw_delta_deg"], 2.0, places=3)

    def test_stm32_button_stop_token_semantics(self):
        self.assertFalse(bpc.stm32_button_stop_requested("CTR_PK START\r\n", "CTR_PK"))
        self.assertTrue(bpc.stm32_button_stop_requested("CTR_PK STOP\r\n", "CTR_PK"))
        # Bare CTR_PK stays a stop request for compatibility with one-token firmware.
        self.assertTrue(bpc.stm32_button_stop_requested("CTR_PK\r\n", "CTR_PK"))

    def test_button_stop_err_becomes_normal_stop_reason(self):
        motion_response = (
            "ACK 1008 ARC\r\n"
            "ERR 1008 CODE=BUTTON_STOP X=0.0 Y=-1.2 D=1.2 YAW=2.0\r\n"
        )
        args = argparse.Namespace(
            strategy="diy_first_frame_path_parking",
            diy_path_require_imu_ok=True,
            motion_min_progress_cm=0.4,
            _last_execute_logged_motion_result={
                "motion_response": motion_response,
                "motion_events": bpc.parse_stm32_events(motion_response),
                "pre_servo_response": "",
            },
        )
        st = {"yaw": 0.0, "d": 0.0, "imu": "OK", "raw": "STAT 1 YAW=0.0 D=0.0 IMU=OK"}
        st_after = {"yaw": 2.0, "d": 1.2, "imu": "OK", "raw": "STAT 2 YAW=2.0 D=1.2 IMU=OK"}
        result = bpc.diy_fast_odom_motion_result(
            {"cmd": "ARC D=-9.0 STE=105 V=1", "step": 9.0},
            st,
            st_after,
            args._last_execute_logged_motion_result["motion_events"],
            args,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["button_stop"])
        self.assertEqual(result["reason"], "button_stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
