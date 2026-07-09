#!/usr/bin/env python3
"""Evaluate whether RAW12+LINE dToF rows contain a 40x64 bin activity mask."""

from __future__ import annotations

import argparse
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


def one_zero_bit_index(word: int) -> int | None:
    diff = word ^ 0xFFFFFFFF
    if diff and diff & (diff - 1) == 0:
        return diff.bit_length() - 1
    return None


def row_words(row: bytes) -> list[int]:
    return [int.from_bytes(row[i : i + 4], "little") for i in range(0, len(row) // 4 * 4, 4)]


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


def active_bins_from_segment(words: list[int], start: int) -> list[list[int]]:
    segment = words[start : start + MASK_WORDS]
    out: list[list[int]] = []
    for col in range(COLS):
        bins: list[int] = []
        for half in range(BINS // 32):
            idx = col * 2 + half
            if idx >= len(segment):
                continue
            bit = one_zero_bit_index(segment[idx])
            if bit is not None:
                bins.append(half * 32 + bit)
        out.append(bins)
    return out


def analyze_frame(bin_path: Path) -> dict[str, Any]:
    meta = parse_meta(bin_path.with_suffix(".meta"))
    stride = int(meta["stride0"])
    height = int(meta["height"])
    data = bin_path.read_bytes()
    rows = [data[idx * stride : (idx + 1) * stride] for idx in range(height)]

    first_measurement_words = row_words(rows[1])
    segment_scores = [score_mask_segment(first_measurement_words, start) for start in range(0, 12)]
    best = max(segment_scores, key=lambda item: item["score"])
    best_start = int(best["start_word"])

    per_row: list[dict[str, Any]] = []
    peak_counter: Counter[int] = Counter()
    signature_counter: Counter[str] = Counter()
    decoded_rows = 0

    for row_idx in range(1, min(height, ROWS + 1)):
        words = row_words(rows[row_idx])
        bins_by_col = active_bins_from_segment(words, best_start)
        row_peaks = [tuple(bins) for bins in bins_by_col]
        signature = "|".join(",".join(str(v) for v in bins) for bins in row_peaks)
        signature_counter[signature] += 1
        active_cols = sum(1 for bins in bins_by_col if bins)
        active_bins = [value for bins in bins_by_col for value in bins]
        peak_counter.update(active_bins)
        if active_cols:
            decoded_rows += 1
        per_row.append({
            "row_index": row_idx,
            "active_cols": active_cols,
            "active_bin_count": len(active_bins),
            "first_10_cols": bins_by_col[:10],
            "bin_counts": Counter(active_bins).most_common(12),
        })

    return {
        "frame": bin_path.stem,
        "meta": {k: meta[k] for k in sorted(meta) if k != "compress_param_hex"},
        "best_segment": best,
        "segment_scores": segment_scores,
        "decoded_rows": decoded_rows,
        "row_signature_counts": signature_counter.most_common(8),
        "active_bin_counts": peak_counter.most_common(24),
        "first_rows": per_row[:6],
    }


def analyze(artifact_dir: Path) -> dict[str, Any]:
    frames = [analyze_frame(path) for path in sorted(artifact_dir.glob("dtof_line_dump_f*.bin"))]
    starts = Counter(frame["best_segment"]["start_word"] for frame in frames)
    bin_counts: Counter[int] = Counter()
    for frame in frames:
        for bin_idx, count in frame["active_bin_counts"]:
            bin_counts[int(bin_idx)] += int(count)
    return {
        "artifact_dir": str(artifact_dir),
        "frame_count": len(frames),
        "expected_mask_words": MASK_WORDS,
        "best_start_word_counts": starts.most_common(),
        "aggregate_active_bin_counts": bin_counts.most_common(32),
        "frames": frames,
        "interpretation": {
            "mask_words_match_40x64": MASK_WORDS == 80,
            "candidate_meaning": (
                "If one cleared bit marks one active histogram bin in each 32-bin half, "
                "the 80-word segment maps exactly to 40 columns * 64 bins."
            ),
            "caveat": (
                "This is a structural hypothesis only. It does not yet recover amplitudes "
                "or prove that DtofProcess will accept the reconstructed histogram."
            ),
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
