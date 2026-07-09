#!/usr/bin/env python3
"""Compute the pixel->ground homography (3x3) from the widened calibration points,
so it can be hardcoded into the board-side standalone controller (no cv2 at runtime)."""
import json
from pathlib import Path

CALIB = Path(__file__).resolve().parents[1] / "artifacts" / "calibration_templates" / "slot_homography_rear_axle.wide_20260610.json"
data = json.loads(CALIB.read_text(encoding="utf-8"))
src = data["image_points_px"]
dst = data["ground_points_cm"]
print(f"points: {len(src)}")

H = None
method = None
try:
    import numpy as np
    import cv2
    Hm, mask = cv2.findHomography(np.array(src, dtype="float64"), np.array(dst, dtype="float64"), method=0)
    H = Hm.tolist()
    method = "cv2.findHomography"
except Exception as e:
    print(f"cv2 unavailable ({e}); using numpy DLT")
    import numpy as np
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    A = np.array(A, dtype="float64")
    _, _, Vt = np.linalg.svd(A)
    h = Vt[-1]
    h = h / h[8]
    H = h.reshape(3, 3).tolist()
    method = "numpy DLT"

print(f"method: {method}")
print("H =", json.dumps(H))


def apply_h(H, px, py):
    a = H[0][0] * px + H[0][1] * py + H[0][2]
    b = H[1][0] * px + H[1][1] * py + H[1][2]
    w = H[2][0] * px + H[2][1] * py + H[2][2]
    return (a / w, b / w)


print("--- residuals (predicted ground vs measured) ---")
for (x, y), (u, v) in zip(src, dst):
    gu, gv = apply_h(H, x, y)
    print(f"  px({x},{y}) -> ({gu:.2f},{gv:.2f})  measured ({u},{v})  err ({gu-u:+.2f},{gv-v:+.2f})")
