#!/usr/bin/env python3
"""
Simulates the SS928 dToF UDP sender for testing the dtof_bridge ROS2 node.
Sends synthetic TofDataUdpPacket frames to a target host:port.

Usage:
  python3 dtof_sim_sender.py [host] [port] [fps]
  python3 dtof_sim_sender.py 192.168.137.100 7777 5
"""

import socket, struct, time, math, sys, random

TARGET_HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.137.100"
TARGET_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
FPS         = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0

PIXELS_H = 30
PIXELS_W = 40
PIXELS   = PIXELS_H * PIXELS_W

# Fake calibration (reasonable for a 30x40 ToF sensor)
FX, FY   = 30.0, 30.0   # focal length in pixels
CX, CY   = 19.5, 14.5   # principal point

HEAD_FMT  = '<hh Ih II hhh B 12f'
PIXEL_FMT = '<hBB'

def make_packet(seq: int, depths) -> bytes:
    t = time.time()
    ts_sec  = int(t)
    ts_nsec = int((t - ts_sec) * 1e9)

    # Build header
    head = struct.pack(HEAD_FMT,
        0,            # checkSum
        seq & 0x7fff, # seqNum
        0,            # startPixel
        PIXELS,       # pixelNumber
        ts_sec, ts_nsec,
        PIXELS_W, PIXELS_H, int(FPS),
        1,            # version
        FX, FY, CX, CY,           # reserved[0..3]: fx, fy, cx, cy
        0.0, 0.0, 0.0, 0.0, 0.0,  # k1..k3, p1, p2
        0.0, 0.0, 0.0              # reserved[9..11]
    )

    # Build pixel data
    pixels = b""
    for i, d in enumerate(depths.flat):
        depth_mm = int(d)
        conf     = min(255, max(0, 200 - abs(depth_mm - 1500) // 10))
        flag     = 0
        pixels  += struct.pack(PIXEL_FMT, depth_mm, conf, flag)

    return head + pixels

def make_depths(frame: int):
    """Generate a simple moving depth pattern (sphere-ish)."""
    import numpy as np
    depths = np.zeros((PIXELS_H, PIXELS_W), dtype=np.float32)
    t = frame / FPS
    cx, cy = PIXELS_W / 2 + math.sin(t) * 5, PIXELS_H / 2 + math.cos(t * 0.7) * 3
    for v in range(PIXELS_H):
        for u in range(PIXELS_W):
            r = math.sqrt((u - cx) ** 2 + (v - cy) ** 2)
            depth = 1000.0 + 500.0 * math.exp(-r * r / 50.0)  # peak at ~1500mm
            depths[v, u] = depth + random.gauss(0, 5)
    return depths

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / FPS
    print(f"Sending dToF packets to {TARGET_HOST}:{TARGET_PORT} at {FPS} fps")
    print(f"Packet size: {struct.calcsize(HEAD_FMT) + PIXELS * struct.calcsize(PIXEL_FMT)} bytes")
    print("Ctrl+C to stop\n")

    frame = 0
    try:
        while True:
            t0 = time.time()
            depths = make_depths(frame)
            pkt = make_packet(frame, depths)
            sock.sendto(pkt, (TARGET_HOST, TARGET_PORT))
            elapsed = time.time() - t0
            print(f"\rFrame {frame:5d}  depth[15][20]={depths[15,20]:.0f}mm  "
                  f"pkt={len(pkt)}B  {elapsed*1000:.1f}ms", end="", flush=True)
            frame += 1
            time.sleep(max(0, interval - elapsed))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
