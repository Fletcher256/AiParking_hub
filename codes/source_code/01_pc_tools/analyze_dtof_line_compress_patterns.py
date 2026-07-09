#!/usr/bin/env python3
"""Inspect saved dToF RAW12+LINE buffers for decode feasibility clues."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROWS = 30
COLS = 40
BINS = 64
MASK_WORDS = COLS * (BINS // 32)


def parse_meta(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def unpack_limited(row: bytes, bit_width: int) -> list[int]:
    out: list[int] = []
    if bit_width == 10:
        for i in range(len(row) // 5):
            b = row[5 * i : 5 * i + 5]
            value = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24) | (b[4] << 32)
            out.extend((value >> (10 * j)) & 0x3FF for j in range(4))
    elif bit_width == 12:
        for i in range(len(row) // 3):
            b = row[3 * i : 3 * i + 3]
            value = b[0] | (b[1] << 8) | (b[2] << 16)
            out.append(value & 0xFFF)
            out.append((value >> 12) & 0xFFF)
    elif bit_width == 16:
        for i in range(len(row) // 2):
            out.append(row[2 * i] | (row[2 * i + 1] << 8))
    else:
        raise ValueError(f"unsupported bit width {bit_width}")
    return out


def sample_groups(vals: list[int], group_size: int = 64) -> dict[str, Any]:
    groups = [vals[i : i + group_size] for i in range(0, len(vals), group_size)]
    complete = [group for group in groups if len(group) == group_size]
    sums = [sum(group) for group in complete]
    maxs = [max(group) for group in complete] if complete else []
    nonzero_group_count = sum(1 for total in sums if total)
    return {
        "complete_64bin_groups": len(complete),
        "nonzero_64bin_groups": nonzero_group_count,
        "first_40_group_sums": sums[:40],
        "first_40_group_max": maxs[:40],
    }


def unpack_summary(row: bytes, bit_width: int, expected_width: int) -> dict[str, Any]:
    bytes_needed = expected_width * bit_width // 8
    vals = unpack_limited(row, bit_width)
    counts = Counter(vals)
    return {
        "bit_width": bit_width,
        "ordinary_bytes_needed_for_width": bytes_needed,
        "fits_within_stride": bytes_needed <= len(row),
        "limited_values": len(vals),
        "nonzero_values": sum(1 for value in vals if value),
        "unique_values": len(counts),
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "top_values": counts.most_common(12),
        **sample_groups(vals),
    }


def one_zero_bit_index(word: int) -> int | None:
    diff = word ^ 0xFFFFFFFF
    if diff and diff & (diff - 1) == 0:
        return diff.bit_length() - 1
    return None


def score_mask_segment(words: list[int], start: int) -> dict[str, Any]:
    segment = words[start : start + MASK_WORDS]
    zero_bits = [one_zero_bit_index(word) for word in segment]
    one_zero_count = sum(bit is not None for bit in zero_bits)
    all_ones_count = sum(word == 0xFFFFFFFF for word in segment)
    other_count = len(segment) - one_zero_count - all_ones_count
    return {
        "start_word": start,
        "word_count": len(segment),
        "one_zero_count": one_zero_count,
        "all_ones_count": all_ones_count,
        "other_count": other_count,
        "score": one_zero_count * 2 + all_ones_count - other_count * 4,
        "first_16_words_hex": [f"0x{word:08x}" for word in segment[:16]],
        "first_32_zero_bits": [bit for bit in zero_bits[:32]],
    }


def best_mask_segment(row: bytes) -> dict[str, Any]:
    words = [int.from_bytes(row[i : i + 4], "little") for i in range(0, len(row) // 4 * 4, 4)]
    candidates = [score_mask_segment(words, start) for start in range(0, 12)]
    best = max(candidates, key=lambda item: item["score"])
    start_byte = int(best["start_word"]) * 4
    end_byte = start_byte + MASK_WORDS * 4
    nonzero_positions = [idx for idx, byte in enumerate(row) if byte]
    nonzero_before = [idx for idx in nonzero_positions if idx < start_byte]
    nonzero_inside = [idx for idx in nonzero_positions if start_byte <= idx < end_byte]
    nonzero_after = [idx for idx in nonzero_positions if idx >= end_byte]
    return {
        "expected_mask_words": MASK_WORDS,
        "expected_mask_bytes": MASK_WORDS * 4,
        "segment_scores": candidates,
        "best": best,
        "best_start_byte": start_byte,
        "best_end_byte": end_byte,
        "nonzero_before_mask": len(nonzero_before),
        "nonzero_inside_mask": len(nonzero_inside),
        "nonzero_after_mask": len(nonzero_after),
        "first_32_after_mask_nonzero_offsets": nonzero_after[:32],
        "after_mask_nonzero_region_hex": row[
            (nonzero_after[0] if nonzero_after else end_byte) :
            ((nonzero_after[-1] + 1) if nonzero_after else end_byte)
        ].hex(" "),
        "expanded_histogram_bytes_per_measurement_row": COLS * BINS * 2,
        "expanded_histogram_bytes_total": ROWS * COLS * BINS * 2,
        "compressed_stride_bytes": len(row),
        "compressed_frame_bytes_without_header_row": ROWS * len(row),
        "stride_smaller_than_one_expanded_histogram_row": len(row) < COLS * BINS * 2,
    }


def mask_sequence_summary(row: bytes) -> dict[str, Any]:
    prefix_len = 0
    for idx, byte in enumerate(row):
        if byte == 0 and idx > 0 and all(b == 0 for b in row[idx:]):
            break
        prefix_len = idx + 1
    prefix = row[:prefix_len]
    words = [int.from_bytes(prefix[i : i + 4], "little") for i in range(0, len(prefix) // 4 * 4, 4)]
    zero_bit_indexes = [one_zero_bit_index(word) for word in words]
    mask_words = [idx for idx in zero_bit_indexes if idx is not None]

    longest_run: list[int] = []
    current: list[int] = []
    for item in zero_bit_indexes:
        if item is None:
            if len(current) > len(longest_run):
                longest_run = current
            current = []
        else:
            current.append(item)
    if len(current) > len(longest_run):
        longest_run = current

    return {
        "prefix_len": prefix_len,
        "word_count": len(words),
        "single_zero_bit_mask_word_count": len(mask_words),
        "single_zero_bit_mask_ratio": len(mask_words) / len(words) if words else 0,
        "longest_single_zero_bit_run_len": len(longest_run),
        "longest_single_zero_bit_run_first32": longest_run[:32],
        "first_32_words_hex": [f"0x{word:08x}" for word in words[:32]],
    }


def analyze(artifact_dir: Path) -> dict[str, Any]:
    rows: list[bytes] = []
    frame_summaries: dict[str, Any] = {}

    for bin_path in sorted(artifact_dir.glob("dtof_line_dump_f*.bin")):
        frame = bin_path.stem.rsplit("f", 1)[-1].lstrip("0") or "0"
        meta_path = bin_path.with_suffix(".meta")
        if not meta_path.exists():
            continue
        meta = parse_meta(meta_path)
        stride = int(meta.get("stride0", "0") or 0)
        height = int(meta.get("height", "0") or 0)
        data = bin_path.read_bytes()
        row_hashes: list[str] = []
        row_nonzero: list[int] = []
        for row_idx in range(height):
            row = data[row_idx * stride : (row_idx + 1) * stride]
            row_hashes.append(sha16(row))
            row_nonzero.append(sum(1 for byte in row if byte))
            if row_idx > 0:
                rows.append(row)
        frame_summaries[frame] = {
            "meta": {k: meta[k] for k in sorted(meta) if k != "compress_param_hex"},
            "row_hashes": row_hashes,
            "row_nonzero": row_nonzero,
        }

    row_hash_counts = Counter(sha16(row) for row in rows)
    common_hash, common_count = row_hash_counts.most_common(1)[0]
    common_row = next(row for row in rows if sha16(row) == common_hash)
    nonzero_positions = [idx for idx, byte in enumerate(common_row) if byte]

    return {
        "artifact_dir": str(artifact_dir),
        "frame_count": len(frame_summaries),
        "measurement_row_count": len(rows),
        "measurement_row_hash_counts": row_hash_counts.most_common(12),
        "common_measurement_row": {
            "hash": common_hash,
            "count": common_count,
            "nonzero_byte_count": len(nonzero_positions),
            "first_nonzero": nonzero_positions[0] if nonzero_positions else None,
            "last_nonzero": nonzero_positions[-1] if nonzero_positions else None,
            "first_128_hex": common_row[:128].hex(" "),
            "last_nonzero_region_hex": common_row[
                max(0, (nonzero_positions[-1] if nonzero_positions else 0) - 64) :
                (nonzero_positions[-1] + 1 if nonzero_positions else 0)
            ].hex(" "),
            "mask_sequence": mask_sequence_summary(common_row),
            "mask_payload_layout": best_mask_segment(common_row),
            "ordinary_unpack_summaries": [
                unpack_summary(common_row, bit_width, expected_width=2560)
                for bit_width in (10, 12, 16)
            ],
        },
        "frame_summaries": frame_summaries,
        "interpretation": {
            "ordinary_raw12_overreads_line": 2560 * 12 // 8 > len(common_row),
            "ordinary_raw16_overreads_line": 2560 * 2 > len(common_row),
            "ordinary_raw10_fits_but_has_sparse_prefix_only": True,
            "notes": [
                "Common measurement rows are dominated by single-zero-bit mask words, not dense histogram samples.",
                "Stride-local ordinary unpacking produces only a few nonzero 64-bin groups, not a 40x64 row.",
                "The existing RAW12 ordinary unpack path expects 3840 bytes per row but RAW12+LINE stride is 3552.",
                "A complete 40x64 16-bit histogram row would require 5120 bytes, larger than the compressed row stride.",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = analyze(args.artifact_dir)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
