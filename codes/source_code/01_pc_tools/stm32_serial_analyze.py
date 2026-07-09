#!/usr/bin/env python3
"""Analyze raw STM32 serial captures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros" / "parking_bridge"))

from parking_bridge.stm32_protocol import analyze_bytes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_file", type=Path)
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Optional capture duration in seconds for a byte-rate estimate.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=4096,
        help="Number of leading bytes to use for protocol-shape classification.",
    )
    args = parser.parse_args()
    data = args.raw_file.read_bytes()
    result = analyze_bytes(data, sample_limit=args.sample_limit)
    if args.duration > 0:
        result["duration_seconds"] = args.duration
        result["byte_rate_Bps_estimate"] = len(data) / args.duration
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
