#!/usr/bin/env python3
"""Summarize Phase1 dToF board debug logs and VM UDP check logs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean, median
from typing import Any


DBG_RE = re.compile(
    r"\[(?:DTOF_DBG|DTOF_OFFICIAL_DBG)\]\s+frame=(?P<frame>\d+).*?"
    r"(?:pixfmt=(?P<pixfmt>\d+).*?compress=(?P<compress>\d+).*?)?"
    r"raw_min=(?P<raw_min>\d+)\s+raw_max=(?P<raw_max>\d+)\s+raw_nonzero=(?P<raw_nonzero>\d+)\s+"
    r"out_min=(?P<out_min>\d+)\s+out_max=(?P<out_max>\d+)\s+out_nonzero=(?P<out_nonzero>\d+)\s+"
    r"out_eq_2=(?P<out_eq_2>\d+)\s+out_mid=(?P<out_mid>\d+)\s+"
    r"switch=(?P<switch>-?\d+)\s+config=(?P<config>-?\d+).*?temp=(?P<temp>-?\d+(?:\.\d+)?)"
)

FRAME_RE = re.compile(
    r"\[DTOF_FRAME\]\s+frame=(?P<frame>\d+)\s+w=(?P<w>\d+)\s+h=(?P<h>\d+)\s+"
    r"stride0=(?P<stride0>\d+)\s+pixfmt=(?P<pixfmt>\d+)\s+compress=(?P<compress>\d+)"
)

MASK_RE = re.compile(
    r"\[DTOF_MASK\]\s+frame_hint=(?P<frame_hint>\d+)\s+decoded_rows=(?P<decoded_rows>\d+)\s+"
    r"active_bins=(?P<active_bins>\d+)\s+amplitude=(?P<amplitude>\d+)\s+"
    r"pixfmt=(?P<pixfmt>\d+)\s+compress=(?P<compress>\d+)\s+stride0=(?P<stride0>\d+)"
)

DEPTH_RE = re.compile(
    r"DEPTH_SUMMARY\s+seq=(?P<seq>\d+)\s+min=(?P<min>-?\d+)\s+max=(?P<max>-?\d+)\s+"
    r"mean=(?P<mean>-?\d+(?:\.\d+)?)\s+unique=(?P<unique>\d+)"
    r"(?:\s+valid=(?P<valid>\d+)\s+valid_median=(?P<valid_median>-?\d+(?:\.\d+)?|nan)\s+"
    r"(?:valid_p25=(?P<valid_p25>-?\d+(?:\.\d+)?|nan)\s+valid_p75=(?P<valid_p75>-?\d+(?:\.\d+)?|nan)\s+)?"
    r"valid_lt1000=(?P<valid_lt1000>\d+)"
    r"(?:\s+valid_2000_5000=(?P<valid_2000_5000>\d+))?\s+"
    r"(?:center_roi_valid=(?P<center_roi_valid>\d+)\s+center_roi_2000_5000=(?P<center_roi_2000_5000>\d+)\s+)?"
    r"center=(?P<center>-?\d+))?"
)

KV_RE = re.compile(r"^(?P<key>[A-Za-z0-9_]+)=(?P<value>.*)$")

RAW_BITS_BY_PIXFMT = {
    20: 10,  # OT_PIXEL_FORMAT_RGB_BAYER_10BPP in observed SS928 logs
    21: 12,  # OT_PIXEL_FORMAT_RGB_BAYER_12BPP in observed SS928 logs
    22: 14,
    23: 16,  # OT_PIXEL_FORMAT_RGB_BAYER_16BPP in observed SS928 logs
}


def read_text_clean(path: Path) -> str:
    text = path.read_bytes().decode("utf-8", errors="replace")
    if text.count("\x00") > max(8, len(text) // 20):
        text = text.replace("\x00", "")
    return text


def numbers(items: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for item in items:
        value = item.get(key)
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "median": median(values),
        "mean": mean(values),
        "max": max(values),
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "frame_count": len(rows),
        "raw_nonzero": stats(numbers(rows, "raw_nonzero")),
        "raw_max": stats(numbers(rows, "raw_max")),
        "out_max": stats(numbers(rows, "out_max")),
        "out_mid": stats(numbers(rows, "out_mid")),
        "out_eq_2": stats(numbers(rows, "out_eq_2")),
    }


def line_stride_mismatches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int, int, int, int], dict[str, Any]] = {}
    for row in rows:
        pixfmt = row.get("pixfmt")
        compress = row.get("compress")
        width = row.get("frame_w")
        stride0 = row.get("frame_stride0")
        frame = row.get("frame")
        if not all(isinstance(value, int) for value in (pixfmt, compress, width, stride0, frame)):
            continue
        bit_width = RAW_BITS_BY_PIXFMT.get(pixfmt)
        if compress != 4 or bit_width is None:
            continue
        ordinary_bytes = (width * bit_width + 7) // 8
        if ordinary_bytes <= stride0:
            continue
        key = (pixfmt, compress, width, stride0, bit_width, ordinary_bytes)
        item = grouped.setdefault(
            key,
            {
                "pixfmt": pixfmt,
                "compress": compress,
                "width": width,
                "stride0": stride0,
                "bit_width": bit_width,
                "ordinary_bytes_needed": ordinary_bytes,
                "first_frame": frame,
                "last_frame": frame,
                "frame_count": 0,
            },
        )
        item["last_frame"] = frame
        item["frame_count"] += 1
    return sorted(grouped.values(), key=lambda item: (item["first_frame"], item["pixfmt"]))


def parse_board(path: Path) -> dict[str, Any]:
    text = read_text_clean(path)
    phase_rc_match = re.search(r"DTOF_PHASE1_RC=(?P<rc>-?\d+)", text)
    startup_errors = [
        needle
        for needle in (
            "program exit abnormally",
            "OT_MPI_ISP_MemInit failed",
            "already inited",
            "start isp failed",
            "start vi failed",
            "Segmentation fault",
        )
        if needle in text
    ]
    frame_info: dict[int, dict[str, int]] = {}
    for match in FRAME_RE.finditer(text):
        frame = int(match.group("frame"))
        frame_info[frame] = {
            "pixfmt": int(match.group("pixfmt")),
            "compress": int(match.group("compress")),
            "w": int(match.group("w")),
            "h": int(match.group("h")),
            "stride0": int(match.group("stride0")),
        }

    mask_rows: list[dict[str, Any]] = []
    for match in MASK_RE.finditer(text):
        mask_rows.append({key: int(value) for key, value in match.groupdict().items()})

    rows: list[dict[str, Any]] = []
    for match in DBG_RE.finditer(text):
        row: dict[str, Any] = {}
        for key, value in match.groupdict().items():
            if value is None:
                continue
            row[key] = float(value) if key == "temp" else int(value)
        info = frame_info.get(int(row["frame"]))
        if info:
            row.update({f"frame_{key}": value for key, value in info.items()})
            row.setdefault("pixfmt", info["pixfmt"])
            row.setdefault("compress", info["compress"])
        rows.append(row)

    raw_nonzero = numbers(rows, "raw_nonzero")
    raw_max = numbers(rows, "raw_max")
    out_max = numbers(rows, "out_max")
    out_mid = numbers(rows, "out_mid")
    out_eq_2 = numbers(rows, "out_eq_2")
    pixfmts = sorted({int(item["pixfmt"]) for item in rows if "pixfmt" in item})
    compress_modes = sorted({int(item["compress"]) for item in rows if "compress" in item})
    raw_zero_frames = [int(item["frame"]) for item in rows if item.get("raw_nonzero") == 0]
    all_2mm_frames = [int(item["frame"]) for item in rows if item.get("out_eq_2") == 1200]
    first_two_rows = [item for item in rows if int(item["frame"]) <= 2]
    after_first_two_rows = [item for item in rows if int(item["frame"]) > 2]
    if raw_zero_frames:
        first_zero = raw_zero_frames[0]
        before_raw_zero_rows = [item for item in rows if int(item["frame"]) < first_zero]
        from_raw_zero_rows = [item for item in rows if int(item["frame"]) >= first_zero]
    else:
        before_raw_zero_rows = rows[:]
        from_raw_zero_rows = []

    return {
        "path": str(path),
        "phase_rc": int(phase_rc_match.group("rc")) if phase_rc_match else None,
        "startup_errors": startup_errors,
        "debug_frame_count": len(rows),
        "pixfmts": pixfmts,
        "compress_modes": compress_modes,
        "raw_nonzero": stats(raw_nonzero),
        "raw_max": stats(raw_max),
        "out_max": stats(out_max),
        "out_mid": stats(out_mid),
        "out_eq_2": stats(out_eq_2),
        "raw_zero_frame_count": len(raw_zero_frames),
        "raw_zero_first_frame": raw_zero_frames[0] if raw_zero_frames else None,
        "all_2mm_frame_count": len(all_2mm_frames),
        "all_2mm_first_frame": all_2mm_frames[0] if all_2mm_frames else None,
        "first_two": summarize_rows(first_two_rows),
        "after_first_two": summarize_rows(after_first_two_rows),
        "before_raw_zero": summarize_rows(before_raw_zero_rows),
        "from_raw_zero": summarize_rows(from_raw_zero_rows),
        "mask_decode": {
            "count": len(mask_rows),
            "decoded_rows": stats(numbers(mask_rows, "decoded_rows")),
            "active_bins": stats(numbers(mask_rows, "active_bins")),
            "amplitude": stats(numbers(mask_rows, "amplitude")),
            "first_rows": mask_rows[:5],
            "last_rows": mask_rows[-5:],
        },
        "line_stride_mismatches": line_stride_mismatches(rows),
        "first_frames": rows[:5],
        "last_frames": rows[-5:],
    }


def parse_vm(path: Path) -> dict[str, Any]:
    text = read_text_clean(path)
    kv: dict[str, Any] = {}
    depth_rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        kv_match = KV_RE.match(line.strip())
        if kv_match:
            key = kv_match.group("key")
            value = kv_match.group("value")
            if value.lstrip("-").isdigit():
                kv[key] = int(value)
            else:
                try:
                    kv[key] = float(value)
                except ValueError:
                    kv[key] = value
        depth_match = DEPTH_RE.search(line)
        if depth_match:
            def parse_optional_float(name: str) -> float | None:
                text_value = depth_match.group(name)
                if text_value is None or text_value == "nan":
                    return None
                return float(text_value)

            depth_rows.append(
                {
                    "seq": int(depth_match.group("seq")),
                    "min": int(depth_match.group("min")),
                    "max": int(depth_match.group("max")),
                    "mean": float(depth_match.group("mean")),
                    "unique": int(depth_match.group("unique")),
                    "valid": int(depth_match.group("valid")) if depth_match.group("valid") else None,
                    "valid_median": parse_optional_float("valid_median"),
                    "valid_p25": parse_optional_float("valid_p25"),
                    "valid_p75": parse_optional_float("valid_p75"),
                    "valid_lt1000": int(depth_match.group("valid_lt1000")) if depth_match.group("valid_lt1000") else None,
                    "valid_2000_5000": int(depth_match.group("valid_2000_5000")) if depth_match.group("valid_2000_5000") else None,
                    "center_roi_valid": int(depth_match.group("center_roi_valid")) if depth_match.group("center_roi_valid") else None,
                    "center_roi_2000_5000": int(depth_match.group("center_roi_2000_5000")) if depth_match.group("center_roi_2000_5000") else None,
                    "center": int(depth_match.group("center")) if depth_match.group("center") else None,
                }
            )

    max_values = numbers(depth_rows, "max")
    mean_values = numbers(depth_rows, "mean")
    unique_values = numbers(depth_rows, "unique")
    valid_values = numbers(depth_rows, "valid")
    valid_median_values = numbers(depth_rows, "valid_median")
    valid_p25_values = numbers(depth_rows, "valid_p25")
    valid_p75_values = numbers(depth_rows, "valid_p75")
    valid_lt1000_values = numbers(depth_rows, "valid_lt1000")
    valid_2000_5000_values = numbers(depth_rows, "valid_2000_5000")
    center_roi_valid_values = numbers(depth_rows, "center_roi_valid")
    center_roi_2000_5000_values = numbers(depth_rows, "center_roi_2000_5000")
    return {
        "path": str(path),
        "kv": kv,
        "depth_summary_count": len(depth_rows),
        "depth_max": stats(max_values),
        "depth_mean": stats(mean_values),
        "depth_unique": stats(unique_values),
        "depth_valid": stats(valid_values),
        "depth_valid_median": stats(valid_median_values),
        "depth_valid_p25": stats(valid_p25_values),
        "depth_valid_p75": stats(valid_p75_values),
        "depth_valid_lt1000": stats(valid_lt1000_values),
        "depth_valid_2000_5000": stats(valid_2000_5000_values),
        "center_roi_valid": stats(center_roi_valid_values),
        "center_roi_2000_5000": stats(center_roi_2000_5000_values),
        "first_summaries": depth_rows[:5],
        "last_summaries": depth_rows[-5:],
    }


def classify(board: dict[str, Any], vm: dict[str, Any]) -> dict[str, Any]:
    raw_zero_first = board.get("raw_zero_first_frame")
    all_2mm_packets = vm.get("kv", {}).get("ALL_2MM_PACKETS")
    packets = vm.get("kv", {}).get("PACKETS")
    good_size_packets = vm.get("kv", {}).get("GOOD_SIZE_4873")
    good_header_packets = vm.get("kv", {}).get("GOOD_HEADER_40x30")
    good_pixel_number_packets = vm.get("kv", {}).get("GOOD_PIXEL_NUMBER_1200")
    near_majority_packets = vm.get("kv", {}).get("NEAR_MAJORITY_LT_1000_PACKETS")
    near_median_packets = vm.get("kv", {}).get("NEAR_MEDIAN_LT_1000_PACKETS")
    near_any_packets = vm.get("kv", {}).get("NEAR_ANY_LT_1000_PACKETS")
    range_2to5_ratio = vm.get("kv", {}).get("RANGE_2000_5000_PIXEL_RATIO")
    range_2to5_majority_packets = vm.get("kv", {}).get("RANGE_2000_5000_MAJORITY_PACKETS")
    range_2to5_median_packets = vm.get("kv", {}).get("RANGE_2000_5000_MEDIAN_PACKETS")
    center_roi_2to5_ratio = vm.get("kv", {}).get("CENTER_ROI_2000_5000_RATIO")
    center_roi_2to5_majority_packets = vm.get("kv", {}).get("CENTER_ROI_2000_5000_MAJORITY_PACKETS")
    valid_non_sentinel_packets = vm.get("kv", {}).get("VALID_NON_SENTINEL_PACKETS")
    raw_nonzero_med = board.get("raw_nonzero", {}).get("median")
    out_eq_2_med = board.get("out_eq_2", {}).get("median")
    depth_unique_med = vm.get("depth_unique", {}).get("median")
    phase_rc = board.get("phase_rc")
    debug_frame_count = board.get("debug_frame_count", 0)
    startup_errors = board.get("startup_errors") or []
    compress_modes = set(board.get("compress_modes") or [])
    stride_mismatches = board.get("line_stride_mismatches") or []
    mask_count = board.get("mask_decode", {}).get("count", 0)
    depth_mean_med = vm.get("depth_mean", {}).get("median")

    notes: list[str] = []
    gate = "undetermined"

    if debug_frame_count == 0 and (startup_errors or (phase_rc is not None and phase_rc != 0) or packets == 0):
        gate = "startup_failed"
        if phase_rc is not None:
            notes.append(f"Board sample did not reach debug frames (DTOF_PHASE1_RC={phase_rc}).")
        if startup_errors:
            notes.append("Board startup errors: " + ", ".join(startup_errors) + ".")
        if packets == 0:
            notes.append("VM UDP capture received no packets.")
    elif raw_zero_first == 1:
        gate = "raw_zero_from_start"
        notes.append("Board raw is zero from the first debug frame.")
        if packets and all_2mm_packets is not None and all_2mm_packets == packets:
            notes.append(f"VM UDP packets are all 2mm ({all_2mm_packets}/{packets}).")
    elif raw_zero_first is not None and raw_zero_first <= 3:
        gate = "pipe_attr_zero_after_switch"
        notes.append("Board raw becomes zero immediately after the dump pipe attribute switch.")
    elif (
        packets
        and good_size_packets == packets
        and good_header_packets == packets
        and (good_pixel_number_packets is None or good_pixel_number_packets == packets)
        and valid_non_sentinel_packets
        and range_2to5_majority_packets is not None
        and range_2to5_median_packets is not None
        and range_2to5_majority_packets * 2 >= packets
        and range_2to5_median_packets * 2 >= packets
    ):
        gate = "target_range_2to5_candidate"
        notes.append(
            "VM UDP reports official 4873-byte/40x30 packets whose valid depths are mostly in the requested 2-5m range."
        )
    elif (
        packets
        and good_size_packets == packets
        and good_header_packets == packets
        and (good_pixel_number_packets is None or good_pixel_number_packets == packets)
        and valid_non_sentinel_packets
        and range_2to5_ratio is not None
        and range_2to5_majority_packets == 0
        and range_2to5_median_packets == 0
    ):
        gate = "dtof_live_but_2to5_not_majority"
        notes.append(
            "dToF UDP is alive and non-2mm, but valid depths are not dominated by the requested 2-5m target range."
        )
        notes.append(
            f"2-5m valid-pixel ratio is {range_2to5_ratio:.3f}"
            + (
                f"; center ROI ratio is {center_roi_2to5_ratio:.3f}"
                if center_roi_2to5_ratio is not None
                else ""
            )
            + "."
        )
    elif (
        packets
        and good_size_packets == packets
        and good_header_packets == packets
        and (good_pixel_number_packets is None or good_pixel_number_packets == packets)
        and valid_non_sentinel_packets
        and near_majority_packets is not None
        and near_median_packets is not None
        and near_majority_packets * 2 >= packets
        and near_median_packets * 2 >= packets
    ):
        gate = "near_depth_candidate"
        notes.append(
            "VM UDP reports official 4873-byte/40x30 packets whose non-2mm valid depths are mostly <1m."
        )
    elif (
        mask_count
        and raw_nonzero_med
        and raw_nonzero_med > 0
        and out_eq_2_med is not None
        and out_eq_2_med <= 1
        and (
            (depth_mean_med is not None and depth_mean_med > 1000)
            or (board.get("out_mid", {}).get("median") is not None and board["out_mid"]["median"] > 1000)
        )
    ):
        gate = "line_mask_heuristic_far_not_near"
        notes.append(
            "The RAW12+LINE mask heuristic produced non-sentinel output, but the result is stable far depth, not <1m near depth."
        )
    elif (
        4 in compress_modes
        and raw_nonzero_med
        and raw_nonzero_med > 0
        and out_eq_2_med is not None
        and out_eq_2_med >= 1199
        and depth_unique_med is not None
        and depth_unique_med <= 3
    ):
        gate = "line_compressed_stream_not_decoded"
        notes.append(
            "RAW12+LINE bytes are present, but ordinary raw unpack produces sparse sentinel/far output."
        )
    elif raw_nonzero_med and raw_nonzero_med > 0 and out_eq_2_med == 1200:
        gate = "raw_present_output_invalid"
        notes.append("Raw data is present, but DtofProcess output is all 2mm sentinel.")

    for mismatch in stride_mismatches[:3]:
        notes.append(
            "LINE-compressed pixfmt={pixfmt} width={width} needs {ordinary_bytes_needed} "
            "ordinary bytes/row, but stride0={stride0}; ordinary unpack would cross the line boundary.".format(
                **mismatch
            )
        )

    if packets and all_2mm_packets is not None:
        ratio = float(all_2mm_packets) / float(packets)
        if ratio > 0.8:
            notes.append(f"VM UDP is dominated by all-2mm packets ({all_2mm_packets}/{packets}).")
    if packets and near_any_packets is not None and near_majority_packets is not None:
        if near_any_packets and near_majority_packets * 2 < packets:
            notes.append(
                f"VM UDP has some <1m non-sentinel pixels ({near_any_packets}/{packets} packets), "
                "but not a majority-depth near result."
            )
    if packets and center_roi_2to5_majority_packets is not None and range_2to5_majority_packets is not None:
        if range_2to5_majority_packets * 2 < packets and center_roi_2to5_majority_packets * 2 < packets:
            notes.append(
                "Neither full frame nor center ROI has a per-packet majority of 2-5m valid depths."
            )

    return {"gate": gate, "notes": notes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-log", required=True)
    parser.add_argument("--vm-log", required=True)
    parser.add_argument("--condition", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    board = parse_board(Path(args.board_log))
    vm = parse_vm(Path(args.vm_log))
    report = {
        "condition": args.condition,
        "board": board,
        "vm": vm,
        "classification": classify(board, vm),
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"DTOF_PHASE1_LOG_REPORT={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
