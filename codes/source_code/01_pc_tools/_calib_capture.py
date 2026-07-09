#!/usr/bin/env python3
"""Capture & average YOLO slot corners_px over a few seconds, canonically ordered
[entrance_left, entrance_right, inside_right, inside_left] to match the calibration
point_order. near edge = larger image y; vehicle-left = smaller image x."""
import json
import time

import rclpy
from std_msgs.msg import String

samples = []


def cb(msg):
    try:
        d = json.loads(msg.data)
        cands = d.get("slot_candidates") or []
        if cands:
            g = cands[0].get("geometry") or {}
            c = g.get("corners_px")
            if c and len(c) == 4:
                samples.append([[float(p[0]), float(p[1])] for p in c])
    except Exception:
        pass


def canon(c):
    s = sorted(c, key=lambda p: p[1])          # ascending image y
    far = sorted(s[:2], key=lambda p: p[0])    # smaller y = inside/far, sort by x
    near = sorted(s[2:], key=lambda p: p[0])   # larger y = entrance/near, sort by x
    return [near[0], near[1], far[1], far[0]]  # entL, entR, insR, insL


rclpy.init()
node = rclpy.create_node("calib_capture")
node.create_subscription(String, "/parking/yolo/parking_detections", cb, 10)
end = time.time() + 5.0
while time.time() < end and rclpy.ok():
    rclpy.spin_once(node, timeout_sec=0.2)
node.destroy_node()
rclpy.shutdown()

if not samples:
    print("NO_DETECTION")
else:
    cs = [canon(s) for s in samples]
    n = len(cs)
    avg = [[round(sum(c[i][0] for c in cs) / n, 1), round(sum(c[i][1] for c in cs) / n, 1)] for i in range(4)]
    spread = [round(max(c[i][0] for c in cs) - min(c[i][0] for c in cs), 1) for i in range(4)]
    print("SAMPLES", n)
    print("CORNERS_PX", json.dumps(avg))
    print("X_SPREAD", json.dumps(spread))
