#!/usr/bin/env python3
"""Run ON THE VM (ROS2 sourced). Subscribe to /dtof/depth (32FC1, mm) and judge
whether the depth is a coherent scene or noise. Does NOT bind the UDP port, so it
runs alongside the live bridge / Foxglove without stealing packets.

  source /opt/ros/humble/setup.bash
  python3 /tmp/vm_dtof_depth_coherence_ros.py <seconds>
"""
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
W, H = 40, 30


class Collector(Node):
    def __init__(self):
        super().__init__('dtof_coherence')
        self.frames = []
        self.create_subscription(Image, '/dtof/depth', self._cb, 20)

    def _cb(self, msg: Image):
        if msg.encoding != '32FC1' or msg.width != W or msg.height != H:
            return
        arr = np.frombuffer(bytes(msg.data), dtype=np.float32).reshape(H, W).copy()
        self.frames.append(arr)


def main():
    rclpy.init()
    node = Collector()
    t_end = time.time() + DURATION
    while time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.2)
    frames = node.frames
    node.destroy_node()
    rclpy.shutdown()

    n = len(frames)
    print(f"COHERENCE frames={n} duration={DURATION}")
    if n < 3:
        print("NOT_ENOUGH_FRAMES (is the bridge publishing /dtof/depth?)")
        return 1

    stack = np.stack(frames, axis=0)          # (n,H,W), NaN = invalid
    valid = ~np.isnan(stack)
    cov = valid.reshape(n, -1).sum(axis=1)
    print(f"valid_coverage/1200: min={int(cov.min())} median={int(np.median(cov))} "
          f"max={int(cov.max())} ({100*np.median(cov)/(W*H):.0f}% of FOV)")

    # per-pixel temporal std over valid samples
    stds = []
    vfrac = valid.mean(axis=0)
    for r in range(H):
        for c in range(W):
            v = stack[:, r, c]
            v = v[~np.isnan(v)]
            if v.size >= 3:
                stds.append(float(np.std(v)))
    if stds:
        stds = np.array(stds)
        print(f"per_pixel_temporal_std_mm: median={int(np.median(stds))} "
              f"mean={int(stds.mean())}  (LOW<~150=stable scene, HIGH=jumping/noise)")
    print(f"pixels_stable_valid(>80% of frames)={int((vfrac>0.8).sum())}/1200")

    # spatial smoothness on last frame
    last = frames[-1]
    a = last[:, :-1]
    b = last[:, 1:]
    m = ~np.isnan(a) & ~np.isnan(b)
    if m.sum() > 0:
        d = np.abs(a[m] - b[m])
        print(f"spatial_neighbour_absdiff_mm: median={int(np.median(d))} "
              f"mean={int(d.mean())} npairs={int(m.sum())}  "
              f"(LOW=smooth surface, HIGH=salt&pepper noise)")

    centre = stack[:, 11:19, 16:24].reshape(-1)
    centre = centre[~np.isnan(centre)]
    if centre.size:
        print(f"centre8x8: valid_samples={centre.size} min={int(centre.min())} "
              f"median={int(np.median(centre))} max={int(centre.max())} "
              f"mean={int(centre.mean())}")
    else:
        print("centre8x8: NO valid returns (centre all sentinel)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
