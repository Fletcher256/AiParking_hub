#!/usr/bin/env python3
"""Print the next Phase1 physical condition and exact capture command.

This helper is local-only. It reads existing reports under logs/ and does not
contact the board or VM.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"


CONDITIONS = [
    {
        "label": "clear_official",
        "user_prompt": "Clear the dToF field of view, then confirm: clear scene ready.",
        "purpose": "Capture the J4/case2 official diagnostic raw/output/UDP baseline in a clear scene.",
        "risk": "Starts a perception-only dToF sample and VM UDP listener; no actuator path and no vehicle motion.",
    },
    {
        "label": "near30cm_official",
        "user_prompt": "Place a flat object about 30 cm in front of the dToF, then confirm: 30 cm target ready.",
        "purpose": "Check whether a near flat target changes early-frame raw data or depth output.",
        "risk": "Starts a perception-only dToF sample and VM UDP listener; no actuator path and no vehicle motion.",
    },
    {
        "label": "covered_official",
        "user_prompt": "Cover the dToF lens closely, then confirm: covered target ready.",
        "purpose": "Check whether full cover still reports a fixed far range, separating optical/fixed-echo issues from post-processing.",
        "risk": "Starts a perception-only dToF sample and VM UDP listener; no actuator path and no vehicle motion.",
    },
]


def latest_report(label: str) -> Path | None:
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


def get_path(item: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def summarize_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path), "error": "unreadable_json"}
    return {
        "path": str(path),
        "condition": report.get("condition"),
        "gate": get_path(report, "classification.gate"),
        "first_two_raw_nonzero_median": get_path(report, "board.first_two.raw_nonzero.median"),
        "steady_raw_nonzero_median": get_path(report, "board.after_first_two.raw_nonzero.median"),
        "raw_zero_first_frame": get_path(report, "board.raw_zero_first_frame"),
        "packets": get_path(report, "vm.kv.PACKETS"),
        "all_2mm_packets": get_path(report, "vm.kv.ALL_2MM_PACKETS"),
    }


def capture_command(label: str, seconds: int, max_packets: int) -> str:
    return (
        ".venv\\Scripts\\python tools\\run_dtof_phase1_condition.py "
        f"--condition {label} --binary sample_dtof_official_dbg "
        f"--seconds {seconds} --max-packets {max_packets}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=35)
    parser.add_argument("--max-packets", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reports: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []
    for condition in CONDITIONS:
        label = condition["label"]
        report_path = latest_report(label)
        if report_path is None:
            missing.append(condition)
        else:
            reports[label] = summarize_report(report_path)

    next_condition = missing[0] if missing else None
    output: dict[str, Any] = {
        "completed_labels": sorted(reports),
        "missing_labels": [item["label"] for item in missing],
        "reports": reports,
        "next": None,
    }
    if next_condition:
        label = next_condition["label"]
        output["next"] = {
            "label": label,
            "user_prompt": next_condition["user_prompt"],
            "command": capture_command(label, args.seconds, args.max_packets),
            "purpose": next_condition["purpose"],
            "risk": next_condition["risk"],
        }
    else:
        output["next"] = {
            "label": "compare",
            "command": (
                ".venv\\Scripts\\python tools\\dtof_phase1_suite_status.py "
                "--labels clear_official near30cm_official covered_official "
                "--out logs\\dtof_phase1_suite_status_latest.json "
                "--compare-out logs\\dtof_phase1_suite_compare_latest.json"
            ),
            "purpose": "Summarize the three physical-condition reports and decide A/B/pipe-zeroing route.",
            "risk": "Local read-only analysis; does not contact the board or VM.",
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print(f"COMPLETED_LABELS={','.join(output['completed_labels']) or '(none)'}")
    print(f"MISSING_LABELS={','.join(output['missing_labels']) or '(none)'}")
    print()
    next_step = output["next"]
    assert isinstance(next_step, dict)
    print(f"NEXT_LABEL={next_step['label']}")
    if "user_prompt" in next_step:
        print(f"USER_ACTION={next_step['user_prompt']}")
    print(f"COMMAND={next_step['command']}")
    print(f"PURPOSE={next_step['purpose']}")
    print(f"RISK={next_step['risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
