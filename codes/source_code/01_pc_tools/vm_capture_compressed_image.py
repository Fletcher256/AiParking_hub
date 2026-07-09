#!/usr/bin/env python3
"""Capture one ROS2 CompressedImage topic message to a JPEG file."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class CompressedImageCapture(Node):
    def __init__(self, topic: str, output: Path) -> None:
        super().__init__("compressed_image_capture")
        self.output = output
        self.frames = 0
        self.decode_errors = 0
        self.done = False
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
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(self.output), frame):
            raise RuntimeError(f"failed to write {self.output}")
        self.frames += 1
        self.done = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/parking/yolo/parking_view")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    args = parser.parse_args()

    rclpy.init()
    node = CompressedImageCapture(args.topic, Path(args.output).expanduser())
    deadline = time.monotonic() + args.timeout_sec
    try:
        while rclpy.ok() and not node.done and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        frames = node.frames
        errors = node.decode_errors
        node.destroy_node()
        rclpy.shutdown()
    print(f"CAPTURE frames={frames} decode_errors={errors} output={args.output}")
    return 0 if frames else 2


if __name__ == "__main__":
    raise SystemExit(main())
