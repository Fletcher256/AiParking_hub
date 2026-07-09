#!/usr/bin/env python3
"""Run ON THE VM. Listen on UDP 2368, decode dToF packets into a 40x30 depth
grid, and print a spatial near-field heatmap + temporal near/far state.

Pure stdlib (no numpy) so it runs on the VM unmodified.
"""
from __future__ import annotations

import socket
import struct
import sys
import time

WIDTH = 40
HEIGHT = 30
PIXELS = WIDTH * HEIGHT
HEADER_FMT = "<hhIhIIhhhB12f"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
PIXEL_SIZE = 4
PACKET_SIZE = HEADER_SIZE + PIXELS * PIXEL_SIZE

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 2368
NEAR_MM = 1000  # "near" threshold


def decode_depths(packet: bytes):
    depths = []
    off = HEADER_SIZE
    for _ in range(PIXELS):
        (d,) = struct.unpack_from("<h", packet, off)
        depths.append(d)
        off += PIXEL_SIZE
    return depths


def main() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))
    s.settimeout(2.0)

    valid_near_count = [0] * PIXELS   # times pixel was a valid (non-sentinel) <1m return
    valid_any_count = [0] * PIXELS    # times pixel was valid (non-0, non-2mm)
    near_depth_sum = [0] * PIXELS
    packets = 0
    near_state_packets = 0  # packets whose valid pixels are majority <1m
    far_state_packets = 0
    valid_counts = []
    deadline = time.time() + DURATION

    while time.time() < deadline:
        try:
            data, _ = s.recvfrom(8192)
        except socket.timeout:
            continue
        if len(data) != PACKET_SIZE:
            continue
        packets += 1
        depths = decode_depths(data)
        valid = 0
        near = 0
        for i, d in enumerate(depths):
            if d != 0 and d != 2:  # 2mm = sentinel
                valid += 1
                valid_any_count[i] += 1
                if 0 < d < NEAR_MM:
                    valid_near_count[i] += 1
                    near_depth_sum[i] += d
                    near += 1
        valid_counts.append(valid)
        if valid > 0 and near * 2 >= valid:
            near_state_packets += 1
        else:
            far_state_packets += 1

    s.close()

    print(f"SPATIAL_PROBE packets={packets} duration={DURATION}")
    if packets == 0:
        print("NO_PACKETS")
        return 1
    vc_sorted = sorted(valid_counts)
    print(f"valid_per_pkt min={min(valid_counts)} median={vc_sorted[len(vc_sorted)//2]} max={max(valid_counts)}")
    print(f"state_split near_state_pkts={near_state_packets} far_state_pkts={far_state_packets}")

    # pixels that resolve to <1m in a meaningful fraction of packets
    hot = [(valid_near_count[i], i) for i in range(PIXELS) if valid_near_count[i] > 0]
    hot.sort(reverse=True)
    print(f"pixels_ever_near={len(hot)} (of {PIXELS})")
    print("TOP_NEAR_PIXELS (row,col,hits,avg_mm):")
    for hits, i in hot[:25]:
        r, c = divmod(i, WIDTH)
        avg = near_depth_sum[i] // max(1, valid_near_count[i])
        print(f"  r{r:02d}c{c:02d} hits={hits} avg={avg}mm")

    # compact heatmap: '#' if pixel is near in >50% of packets, '+' if >0, '.' otherwise
    print("NEAR_HEATMAP (40 wide x 30 tall, '#'=>50%% near, '+'=some, '.'=never):")
    for r in range(HEIGHT):
        row = []
        for c in range(WIDTH):
            i = r * WIDTH + c
            frac = valid_near_count[i] / packets
            row.append("#" if frac > 0.5 else ("+" if valid_near_count[i] > 0 else "."))
        print("  " + "".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
