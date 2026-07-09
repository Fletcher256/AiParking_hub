#!/usr/bin/env python3
"""Extract the GS1860 dToF EEPROM calibration block from an EEPROM-only board log."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


EEPROM_RE = re.compile(
    r"^\[DTOF_EEPROM\]\s+ret=(?P<ret>0x[0-9a-fA-F]+|-?\d+)\s+"
    r"len=(?P<len>\d+)\s+nonzero=(?P<nonzero>\d+)\s+byte_sum=(?P<byte_sum>\d+)\s+hex=(?P<hex>[0-9a-fA-F]+)\s*$"
)


def safe_stem(path: Path) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in path.stem)


def parse_log(path: Path) -> dict[str, object]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = EEPROM_RE.match(line.strip())
        if not match:
            continue
        expected_len = int(match.group("len"))
        data = bytes.fromhex(match.group("hex"))
        if len(data) != expected_len:
            raise ValueError(f"EEPROM hex length mismatch on line {line_no}: expected {expected_len}, got {len(data)}")
        nonzero = sum(1 for byte in data if byte)
        byte_sum = sum(data)
        return {
            "source_log": str(path),
            "line": line_no,
            "ret": match.group("ret"),
            "len": expected_len,
            "nonzero": nonzero,
            "byte_sum": byte_sum,
            "reported_nonzero": int(match.group("nonzero")),
            "reported_byte_sum": int(match.group("byte_sum")),
            "sha256": hashlib.sha256(data).hexdigest(),
            "first64_hex": data[:64].hex(),
            "data": data,
        }
    raise ValueError(f"No [DTOF_EEPROM] line found in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_log", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    parsed = parse_log(args.board_log)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or Path("artifacts") / f"dtof_eeprom_{safe_stem(args.board_log)}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = parsed.pop("data")
    bin_path = out_dir / "gs1860_eeprom_521.bin"
    json_path = out_dir / "gs1860_eeprom_521_report.json"
    bin_path.write_bytes(data)
    parsed["bin_path"] = str(bin_path)
    parsed["json_path"] = str(json_path)
    json_path.write_text(json.dumps(parsed, indent=2, sort_keys=True), encoding="utf-8")

    print(f"EEPROM_BIN={bin_path}")
    print(f"EEPROM_JSON={json_path}")
    print(f"EEPROM_SHA256={parsed['sha256']}")
    print(f"EEPROM_LEN={parsed['len']}")
    print(f"EEPROM_NONZERO={parsed['nonzero']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
