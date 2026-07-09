#!/usr/bin/env python3
"""Inspect recorded dToF packets for depth/preview troubleshooting."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import struct
import sys

import numpy as np


WIDTH = 40
HEIGHT = 30
PIXELS = WIDTH * HEIGHT
HEADER_FMT = "<hhIhIIhhhB12f"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
PIXEL_SIZE = 4
PACKET_SIZE = HEADER_SIZE + PIXELS * PIXEL_SIZE


def latest_session(root: Path) -> Path:
    sessions = sorted(root.glob("session_*"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise SystemExit(f"no session_* under {root}")
    return sessions[-1]


def summarize(name: str, values: np.ndarray) -> None:
    flat = values.reshape(-1)
    print(f"{name}_dtype", flat.dtype)
    print(f"{name}_min", int(flat.min()) if flat.size else None)
    print(f"{name}_max", int(flat.max()) if flat.size else None)
    print(f"{name}_mean", float(flat.mean()) if flat.size else None)
    print(f"{name}_unique_count", int(np.unique(flat).size))
    common = Counter(int(x) for x in flat[: min(flat.size, 1200)]).most_common(12)
    print(f"{name}_top", common)


def parse_packet(packet: bytes, packet_index: int) -> None:
    print("PACKET_INDEX", packet_index)
    print("PACKET_LEN", len(packet))
    fields = struct.unpack_from(HEADER_FMT, packet, 0)
    print(
        "HEADER",
        json.dumps(
            {
                "checksum": fields[0],
                "seq_num": fields[1],
                "start_pixel": fields[2],
                "pixel_number": fields[3],
                "device_time_sec": fields[4],
                "device_time_nsec": fields[5],
                "width": fields[6],
                "height": fields[7],
                "frame_rate": fields[8],
                "version": fields[9],
                "calibration_first4": [float(x) for x in fields[10:14]],
            },
            ensure_ascii=False,
        ),
    )
    payload = packet[HEADER_SIZE:]
    print("PAYLOAD_FIRST_64_HEX", payload[:64].hex())
    print("PAYLOAD_LAST_64_HEX", payload[-64:].hex())

    official = np.frombuffer(
        payload,
        dtype=np.dtype([("depth", "<i2"), ("confidence", "u1"), ("flag", "u1")]),
        count=PIXELS,
    )
    summarize("OFFICIAL_DEPTH_I16", official["depth"])
    summarize("OFFICIAL_CONF_U8", official["confidence"])
    summarize("OFFICIAL_FLAG_U8", official["flag"])

    u16_first = np.frombuffer(payload, dtype="<u2", count=PIXELS * 2)
    summarize("ALL_U16_WORDS", u16_first)
    even_words = u16_first[0::2][:PIXELS]
    odd_words = u16_first[1::2][:PIXELS]
    summarize("EVEN_U16_WORDS", even_words)
    summarize("ODD_U16_WORDS", odd_words)

    bytes_u8 = np.frombuffer(payload, dtype="u1")
    for offset in range(4):
        summarize(f"BYTE_STREAM_OFFSET_{offset}", bytes_u8[offset::4][:PIXELS])


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        record_file = Path("/tmp/parking_sensor_link/parking_record_dir")
        if not record_file.exists():
            raise SystemExit("missing /tmp/parking_sensor_link/parking_record_dir")
        root = Path(record_file.read_text(errors="replace").strip())
    session = latest_session(root)
    print("RECORD_ROOT", root)
    print("SESSION", session)
    packet_path = session / "dtof_packets.bin"
    size = packet_path.stat().st_size
    print("DTOF_PACKET_FILE", packet_path)
    print("DTOF_PACKET_BYTES", size)
    print("DTOF_PACKET_COUNT_BY_SIZE", size // PACKET_SIZE)
    if size < PACKET_SIZE:
        raise SystemExit("packet file too small")
    with packet_path.open("rb") as handle:
        for index in [0, max(0, size // PACKET_SIZE // 2), max(0, size // PACKET_SIZE - 1)]:
            handle.seek(index * PACKET_SIZE)
            packet = handle.read(PACKET_SIZE)
            parse_packet(packet, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
