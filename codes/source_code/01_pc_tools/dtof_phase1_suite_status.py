#!/usr/bin/env python3
"""Find latest Phase1 condition reports and optionally compare them.

This is a local bookkeeping helper. It does not contact the board or VM.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


DEFAULT_LABELS = [
    "clear_official",
    "near30cm_official",
    "covered_official",
]


def get_path(item: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def latest_for_label(label: str) -> Path | None:
    prefix = f"dtof_phase1_{label}_"
    candidates: list[Path] = []
    for path in LOG_DIR.glob(f"{prefix}*.json"):
        if not path.is_file():
            continue
        rest = path.stem[len(prefix) :]
        if rest.startswith("report") or re.match(r"^\d{8}_\d{6}_report", rest):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def brief(path: Path) -> dict[str, Any]:
    report = load_json(path) or {}
    return {
        "label": path.name,
        "condition": report.get("condition"),
        "path": str(path),
        "gate": get_path(report, "classification.gate"),
        "first_two_raw_nonzero_median": get_path(report, "board.first_two.raw_nonzero.median"),
        "first_two_raw_max_median": get_path(report, "board.first_two.raw_max.median"),
        "first_two_out_max_median": get_path(report, "board.first_two.out_max.median"),
        "steady_raw_nonzero_median": get_path(report, "board.after_first_two.raw_nonzero.median"),
        "steady_out_max_median": get_path(report, "board.after_first_two.out_max.median"),
        "raw_zero_first_frame": get_path(report, "board.raw_zero_first_frame"),
        "packets": get_path(report, "vm.kv.PACKETS"),
        "all_2mm_packets": get_path(report, "vm.kv.ALL_2MM_PACKETS"),
        "validish_packets": get_path(report, "vm.kv.VALIDISH_DEPTH_PACKETS"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", nargs="+", default=DEFAULT_LABELS)
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--compare-out",
        default="",
        help="Write dtof_phase1_compare_reports.py output for found labels.",
    )
    args = parser.parse_args()

    found: list[Path] = []
    missing: list[str] = []
    rows: list[dict[str, Any]] = []

    for label in args.labels:
        path = latest_for_label(label)
        if path is None:
            missing.append(label)
            continue
        found.append(path)
        rows.append(brief(path))

    output: dict[str, Any] = {
        "labels": args.labels,
        "found_count": len(found),
        "missing": missing,
        "reports": rows,
    }

    if args.compare_out and len(found) >= 2:
        compare_cmd = [
            str(PYTHON),
            str(ROOT / "tools" / "dtof_phase1_compare_reports.py"),
            *[str(path) for path in found],
            "--out",
            args.compare_out,
        ]
        proc = subprocess.run(
            compare_cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output["compare_rc"] = proc.returncode
        output["compare_stdout"] = proc.stdout

    text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"DTOF_PHASE1_SUITE_STATUS={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
