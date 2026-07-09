#!/usr/bin/env python3
"""Record a ROS2 CompressedImage topic to an MP4 file on the VM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class CompressedVideoRecorder(Node):
    def __init__(self, topic: str, output: Path, duration_sec: float, fps: float) -> None:
        super().__init__("parking_yolo_video_recorder")
        self.topic = topic
        self.output = output
        self.duration_sec = duration_sec
        self.fps = fps
        self.started = time.monotonic()
        self.frames = 0
        self.decode_errors = 0
        self.writer: cv2.VideoWriter | None = None
        self.last_shape: tuple[int, int] | None = None
        self.subscription = self.create_subscription(
            CompressedImage,
            topic,
            self._on_image,
            qos_profile_sensor_data,
        )

    def _on_image(self, msg: CompressedImage) -> None:
        data = np.frombuffer(msg.data, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            self.decode_errors += 1
            return
        h, w = frame.shape[:2]
        if self.writer is None:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(str(self.output), fourcc, self.fps, (w, h))
            if not self.writer.isOpened():
                raise RuntimeError(f"failed to open video writer: {self.output}")
            self.last_shape = (w, h)
        if self.last_shape != (w, h):
            frame = cv2.resize(frame, self.last_shape, interpolation=cv2.INTER_AREA)
        self.writer.write(frame)
        self.frames += 1

    def done(self) -> bool:
        return (time.monotonic() - self.started) >= self.duration_sec

    def close(self) -> dict[str, object]:
        if self.writer is not None:
            self.writer.release()
        elapsed = time.monotonic() - self.started
        return {
            "topic": self.topic,
            "output": str(self.output),
            "duration_sec": elapsed,
            "frames": self.frames,
            "decode_errors": self.decode_errors,
            "fps_written": self.frames / elapsed if elapsed > 0 else 0.0,
            "shape": list(self.last_shape) if self.last_shape else None,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/parking/yolo/parking_view")
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-sec", type=float, default=20.0)
    parser.add_argument("--fps", type=float, default=10.0)
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    rclpy.init()
    node = CompressedVideoRecorder(args.topic, output, args.duration_sec, args.fps)
    try:
        while rclpy.ok() and not node.done():
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        stats = node.close()
        node.destroy_node()
        rclpy.shutdown()
    stats_path = output.with_suffix(".json")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print("VIDEO_RECORD_STATS", json.dumps(stats, ensure_ascii=False, separators=(",", ":")))
    print("VIDEO_PATH", output)
    print("STATS_PATH", stats_path)
    return 0 if stats["frames"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
