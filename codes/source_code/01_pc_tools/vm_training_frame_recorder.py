#!/usr/bin/env python3
"""Save CompressedImage frames from a ROS2 topic at a fixed sampling rate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class TrainingFrameRecorder(Node):
    def __init__(self, topic: str, output_dir: Path, fps: float) -> None:
        super().__init__("parking_training_frame_recorder")
        self.topic = topic
        self.output_dir = output_dir
        self.image_dir = output_dir / "images"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.interval_sec = 1.0 / max(0.001, fps)
        self.started_wall = time.strftime("%Y-%m-%d %H:%M:%S")
        self.started_monotonic = time.monotonic()
        self.last_saved_monotonic = 0.0
        self.received_frames = 0
        self.saved_frames = 0
        self.running = True
        self.metadata_path = output_dir / "frames.jsonl"
        self.summary_path = output_dir / "summary.json"
        self.metadata = self.metadata_path.open("a", encoding="utf-8")
        self.subscription = self.create_subscription(
            CompressedImage,
            topic,
            self._on_image,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            f"training recorder started: topic={topic}, output={self.image_dir}, fps={fps:.3f}"
        )

    def _on_image(self, msg: CompressedImage) -> None:
        self.received_frames += 1
        now = time.monotonic()
        if self.saved_frames > 0 and (now - self.last_saved_monotonic) < self.interval_sec:
            return
        self.last_saved_monotonic = now
        self.saved_frames += 1
        filename = f"frame_{self.saved_frames:06d}.jpg"
        path = self.image_dir / filename
        path.write_bytes(bytes(msg.data))
        row = {
            "index": self.saved_frames,
            "filename": str(Path("images") / filename),
            "topic": self.topic,
            "stamp_sec": int(msg.header.stamp.sec),
            "stamp_nanosec": int(msg.header.stamp.nanosec),
            "frame_id": msg.header.frame_id,
            "format": msg.format,
            "bytes": len(msg.data),
            "recv_time_unix": time.time(),
        }
        self.metadata.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.metadata.flush()

    def stop(self) -> None:
        self.running = False

    def close(self) -> dict[str, object]:
        elapsed = max(0.0, time.monotonic() - self.started_monotonic)
        summary = {
            "topic": self.topic,
            "output_dir": str(self.output_dir),
            "started_wall": self.started_wall,
            "finished_wall": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": elapsed,
            "received_frames": self.received_frames,
            "saved_frames": self.saved_frames,
            "target_fps": 1.0 / self.interval_sec,
            "actual_saved_fps": self.saved_frames / elapsed if elapsed > 0.0 else 0.0,
        }
        if not self.metadata.closed:
            self.metadata.close()
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/parking/camera/yolo_input_jpeg")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fps", type=float, default=3.0)
    args = parser.parse_args()

    rclpy.init()
    node = TrainingFrameRecorder(args.topic, Path(args.output_dir).expanduser(), args.fps)

    def handle_stop(_signum, _frame) -> None:
        node.stop()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)
    try:
        while rclpy.ok() and node.running:
            rclpy.spin_once(node, timeout_sec=0.2)
    finally:
        summary = node.close()
        node.destroy_node()
        rclpy.shutdown()
    print("TRAINING_CAPTURE_SUMMARY", json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
