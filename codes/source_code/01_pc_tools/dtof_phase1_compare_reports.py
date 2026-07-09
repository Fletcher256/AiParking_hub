#!/usr/bin/env python3
"""Compare multiple Phase1 dToF JSON reports and suggest the next route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def get_path(item: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    report["_path"] = str(path)
    return report


def brief(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": report.get("condition") or Path(report["_path"]).stem,
        "path": report["_path"],
        "gate": get_path(report, "classification.gate"),
        "raw_nonzero_median": get_path(report, "board.raw_nonzero.median"),
        "raw_max_median": get_path(report, "board.raw_max.median"),
        "first_two_raw_nonzero_median": get_path(report, "board.first_two.raw_nonzero.median"),
        "first_two_raw_max_median": get_path(report, "board.first_two.raw_max.median"),
        "first_two_out_max_median": get_path(report, "board.first_two.out_max.median"),
        "before_raw_zero_raw_nonzero_median": get_path(report, "board.before_raw_zero.raw_nonzero.median"),
        "before_raw_zero_out_max_median": get_path(report, "board.before_raw_zero.out_max.median"),
        "raw_zero_first_frame": get_path(report, "board.raw_zero_first_frame"),
        "out_max_median": get_path(report, "board.out_max.median"),
        "out_mid_median": get_path(report, "board.out_mid.median"),
        "out_eq_2_median": get_path(report, "board.out_eq_2.median"),
        "mask_decode_count": get_path(report, "board.mask_decode.count"),
        "mask_active_bins_median": get_path(report, "board.mask_decode.active_bins.median"),
        "packets": get_path(report, "vm.kv.PACKETS"),
        "all_2mm_packets": get_path(report, "vm.kv.ALL_2MM_PACKETS"),
        "validish_packets": get_path(report, "vm.kv.VALIDISH_DEPTH_PACKETS"),
        "depth_max_median": get_path(report, "vm.depth_max.median"),
        "depth_mean_median": get_path(report, "vm.depth_mean.median"),
        "depth_unique_median": get_path(report, "vm.depth_unique.median"),
    }


def ratio(num: Any, den: Any) -> float | None:
    if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
        return float(num) / float(den)
    return None


def decide(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gates = {str(row.get("gate")) for row in rows}
    notes: list[str] = []
    route = "undetermined"

    if "line_compressed_stream_not_decoded" in gates:
        route = "decode_or_bypass_raw12_line_compression_before_dtofprocess"
        notes.append(
            "RAW12+LINE bytes are present, but current user-space unpacking does not decode them before DtofProcess."
        )

    mask_far = [row for row in rows if row.get("gate") == "line_mask_heuristic_far_not_near"]
    if mask_far:
        if route == "undetermined":
            route = "decode_or_bypass_raw12_line_compression_before_dtofprocess"
        for row in mask_far:
            notes.append(
                f"{row['condition']}: 40x64 mask heuristic removed 2mm sentinel but produced far depth "
                f"(out_mid_median={row.get('out_mid_median')}, depth_mean_median={row.get('depth_mean_median')})."
            )

    if "pipe_attr_zero_after_switch" in gates:
        if route == "undetermined":
            route = "fix_or_bypass_official_pipe_attr_zeroing_first"
        notes.append("At least one official run loses raw data after the RAW10/NONE pipe-attribute switch.")

    raw_present_invalid = [row for row in rows if row.get("gate") == "raw_present_output_invalid"]
    if raw_present_invalid:
        notes.append("At least one run has raw data present while DtofProcess output remains invalid/all-2mm.")
        if route == "undetermined":
            route = "postprocess_or_mode_debug"

    labels = {str(row.get("condition")).lower(): row for row in rows}
    near_rows = [row for key, row in labels.items() if "near" in key or "30" in key or "50" in key]
    clear_rows = [row for key, row in labels.items() if "clear" in key or "empty" in key or "unobstruct" in key]
    covered_rows = [row for key, row in labels.items() if "cover" in key or "blocked" in key or "贴" in key]

    if clear_rows and near_rows:
        clear_raw = clear_rows[0].get("first_two_raw_nonzero_median")
        near_raw = near_rows[0].get("first_two_raw_nonzero_median")
        if clear_raw is None or near_raw is None:
            clear_raw = clear_rows[0].get("raw_nonzero_median")
            near_raw = near_rows[0].get("raw_nonzero_median")
        if isinstance(clear_raw, (int, float)) and isinstance(near_raw, (int, float)):
            if clear_raw == 0 and near_raw == 0:
                notes.append("Clear and near runs both have zero comparable raw median; physical near/far comparison is masked.")
            else:
                delta = abs(float(near_raw) - float(clear_raw))
                base = max(1.0, abs(float(clear_raw)))
                if delta / base > 0.1:
                    notes.append("Near object changes early-frame raw_nonzero by more than 10 percent versus clear.")
                    if route not in {
                        "fix_or_bypass_official_pipe_attr_zeroing_first",
                        "decode_or_bypass_raw12_line_compression_before_dtofprocess",
                    }:
                        route = "B_postprocess_drops_near_object"
                else:
                    notes.append("Near object does not materially change early-frame raw_nonzero versus clear.")
                    if covered_rows:
                        route = "A_physical_or_fixed_echo_if_covered_also_unchanged"

    for row in rows:
        r = ratio(row.get("all_2mm_packets"), row.get("packets"))
        if r is not None and r > 0.8:
            notes.append(f"{row['condition']}: UDP all-2mm ratio is {r:.2f}.")

    return {"route": route, "notes": notes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", help="JSON reports from dtof_phase1_log_report.py")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    reports = [load_report(Path(path)) for path in args.reports]
    rows = [brief(report) for report in reports]
    output = {"reports": rows, "decision": decide(rows)}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"DTOF_PHASE1_COMPARE_REPORT={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
