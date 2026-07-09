import importlib.util
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "board_stm32_button_autopark.py"


def load_module():
    spec = importlib.util.spec_from_file_location("board_stm32_button_autopark_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ButtonAutoparkRecordingTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_default_button_recording_generates_record_env(self):
        args = self.mod.parse_args([])
        self.assertTrue(args.button_record_enable)
        paths = self.mod.button_run_paths(args, "20260708_180000")

        env = self.mod.build_yolo_start_env(args, paths["h264_path"])

        self.assertEqual(env["PARKING_YOLO_RTSP"], "1")
        self.assertEqual(env["PARKING_YOLO_RUN_FOREVER"], "1")
        self.assertEqual(env["PARKING_RECORD_PATH"], paths["h264_path"])
        self.assertTrue(paths["h264_path"].endswith("/button_autopark_20260708_180000.h264"))

    def test_no_button_recording_omits_record_env(self):
        old = os.environ.get("PARKING_RECORD_PATH")
        os.environ["PARKING_RECORD_PATH"] = "/tmp/stale_should_not_leak.h264"
        try:
            args = self.mod.parse_args(["--no-button-record-enable"])
            self.assertFalse(args.button_record_enable)

            env = self.mod.build_yolo_start_env(args, "")

            self.assertNotIn("PARKING_RECORD_PATH", env)
            self.assertNotIn("PARKING_YOLO_RTSP", env)
        finally:
            if old is None:
                os.environ.pop("PARKING_RECORD_PATH", None)
            else:
                os.environ["PARKING_RECORD_PATH"] = old

    def test_button_record_paths_share_same_timestamp_stem(self):
        args = self.mod.parse_args([])
        stamp = "20260708_180001"

        paths = self.mod.button_run_paths(args, stamp)

        self.assertEqual(paths["stem"], f"button_autopark_{stamp}")
        self.assertEqual(
            paths["log_jsonl"],
            f"{args.state_dir}/button_autopark_{stamp}.jsonl",
        )
        self.assertEqual(
            paths["stdout_log"],
            f"{args.state_dir}/button_autopark_{stamp}.log",
        )
        self.assertEqual(
            paths["h264_path"],
            f"{args.button_record_dir}/button_autopark_{stamp}.h264",
        )
        self.assertEqual(
            paths["record_meta"],
            f"{args.button_record_dir}/button_autopark_{stamp}.record_meta.json",
        )


if __name__ == "__main__":
    unittest.main()
