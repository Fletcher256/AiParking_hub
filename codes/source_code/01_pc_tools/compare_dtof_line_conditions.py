#!/usr/bin/env python3
"""Compare SS928 dToF RAW12+LINE dumps captured under known conditions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROWS = 30
COLS = 40
BINS = 64
MASK_WORDS = COLS * (BINS // 32)


def parse_condition(value: str) -> tuple[str, Path]:
    if "=" in value:
        label, path = value.split("=", 1)
        return label.strip(), Path(path)
    path = Path(value)
    return path.name, path


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


def sha16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def one_zero_bit_index(word: int) -> int | None:
    diff = word ^ 0xFFFFFFFF
    if diff and diff & (diff - 1) == 0:
        return diff.bit_length() - 1
    return None


def row_words(row: bytes) -> list[int]:
    return [int.from_bytes(row[i : i + 4], "little") for i in range(0, len(row) // 4 * 4, 4)]


def score_mask_segment(words: list[int], start: int) -> int:
    segment = words[start : start + MASK_WORDS]
    one_zero_count = sum(one_zero_bit_index(word) is not None for word in segment)
    all_ones_count = sum(word == 0xFFFFFFFF for word in segment)
    other_count = len(segment) - one_zero_count - all_ones_count
    return one_zero_count * 2 + all_ones_count - other_count * 4


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


def mode_bytes(rows_by_index: dict[int, list[bytes]], stride: int) -> dict[int, bytes]:
    modes: dict[int, bytes] = {}
    for row_idx, rows in rows_by_index.items():
        if not rows:
            continue
        output = bytearray(stride)
        for offset in range(stride):
            counts = Counter(row[offset] for row in rows if offset < len(row))
            output[offset] = counts.most_common(1)[0][0] if counts else 0
        modes[row_idx] = bytes(output)
    return modes


def compress_param_summary(meta: dict[str, str]) -> dict[str, Any]:
    data = parse_hex_bytes(meta.get("compress_param_hex", ""))
    u32 = [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data) // 4 * 4, 4)]
    u16 = [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data) // 2 * 2, 2)]
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest() if data else "",
        "nonzero_count": sum(1 for byte in data if byte),
        "sum": sum(data),
        "u32_le": u32,
        "u16_le_first32": u16[:32],
        "candidate_known_u32": {
            "word7_width": u32[7] if len(u32) > 7 else None,
            "word8_height": u32[8] if len(u32) > 8 else None,
            "word28_ordinary_raw10_bytes_per_row": u32[28] if len(u32) > 28 else None,
            "word33_aligned_delta_a": u32[33] if len(u32) > 33 else None,
            "word34_aligned_delta_b": u32[34] if len(u32) > 34 else None,
            "word35_raw12_stride_deficit": u32[35] if len(u32) > 35 else None,
        },
    }


def read_condition(label: str, artifact_dir: Path) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    rows_by_index: dict[int, list[bytes]] = defaultdict(list)
    all_measurement_rows: list[bytes] = []
    meta_counter: Counter[tuple[tuple[str, str], ...]] = Counter()

    for bin_path in sorted(artifact_dir.glob("dtof_line_dump_f*.bin")):
        meta_path = bin_path.with_suffix(".meta")
        if not meta_path.exists():
            continue
        meta = parse_meta(meta_path)
        stride = int(meta.get("stride0", "0") or 0)
        height = int(meta.get("height", "0") or 0)
        data = bin_path.read_bytes()
        frame_rows: list[bytes] = []
        for row_idx in range(height):
            row = data[row_idx * stride : (row_idx + 1) * stride]
            frame_rows.append(row)
            if 1 <= row_idx <= ROWS:
                rows_by_index[row_idx].append(row)
                all_measurement_rows.append(row)

        meta_key = tuple(
            sorted(
                (key, meta.get(key, ""))
                for key in ("width", "height", "stride0", "pixel_format", "compress_mode", "size")
            )
        )
        meta_counter[meta_key] += 1
        frames.append(
            {
                "path": str(bin_path),
                "meta": meta,
                "sha16": sha16(data),
                "row_hashes": [sha16(row) for row in frame_rows],
            }
        )

    if not frames:
        raise SystemExit(f"no dtof_line_dump_f*.bin frames found in {artifact_dir}")

    first_meta = frames[0]["meta"]
    stride = int(first_meta.get("stride0", "0") or 0)
    common_rows = Counter(sha16(row) for row in all_measurement_rows)
    mode_by_row = mode_bytes(rows_by_index, stride)

    mask_start_counts: Counter[int] = Counter()
    active_bin_counts: Counter[int] = Counter()
    row_signature_counts: Counter[str] = Counter()
    for row in all_measurement_rows:
        words = row_words(row)
        scores = {start: score_mask_segment(words, start) for start in range(0, 12)}
        best_start = max(scores, key=scores.get)
        mask_start_counts[best_start] += 1
        bins_by_col = active_bins_from_segment(words, best_start)
        active_bins = [bin_idx for bins in bins_by_col for bin_idx in bins]
        active_bin_counts.update(active_bins)
        row_signature_counts["|".join(",".join(str(v) for v in bins) for bins in bins_by_col)] += 1

    offset_variability: list[dict[str, Any]] = []
    for offset in range(stride):
        values = Counter(row[offset] for row in all_measurement_rows if offset < len(row))
        if len(values) > 1:
            offset_variability.append(
                {
                    "offset": offset,
                    "unique_values": len(values),
                    "top_values": values.most_common(6),
                }
            )

    return {
        "label": label,
        "artifact_dir": str(artifact_dir),
        "frame_count": len(frames),
        "measurement_row_count": len(all_measurement_rows),
        "compress_param": compress_param_summary(first_meta),
        "meta_counts": [
            {"count": count, "meta": dict(items)} for items, count in meta_counter.most_common()
        ],
        "measurement_row_hash_counts": common_rows.most_common(12),
        "mode_rows": {str(key): value.hex() for key, value in sorted(mode_by_row.items())},
        "mask": {
            "best_start_word_counts": mask_start_counts.most_common(),
            "aggregate_active_bin_counts": dict(sorted(active_bin_counts.items())),
            "aggregate_active_bin_counts_top": active_bin_counts.most_common(32),
            "row_signature_counts": row_signature_counts.most_common(8),
        },
        "offset_variability_top": sorted(
            offset_variability, key=lambda item: (-int(item["unique_values"]), int(item["offset"]))
        )[:64],
        "frames": frames,
    }


def top_pair_diffs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rows = {int(key): bytes.fromhex(value) for key, value in left["mode_rows"].items()}
    right_rows = {int(key): bytes.fromhex(value) for key, value in right["mode_rows"].items()}
    common_indexes = sorted(set(left_rows) & set(right_rows))
    if not common_indexes:
        return {"error": "no common measurement row indexes"}

    stride = min(min(len(left_rows[idx]), len(right_rows[idx])) for idx in common_indexes)
    byte_offsets: list[dict[str, Any]] = []
    for offset in range(stride):
        changed_rows = []
        total_abs_delta = 0
        values: Counter[tuple[int, int]] = Counter()
        for row_idx in common_indexes:
            a = left_rows[row_idx][offset]
            b = right_rows[row_idx][offset]
            if a != b:
                changed_rows.append(row_idx)
                total_abs_delta += abs(a - b)
                values[(a, b)] += 1
        if changed_rows:
            byte_offsets.append(
                {
                    "offset": offset,
                    "changed_row_count": len(changed_rows),
                    "first_changed_rows": changed_rows[:12],
                    "total_abs_delta": total_abs_delta,
                    "top_value_pairs": [
                        {"left": pair[0], "right": pair[1], "count": count}
                        for pair, count in values.most_common(6)
                    ],
                }
            )

    word_offsets: list[dict[str, Any]] = []
    for word_idx in range(stride // 4):
        offset = word_idx * 4
        changed_rows = []
        values: Counter[tuple[int, int]] = Counter()
        for row_idx in common_indexes:
            a = int.from_bytes(left_rows[row_idx][offset : offset + 4], "little")
            b = int.from_bytes(right_rows[row_idx][offset : offset + 4], "little")
            if a != b:
                changed_rows.append(row_idx)
                values[(a, b)] += 1
        if changed_rows:
            word_offsets.append(
                {
                    "word_index": word_idx,
                    "byte_offset": offset,
                    "changed_row_count": len(changed_rows),
                    "first_changed_rows": changed_rows[:12],
                    "top_word_pairs_hex": [
                        {"left": f"0x{pair[0]:08x}", "right": f"0x{pair[1]:08x}", "count": count}
                        for pair, count in values.most_common(6)
                    ],
                }
            )

    left_bins = Counter(dict(left["mask"]["aggregate_active_bin_counts"]))
    right_bins = Counter(dict(right["mask"]["aggregate_active_bin_counts"]))
    bin_delta = []
    for bin_idx in sorted(set(left_bins) | set(right_bins)):
        delta = right_bins[bin_idx] - left_bins[bin_idx]
        if delta:
            bin_delta.append({"bin": bin_idx, "left": left_bins[bin_idx], "right": right_bins[bin_idx], "delta": delta})

    return {
        "left": left["label"],
        "right": right["label"],
        "mode_row_changed_byte_offsets": len(byte_offsets),
        "mode_row_changed_word_offsets": len(word_offsets),
        "top_byte_offsets": sorted(
            byte_offsets,
            key=lambda item: (-int(item["changed_row_count"]), -int(item["total_abs_delta"]), int(item["offset"])),
        )[:80],
        "top_word_offsets": sorted(
            word_offsets,
            key=lambda item: (-int(item["changed_row_count"]), int(item["word_index"])),
        )[:80],
        "mask_active_bin_delta_top": sorted(
            bin_delta,
            key=lambda item: (-abs(int(item["delta"])), int(item["bin"])),
        )[:64],
        "interpretation": {
            "zero_changed_byte_offsets": len(byte_offsets) == 0,
            "changed_offsets_are_scene_candidates": (
                "Offsets that change by physical condition but stay stable within a condition "
                "are candidates for real compressed payload or per-row control data."
            ),
        },
    }


def strip_mode_rows(condition: dict[str, Any]) -> dict[str, Any]:
    out = dict(condition)
    out.pop("mode_rows", None)
    return out


def strip_verbose(condition: dict[str, Any], include_mode_rows: bool, include_frames: bool) -> dict[str, Any]:
    out = condition if include_mode_rows else strip_mode_rows(condition)
    if include_frames:
        return out
    out = dict(out)
    out.pop("frames", None)
    return out


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_summary(report: dict[str, Any]) -> str:
    lines = ["DTOF_LINE_CONDITION_COMPARE_SUMMARY"]
    for condition in report["conditions"]:
        meta_counts = condition.get("meta_counts", [])
        meta = meta_counts[0]["meta"] if meta_counts else {}
        compress_param = condition.get("compress_param", {})
        mask = condition.get("mask", {})
        lines.append(
            "CONDITION "
            f"label={condition.get('label')} "
            f"frames={condition.get('frame_count')} "
            f"measurement_rows={condition.get('measurement_row_count')} "
            f"width={meta.get('width')} "
            f"height={meta.get('height')} "
            f"stride0={meta.get('stride0')} "
            f"pixfmt={meta.get('pixel_format')} "
            f"compress={meta.get('compress_mode')} "
            f"compress_param_sha16={str(compress_param.get('sha256', ''))[:16]}"
        )
        lines.append(
            "  "
            f"mask_best_start={compact_json(mask.get('best_start_word_counts', [])[:6])} "
            f"active_bins_top={compact_json(mask.get('aggregate_active_bin_counts_top', [])[:10])} "
            f"row_hash_top={compact_json(condition.get('measurement_row_hash_counts', [])[:4])}"
        )

    for pair in report["pairs"]:
        if "error" in pair:
            lines.append(
                "PAIR "
                f"left={pair.get('left')} "
                f"right={pair.get('right')} "
                f"error={pair.get('error')}"
            )
            continue

        zero_changed = pair.get("interpretation", {}).get("zero_changed_byte_offsets")
        lines.append(
            "PAIR "
            f"left={pair.get('left')} "
            f"right={pair.get('right')} "
            f"changed_byte_offsets={pair.get('mode_row_changed_byte_offsets')} "
            f"changed_word_offsets={pair.get('mode_row_changed_word_offsets')} "
            f"mask_delta_count={len(pair.get('mask_active_bin_delta_top', []))} "
            f"zero_changed_byte_offsets={zero_changed}"
        )

        top_bytes = [
            {
                "offset": item["offset"],
                "rows": item["changed_row_count"],
                "abs_delta": item["total_abs_delta"],
            }
            for item in pair.get("top_byte_offsets", [])[:8]
        ]
        top_words = [
            {
                "word": item["word_index"],
                "byte": item["byte_offset"],
                "rows": item["changed_row_count"],
            }
            for item in pair.get("top_word_offsets", [])[:8]
        ]
        top_bins = [
            {"bin": item["bin"], "delta": item["delta"]}
            for item in pair.get("mask_active_bin_delta_top", [])[:10]
        ]
        lines.append(
            "  "
            f"top_byte_offsets={compact_json(top_bytes)} "
            f"top_word_offsets={compact_json(top_words)} "
            f"top_mask_bin_deltas={compact_json(top_bins)}"
        )

    lines.append(f"NEXT={report.get('recommended_next_read')}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "conditions",
        nargs="+",
        help="Condition artifact directories, optionally as label=path.",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--include-mode-rows",
        action="store_true",
        help="Include full per-row mode byte strings in JSON output.",
    )
    parser.add_argument(
        "--include-frames",
        action="store_true",
        help="Include every input frame hash and metadata record in JSON output.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact human-readable summary instead of the full JSON report.",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        help="Optional path for the compact summary. The full JSON is still controlled by --out.",
    )
    args = parser.parse_args()

    conditions = [read_condition(label, path) for label, path in map(parse_condition, args.conditions)]
    pairs = []
    for left_idx in range(len(conditions)):
        for right_idx in range(left_idx + 1, len(conditions)):
            pairs.append(top_pair_diffs(conditions[left_idx], conditions[right_idx]))

    report_conditions = [
        strip_verbose(item, include_mode_rows=args.include_mode_rows, include_frames=args.include_frames)
        for item in conditions
    ]
    report = {
        "conditions": report_conditions,
        "pairs": pairs,
        "recommended_next_read": (
            "If clear/near/covered dumps show no condition-dependent offsets, suspect physical "
            "light path, trigger/config, or MIPI mapping. If only a compact region changes, use "
            "that region to derive the RAW12+LINE decoder before feeding DtofProcess."
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    summary = build_summary(report)
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(summary + "\n", encoding="utf-8")
    print(summary if args.summary else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
