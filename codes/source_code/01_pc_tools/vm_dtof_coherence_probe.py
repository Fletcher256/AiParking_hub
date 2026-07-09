#!/usr/bin/env python3
"""Run ON THE VM. Quantify whether the dToF depth is a coherent scene or noise.

Listens UDP 2368, decodes 40x30 depth, and over a capture window computes:
  - valid coverage (fraction of pixels with a non-sentinel return)
  - temporal stability: per-pixel std of depth across frames (low=stable scene)
  - spatial smoothness: mean abs depth diff between horizontal neighbours
  - centre 8x8 region summary
Pure stdlib (no numpy needed but uses it if present).
"""
import socket
import struct
import sys
import time
import statistics

WIDTH = 40
HEIGHT = 30
PIXELS = WIDTH * HEIGHT
HEAD_SIZE = struct.calcsize('<hh Ih II hhh B 12f')  # 73
PIXEL_SIZE = 4
PACKET_SIZE = HEAD_SIZE + PIXELS * PIXEL_SIZE

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 2368


def depths_of(pkt):
    out = []
    off = HEAD_SIZE
    for _ in range(PIXELS):
        (d,) = struct.unpack_from('<h', pkt, off)
        out.append(d)
        off += PIXEL_SIZE
    return out


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', PORT))
    s.settimeout(2.0)

    frames = []
    deadline = time.time() + DURATION
    while time.time() < deadline:
        try:
            data, _ = s.recvfrom(8192)
        except socket.timeout:
            continue
        if len(data) != PACKET_SIZE:
            continue
        frames.append(depths_of(data))
    s.close()

    n = len(frames)
    print(f"COHERENCE packets={n} duration={DURATION}")
    if n < 3:
        print("NOT_ENOUGH_FRAMES")
        return 1

    def valid(d):
        return d != 0 and d != 2

    # coverage per frame
    cov = [sum(1 for d in fr if valid(d)) for fr in frames]
    print(f"valid_coverage/1200 min={min(cov)} median={int(statistics.median(cov))} max={max(cov)} "
          f"({100*statistics.median(cov)/PIXELS:.0f}% of FOV)")

    # per-pixel temporal std over frames where that pixel is valid
    stds = []
    valid_frac = []
    means = []
    for i in range(PIXELS):
        vals = [fr[i] for fr in frames if valid(fr[i])]
        valid_frac.append(len(vals) / n)
        if len(vals) >= 3:
            stds.append(statistics.pstdev(vals))
            means.append(statistics.mean(vals))
    if stds:
        print(f"per_pixel_temporal_std_mm: median={int(statistics.median(stds))} "
              f"mean={int(statistics.mean(stds))} (LOW=stable scene, HIGH=jumping/noise)")
    pix_always_valid = sum(1 for f in valid_frac if f > 0.8)
    print(f"pixels_stable_valid(>80% frames)={pix_always_valid}/{PIXELS}")

    # spatial smoothness: mean abs diff horizontal neighbours, last frame, valid pairs
    fr = frames[-1]
    diffs = []
    for r in range(HEIGHT):
        for c in range(WIDTH - 1):
            a = fr[r * WIDTH + c]
            b = fr[r * WIDTH + c + 1]
            if valid(a) and valid(b):
                diffs.append(abs(a - b))
    if diffs:
        print(f"spatial_neighbour_absdiff_mm: median={int(statistics.median(diffs))} "
              f"mean={int(statistics.mean(diffs))} npairs={len(diffs)} "
              f"(LOW=smooth surface, HIGH=salt&pepper noise)")

    # centre 8x8 region (rows 11-18, cols 16-23)
    cvals = []
    for fr in frames:
        for r in range(11, 19):
            for c in range(16, 24):
                d = fr[r * WIDTH + c]
                if valid(d):
                    cvals.append(d)
    if cvals:
        print(f"centre8x8: valid_samples={len(cvals)} "
              f"min={min(cvals)} median={int(statistics.median(cvals))} max={max(cvals)} "
              f"mean={int(statistics.mean(cvals))}")
    else:
        print("centre8x8: NO valid returns (centre all sentinel)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
