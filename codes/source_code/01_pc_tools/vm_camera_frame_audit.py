#!/usr/bin/env python3
"""Audit recorded camera JPEG frames for flat/gray failures on the VM."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def latest_session(record_root: Path) -> Path:
    sessions = sorted(record_root.glob("session_*"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise SystemExit(f"no session_* directory under {record_root}")
    return sessions[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record_root", nargs="?", default="")
    parser.add_argument("--sample", type=int, default=1500)
    parser.add_argument("--flat-std", type=float, default=6.0)
    parser.add_argument("--gray-delta", type=float, default=1.2)
    args = parser.parse_args()

    if args.record_root:
        record_root = Path(args.record_root)
    else:
        record_file = Path("/tmp/parking_sensor_link/parking_record_dir")
        record_root = Path(record_file.read_text().strip())
    session = latest_session(record_root)
    files = sorted((session / "camera_frames").glob("*.jpg"))[-args.sample :]
    bad_decode: list[str] = []
    flat: list[tuple[str, float, float, float, int]] = []
    grayish: list[tuple[str, float, float, float, int]] = []
    stats: list[tuple[str, float, float, float, int]] = []

    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            bad_decode.append(path.name)
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean = float(gray.mean())
        luma_std = float(gray.std())
        b = img[:, :, 0].astype(np.int16)
        g = img[:, :, 1].astype(np.int16)
        r = img[:, :, 2].astype(np.int16)
        color_delta = float(np.mean(np.abs(b - g) + np.abs(g - r) + np.abs(b - r)) / 3.0)
        row = (path.name, mean, luma_std, color_delta, path.stat().st_size)
        stats.append(row)
        if luma_std < args.flat_std:
            flat.append(row)
        if color_delta < args.gray_delta:
            grayish.append(row)

    print("SESSION", session)
    print("FILES", len(files))
    print("BAD_DECODE", len(bad_decode))
    print("FLAT_COUNT", len(flat))
    print("GRAYISH_COUNT", len(grayish))
    print("LAST_FLAT", flat[-8:])
    print("LAST_GRAYISH", grayish[-8:])
    if stats:
        means = np.array([s[1] for s in stats], dtype=np.float32)
        luma_stds = np.array([s[2] for s in stats], dtype=np.float32)
        color_deltas = np.array([s[3] for s in stats], dtype=np.float32)
        sizes = np.array([s[4] for s in stats], dtype=np.float32)
        print("MEAN_RANGE", float(means.min()), float(means.max()))
        print("LUMA_STD_RANGE", float(luma_stds.min()), float(luma_stds.max()))
        print("COLOR_DELTA_RANGE", float(color_deltas.min()), float(color_deltas.max()))
        print("SIZE_RANGE", int(sizes.min()), int(sizes.max()))
        print("LAST_STATS", stats[-8:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
