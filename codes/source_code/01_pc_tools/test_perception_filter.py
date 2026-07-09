#!/usr/bin/env python3
"""Lightweight regression checks for board_parking_controller perception filter."""

from __future__ import annotations

import math
import time

from board_parking_controller import SlotStabilityFilter


def make_info(x, y=0.0, yaw=0.0, px=320.0, py=420.0):
    axis_len = 10.0
    rad = math.radians(yaw)
    dx = axis_len * 0.5 * math.cos(rad)
    dy = axis_len * 0.5 * math.sin(rad)
    return {
        "center_cm": (float(x), float(y)),
        "axis_yaw_deg": float(yaw),
        "approach_axis_cm": [(float(x) - dx, float(y) - dy), (float(x) + dx, float(y) + dy)],
        "center_px": (float(px), float(py)),
        "entrance_mid_px": (float(px), float(py + 80.0)),
        "entrance_edge_px": ((px - 40.0, py + 120.0), (px + 40.0, py + 120.0)),
        "back_edge_px": ((px - 40.0, py - 120.0), (px + 40.0, py - 120.0)),
        "edge_a_px": ((px - 40.0, py + 120.0), (px - 40.0, py - 120.0)),
        "edge_b_px": ((px + 40.0, py + 120.0), (px + 40.0, py - 120.0)),
        "left_edge_px": ((px - 40.0, py + 120.0), (px - 40.0, py - 120.0)),
        "right_edge_px": ((px + 40.0, py + 120.0), (px + 40.0, py - 120.0)),
        "axis_angle_px_deg": -90.0 + float(yaw),
        # Current board controller uses polygon/quadrilateral geometry fields.
        # Keep bbox aliases for compatibility with older diagnostic readers.
        "quad_w_px": 80.0,
        "quad_h_px": 240.0,
        "quad_area_px": 19200.0,
        "bbox_w_px": 80.0,
        "bbox_h_px": 240.0,
        "bbox_area_px": 19200.0,
        "confidence": 0.9,
    }


def test_rejects_single_outlier_without_clearing_window():
    filt = SlotStabilityFilter(3, 4.0, 8.0, gate_static_scale=0.5)
    for x in (10.0, 10.1, 9.9):
        stable, _metrics = filt.add(make_info(x))
    assert stable
    stable, metrics = filt.add(make_info(25.0))
    assert stable
    assert metrics.get("outlier_rejected") is True
    assert filt.is_stable()
    fused = filt.fused()
    assert abs(fused["center_cm"][0] - 10.0) < 0.2


def test_accepts_consistent_outlier_cluster():
    filt = SlotStabilityFilter(3, 4.0, 8.0, outlier_accept_consecutive=3, gate_static_scale=0.5)
    for x in (10.0, 10.1, 9.9):
        filt.add(make_info(x))
    accepted = False
    for x in (25.0, 25.2, 25.1):
        stable, metrics = filt.add(make_info(x))
        accepted = accepted or bool(metrics.get("accepted_outlier_cluster"))
    assert accepted
    assert stable
    fused = filt.fused()
    assert abs(fused["center_cm"][0] - 25.1) < 0.3


def test_hold_last_stable_state_expires():
    filt = SlotStabilityFilter(2, 4.0, 8.0, hold_grace_sec=0.05, hold_max_frames=2)
    filt.add(make_info(10.0))
    stable, _metrics = filt.add(make_info(10.1))
    assert stable
    coasted, metrics = filt.tick_no_detection()
    assert coasted is not None
    assert metrics["hold"] is True
    time.sleep(0.07)
    coasted, metrics = filt.tick_no_detection()
    assert coasted is None
    assert metrics["hold"] is False


def main():
    test_rejects_single_outlier_without_clearing_window()
    test_accepts_consistent_outlier_cluster()
    test_hold_last_stable_state_expires()
    print("perception_filter_tests=PASS")


if __name__ == "__main__":
    main()
