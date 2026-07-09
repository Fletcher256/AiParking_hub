#!/usr/bin/env python3
"""Unit tests for parking_controller_core (pure stdlib, offline)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parking_controller_core as core  # noqa: E402


class ConfigLoadingTests(unittest.TestCase):
    def test_success_criteria_fallback_is_deep_copy(self):
        first = core.load_success_criteria("")
        first["done"]["slot_x_err_px_abs_max"] = 999.0
        second = core.load_success_criteria("")
        self.assertEqual(second["done"]["slot_x_err_px_abs_max"], 15.0)

    def test_perception_filter_deep_merge(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as fh:
            json.dump({"line_accumulator": {"enabled": True}}, fh)
            path = fh.name
        try:
            cfg = core.load_perception_filter(path)
        finally:
            os.unlink(path)
        self.assertTrue(cfg["line_accumulator"]["enabled"])
        self.assertIn("max_track_age_sec", cfg["line_accumulator"])


class CriteriaTests(unittest.TestCase):
    def stable_state(self, **corridor_overrides):
        corridor = {
            "slot_x_err_px": 0.0,
            "min_margin_px": 100.0,
            "line_risk": False,
        }
        corridor.update(corridor_overrides)
        return {
            "stable_frames": 3,
            "corridor": corridor,
            "image": {"slot_heading_err_deg": 0.0},
            "ground_estimate": {"slot_y_dist_cm": 5.0},
            "gates": {"stable_enough": True},
        }

    def test_evaluate_parked(self):
        verdict = core.evaluate_parking_criteria(
            self.stable_state(), core.load_success_criteria(""))
        self.assertEqual(verdict["verdict"], "parked")
        self.assertEqual(verdict["reason"], "success_criteria_met")

    def test_line_risk_aborts(self):
        verdict = core.evaluate_parking_criteria(
            self.stable_state(line_risk=True), core.load_success_criteria(""))
        self.assertEqual(verdict["verdict"], "aborted")
        self.assertEqual(verdict["reason"], "line_risk")


if __name__ == "__main__":
    unittest.main()
