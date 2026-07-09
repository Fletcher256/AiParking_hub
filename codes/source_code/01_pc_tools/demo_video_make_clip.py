#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Make an MP4 clip from composite PNG frames if ffmpeg is available."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from demo_video_utils import ensure_dir, list_images


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--hold-sec", type=float, default=0.0)
    args = ap.parse_args()
    frames = list_images(Path(args.frames_dir))
    out = Path(args.out)
    ensure_dir(out.parent)
    if not frames:
        print("NO_FRAMES", args.frames_dir)
        return 2
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("FFMPEG_NOT_FOUND; image sequence kept at", args.frames_dir)
        return 0
    fps = max(0.1, float(args.fps))
    with tempfile.TemporaryDirectory(prefix="parking_demo_clip_") as td:
        tmp = Path(td)
        dup = max(1, int(round(max(0.0, float(args.hold_sec)) * fps))) if args.hold_sec else 1
        n = 1
        for frame in frames:
            for _ in range(dup):
                shutil.copy2(frame, tmp / f"frame_{n:04d}.png")
                n += 1
        cmd = [
            ffmpeg, "-y", "-framerate", str(fps), "-i", str(tmp / "frame_%04d.png"),
            "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out),
        ]
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        if cp.returncode != 0:
            print("FFMPEG_FAILED")
            print(cp.stdout[-2000:])
            return cp.returncode
    print("MP4", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
