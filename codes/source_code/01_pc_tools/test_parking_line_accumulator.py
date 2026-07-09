#!/usr/bin/env python3
from __future__ import annotations

import math
from argparse import Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from parking_line_accumulator import (  # noqa: E402
    MotionCompensatedSlotLineAccumulator,
    transform_point_anchor_to_vehicle,
)
from board_parking_controller import (  # noqa: E402
    DEFAULT_CORRIDOR_ENTRY_Y,
    DEFAULT_CORRIDOR_SAMPLE_Y,
    DEFAULT_PIXEL_ANGLE_TOL_DEG,
    DEFAULT_PIXEL_STOP_CENTER_Y,
    DEFAULT_PIXEL_STOP_QUAD_H,
    DEFAULT_SLOT_CLASS_NAMES,
    IMAGE_H,
    PIXEL_ANGLE_TARGET_DEG,
    PIXEL_X_TARGET,
    slot_infos_from_udp,
    slot_relative_state,
)

H = [
    [-0.002841148786767839, -0.0902385437276105, 64.96470339525213],
    [-0.06211726961004081, -6.827304779515962e-05, 21.07360636711848],
    [-4.793066796001953e-05, 4.628315527150238e-05, 1.0],
]


def slot_info(dx=0.0, dy=0.0, yaw_deg=0.0, edge_type_suffix=""):
    # A simple rectangular slot in vehicle cm coordinates.
    left = ((20.0 + dx, -10.0 + dy), (70.0 + dx, -10.0 + dy))
    right = ((20.0 + dx, 10.0 + dy), (70.0 + dx, 10.0 + dy))
    entrance = ((20.0 + dx, -10.0 + dy), (20.0 + dx, 10.0 + dy))
    back = ((70.0 + dx, -10.0 + dy), (70.0 + dx, 10.0 + dy))
    if abs(yaw_deg) > 1e-9:
        c = math.cos(math.radians(yaw_deg))
        s = math.sin(math.radians(yaw_deg))

        def rot(p):
            return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)

        left = tuple(rot(p) for p in left)
        right = tuple(rot(p) for p in right)
        entrance = tuple(rot(p) for p in entrance)
        back = tuple(rot(p) for p in back)
    return {
        "confidence": 0.8,
        "slot_completeness": {"score": 0.9, "status": "complete", "can_refresh_geometry": True},
        "left_edge_cm" + edge_type_suffix: left,
        "right_edge_cm" + edge_type_suffix: right,
        "entrance_edge_cm" + edge_type_suffix: entrance,
        "back_edge_cm" + edge_type_suffix: back,
    }


def test_same_line_merges():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1}, H)
    acc.update_from_slot_info(slot_info(), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.0)
    acc.update_from_slot_info(slot_info(dx=0.4, dy=0.2), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.1)
    diag = acc.diagnostics(now=1.2)
    assert diag["track_count"] == 4, diag
    assert all(t["hits"] == 2 for t in diag["tracks"]), diag


def test_edge_types_do_not_merge():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1}, H)
    acc.update_from_slot_info(slot_info(), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.0)
    # Same geometry inserted again should still remain four typed tracks, not cross-merge.
    acc.update_from_slot_info(slot_info(), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.1)
    types = sorted(t["edge_type"] for t in acc.diagnostics(now=1.2)["tracks"])
    assert types == ["back_edge", "entrance_edge", "left_edge", "right_edge"], types


def test_direction_distance_overlap_gates():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1, "merge_distance_cm": 1.0}, H)
    acc.update_from_slot_info(slot_info(), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.0)
    # Far enough to create another set of tracks rather than merging.
    acc.update_from_slot_info(slot_info(dy=20.0), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.1)
    assert acc.diagnostics(now=1.2)["track_count"] == 8


