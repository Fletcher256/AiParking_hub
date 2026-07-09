#!/usr/bin/env python3
"""Analyze saved SS928 dToF line-compressed dump frames."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def parse_meta(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def parse_hex_bytes(text: str) -> bytes:
    if not text:
        return b""
    return bytes(int(part, 16) for part in text.split())


def first_u32_values(data: bytes, count: int = 16) -> list[int]:
    values: list[int] = []
    for i in range(min(count, len(data) // 4)):
        values.append(int.from_bytes(data[i * 4 : i * 4 + 4], "little"))
    return values


def short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def analyze_frame(bin_path: Path, meta_path: Path) -> dict[str, object]:
    meta = parse_meta(meta_path)
    data = bin_path.read_bytes()
    stride = int(meta.get("stride0", "0") or 0)
    height = int(meta.get("height", "0") or 0)
    compress_param = parse_hex_bytes(meta.get("compress_param_hex", ""))

    row_groups: dict[str, list[int]] = {}
    row_nonzero: list[int] = []
    row_sums: list[int] = []
    if stride and height:
        for row_idx in range(height):
            row = data[row_idx * stride : (row_idx + 1) * stride]
            row_groups.setdefault(short_hash(row), []).append(row_idx)
            row_nonzero.append(sum(1 for byte in row if byte))
            row_sums.append(sum(row))

    row1 = data[stride : 2 * stride] if stride and len(data) >= 2 * stride else b""
    return {
        "meta": {key: meta[key] for key in sorted(meta) if key != "compress_param_hex"},
        "file_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "compress_param_sha256": hashlib.sha256(compress_param).hexdigest() if compress_param else "",
        "compress_param_sum": sum(compress_param),
        "compress_param_nonzero_count": sum(1 for byte in compress_param if byte),
        "compress_param_u32_first16": first_u32_values(compress_param),
        "row_groups": row_groups,
        "row_nonzero_first8": row_nonzero[:8],
        "row_sums_first8": row_sums[:8],
        "row1_nonzero": sum(1 for byte in row1 if byte),
        "row1_first64_hex": " ".join(f"{byte:02x}" for byte in row1[:64]),
        "row1_last64_hex": " ".join(f"{byte:02x}" for byte in row1[-64:]) if row1 else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    artifact_dir = args.artifact_dir
    frames: dict[str, object] = {}
    for bin_path in sorted(artifact_dir.glob("dtof_line_dump_f*.bin")):
        frame_id = bin_path.stem.rsplit("f", 1)[-1].lstrip("0") or "0"
        meta_path = bin_path.with_suffix(".meta")
        if not meta_path.exists():
            continue
        frames[frame_id] = analyze_frame(bin_path, meta_path)

    report = {"artifact_dir": str(artifact_dir), "frames": frames}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
