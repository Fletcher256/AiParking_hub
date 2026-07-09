#!/usr/bin/env python3
"""Send raw bytes to the board serial port and print the response."""

from __future__ import annotations

import argparse
import time


def parse_bytes(text: str) -> bytes:
    out = bytearray()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part, 0))
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM11")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--bytes", required=True, help="Comma-separated bytes, e.g. 0x03,13,10")
    parser.add_argument("--read-seconds", type=float, default=1.0)
    args = parser.parse_args()

    import serial

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    try:
        ser.write(parse_bytes(args.bytes))
        ser.flush()
        time.sleep(args.read_seconds)
        data = ser.read(16384)
    finally:
        ser.close()
    print(data.decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