def test_motion_compensation_overlaps_after_pose_transform():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1}, H)
    pose1 = {"x_cm": 0.0, "y_cm": 0.0, "yaw_deg": 0.0}
    pose2 = {"x_cm": 5.0, "y_cm": -1.0, "yaw_deg": 4.0}
    base = slot_info()
    acc.update_from_slot_info(base, pose1, timestamp=1.0)
    # Build a second observation that is the same anchor-frame slot, seen from pose2.
    def edge_to_current(edge):
        return tuple(transform_point_anchor_to_vehicle(p, pose2) for p in edge)

    shifted = {
        "confidence": 0.8,
        "slot_completeness": {"score": 0.9, "status": "complete", "can_refresh_geometry": True},
        "left_edge_cm": edge_to_current(base["left_edge_cm"]),
        "right_edge_cm": edge_to_current(base["right_edge_cm"]),
        "entrance_edge_cm": edge_to_current(base["entrance_edge_cm"]),
        "back_edge_cm": edge_to_current(base["back_edge_cm"]),
    }
    acc.update_from_slot_info(shifted, pose2, timestamp=1.1)
    diag = acc.diagnostics(now=1.2)
    assert diag["track_count"] == 4, diag
    assert all(t["hits"] == 2 for t in diag["tracks"]), diag


def test_fused_detection_rebuilds_polygon():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1}, H)
    for i in range(5):
        acc.update_from_slot_info(slot_info(dx=0.1 * i, dy=-0.05 * i), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.0 + i * 0.1)
    fused = acc.fused_detection_current({"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=2.0)
    assert fused["status"] == "ok", fused
    det = fused["detection"]
    assert len(det["mask_polygon"]) == 4
    assert det["mask_area_px"] > 10.0


def _state_args():
    return Namespace(
        stable_frames=1,
        pixel_target_x=PIXEL_X_TARGET,
        pixel_target_angle_deg=PIXEL_ANGLE_TARGET_DEG,
        pixel_stop_center_y=DEFAULT_PIXEL_STOP_CENTER_Y,
        pixel_stop_quad_h=DEFAULT_PIXEL_STOP_QUAD_H,
        corridor_sample_y=DEFAULT_CORRIDOR_SAMPLE_Y,
        corridor_entry_y=DEFAULT_CORRIDOR_ENTRY_Y,
        corridor_min_line_margin_px=34.0,
        corridor_line_risk_min_closeness=0.92,
        corridor_approach_closeness=0.82,
        corridor_final_stop_closeness=1.08,
        corridor_x_tolerance_px=24.0,
        normalized_x_tolerance=0.06,
        normalized_min_margin=0.12,
        pixel_angle_tolerance_deg=DEFAULT_PIXEL_ANGLE_TOL_DEG,
    )


def test_fused_detection_passes_slot_relative_state():
    acc = MotionCompensatedSlotLineAccumulator({"min_track_weight": 0.1}, H)
    for i in range(5):
        acc.update_from_slot_info(slot_info(dx=0.1 * i, dy=-0.05 * i), {"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=1.0 + i * 0.1)
    fused = acc.fused_detection_current({"x_cm": 0, "y_cm": 0, "yaw_deg": 0}, timestamp=2.0)
    raw = {
        "schema_version": 1,
        "component": "line_accumulator_test",
        "image_size": [640, 640],
        "detections": [fused["detection"]],
        "detection_count": 1,
    }
    infos = slot_infos_from_udp(raw, DEFAULT_SLOT_CLASS_NAMES)
    assert infos, fused
    state = slot_relative_state(infos[0], _state_args())
    assert state["schema"] == "slot_relative_state.v1", state
    assert "ground_estimate" in state and "corridor" in state, state


def main():
    tests = [
        test_same_line_merges,
        test_edge_types_do_not_merge,
        test_direction_distance_overlap_gates,
        test_motion_compensation_overlaps_after_pose_transform,
        test_fused_detection_rebuilds_polygon,
        test_fused_detection_passes_slot_relative_state,
    ]
    for test in tests:
        test()
    print("parking_line_accumulator_tests=PASS")


if __name__ == "__main__":
    main()
