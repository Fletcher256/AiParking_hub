#!/usr/bin/env python3
"""Capture RTSP frames with FFmpeg and audit flat/gray failures."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np


def audit_frames(frame_dir: Path, flat_std: float, gray_delta: float) -> dict[str, object]:
    files = sorted(frame_dir.glob("*.jpg"))
    flat: list[tuple[str, float, float, float, int]] = []
    bad_decode: list[str] = []
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
        if luma_std < flat_std and color_delta < gray_delta:
            flat.append(row)
    return {
        "files": len(files),
        "bad_decode": len(bad_decode),
        "flat": len(flat),
        "flat_tail": flat[-8:],
        "stats_tail": stats[-8:],
    }


def run_mode(url: str, root: Path, name: str, args: list[str], seconds: int, flat_std: float, gray_delta: float) -> None:
    out_dir = root / name
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "timeout",
        str(seconds + 4),
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *args,
        "-i",
        url,
        "-an",
        "-vf",
        "scale=768:-2",
        "-q:v",
        "4",
        "-vsync",
        "0",
        "-t",
        str(seconds),
        str(out_dir / "frame_%06d.jpg"),
    ]
    start = time.time()
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.time() - start
    result = audit_frames(out_dir, flat_std, gray_delta)
    print(f"MODE {name}")
    print(f"RC {proc.returncode}")
    print(f"ELAPSED_SEC {elapsed:.2f}")
    print(f"FRAME_DIR {out_dir}")
    print(f"FILES {result['files']}")
    print(f"BAD_DECODE {result['bad_decode']}")
    print(f"FLAT {result['flat']}")
    print(f"FLAT_TAIL {result['flat_tail']}")
    print(f"STATS_TAIL {result['stats_tail']}")
    if proc.stderr.strip():
        print("STDERR_TAIL_BEGIN")
        print("\n".join(proc.stderr.strip().splitlines()[-12:]))
        print("STDERR_TAIL_END")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="rtsp://172.20.10.2:554/live0")
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--flat-std", type=float, default=6.0)
    parser.add_argument("--gray-delta", type=float, default=4.0)
    parser.add_argument("--root", default="/tmp/rtsp_capture_audit")
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    modes = [
        ("tcp_default", ["-rtsp_transport", "tcp"]),
        ("tcp_lowdelay", ["-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay"]),
    ]
    for name, mode_args in modes:
        run_mode(args.url, root, name, mode_args, args.seconds, args.flat_std, args.gray_delta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
