#!/usr/bin/env python3
"""Find and compare latest dToF LINE dump artifacts for two conditions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
ARTIFACTS = ROOT / "artifacts"
LOG_DIR = ROOT / "logs"


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def latest_artifact_for_label(label: str) -> Path:
    prefix = f"dtof_line_dump_{label}_"
    matches = [path for path in ARTIFACTS.iterdir() if path.is_dir() and path.name.startswith(prefix)]
    if not matches:
        raise SystemExit(f"no artifact directory found for label {label!r} with prefix {prefix!r}")
    return max(matches, key=lambda path: path.stat().st_mtime)


def parse_condition(value: str) -> tuple[str, Path]:
    if "=" in value:
        label, raw_path = value.split("=", 1)
        path = Path(raw_path)
        return label.strip(), path
    path = Path(value)
    if path.exists():
        return path.name, path
    return value, latest_artifact_for_label(value)


def run_compare(left_label: str, left_path: Path, right_label: str, right_path: Path, out: Path, summary_out: Path) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        str(PYTHON),
        "tools/compare_dtof_line_conditions.py",
        f"{left_label}={left_path}",
        f"{right_label}={right_path}",
        "--out",
        str(out),
        "--summary",
        "--summary-out",
        str(summary_out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(proc.stdout, end="")
    return proc.returncode


def decide(report: dict[str, Any]) -> dict[str, Any]:
    if not report.get("pairs"):
        return {
            "decision": "NO_PAIR_RESULT",
            "raw_line_scene_change": "unknown",
            "recommended_next": "No pair result was produced; inspect compare JSON.",
        }

    pair = report["pairs"][0]
    if "error" in pair:
        return {
            "decision": "PAIR_COMPARE_ERROR",
            "raw_line_scene_change": "unknown",
            "error": pair["error"],
            "recommended_next": "Inspect artifact directories and frame metadata.",
        }

    changed_bytes = int(pair.get("mode_row_changed_byte_offsets", 0))
    changed_words = int(pair.get("mode_row_changed_word_offsets", 0))
    mask_delta_count = len(pair.get("mask_active_bin_delta_top", []))

    if changed_bytes == 0 and changed_words == 0 and mask_delta_count == 0:
        return {
            "decision": "NO_LINE_SCENE_CHANGE_OBSERVED",
            "raw_line_scene_change": "no",
            "changed_byte_offsets": changed_bytes,
            "changed_word_offsets": changed_words,
            "mask_delta_count": mask_delta_count,
            "recommended_next": (
                "If these were controlled clear/near captures, prioritize physical light path, "
                "J3/J4 mapping, trigger/config, power, or MIPI routing before ROS thresholds."
            ),
        }

    if changed_bytes > 0:
        return {
            "decision": "LINE_SCENE_CHANGE_CANDIDATE",
            "raw_line_scene_change": "yes",
            "changed_byte_offsets": changed_bytes,
            "changed_word_offsets": changed_words,
            "mask_delta_count": mask_delta_count,
            "top_byte_offsets": pair.get("top_byte_offsets", [])[:12],
            "top_word_offsets": pair.get("top_word_offsets", [])[:12],
            "recommended_next": (
                "If DtofProcess/UDP still reports 2mm or about 5m while LINE changes, inspect "
                "the vendor decode/data contract before any ROS abstraction."
            ),
        }

    return {
        "decision": "MASK_ONLY_SCENE_CHANGE_CANDIDATE",
        "raw_line_scene_change": "partial",
        "changed_byte_offsets": changed_bytes,
        "changed_word_offsets": changed_words,
        "mask_delta_count": mask_delta_count,
        "top_mask_bin_deltas": pair.get("mask_active_bin_delta_top", [])[:12],
        "recommended_next": (
            "The compact mask-like region changed without mode byte offsets; inspect mask "
            "semantics and compare more physical conditions."
        ),
    }


def build_decision_summary(decision_report: dict[str, Any]) -> str:
    lines = ["DTOF_LINE_LATEST_COMPARE_DECISION"]
    lines.append(f"left={decision_report['left']['label']} path={decision_report['left']['path']}")
    lines.append(f"right={decision_report['right']['label']} path={decision_report['right']['path']}")
    decision = decision_report["decision"]
    for key in (
        "decision",
        "raw_line_scene_change",
        "changed_byte_offsets",
        "changed_word_offsets",
        "mask_delta_count",
        "recommended_next",
    ):
        if key in decision:
            lines.append(f"{key}={decision[key]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "left",
        nargs="?",
        default="clear_j4_live",
        help="Left condition label/path, optionally label=path. Default: clear_j4_live.",
    )
    parser.add_argument(
        "right",
        nargs="?",
        default="near30cm_j4_live",
        help="Right condition label/path, optionally label=path. Default: near30cm_j4_live.",
    )
    parser.add_argument("--out", type=Path, help="Full compare JSON path.")
    parser.add_argument("--summary-out", type=Path, help="Compact compare summary path.")
    parser.add_argument("--decision-out", type=Path, help="Decision JSON path.")
    parser.add_argument("--decision-summary-out", type=Path, help="Decision summary path.")
    args = parser.parse_args()

    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}", file=sys.stderr)
        return 2

    left_label, left_path = parse_condition(args.left)
    right_label, right_path = parse_condition(args.right)
    if not left_path.is_dir():
        print(f"left artifact is not a directory: {left_path}", file=sys.stderr)
        return 2
    if not right_path.is_dir():
        print(f"right artifact is not a directory: {right_path}", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pair_name = f"{safe_name(left_label)}_vs_{safe_name(right_label)}_{stamp}"
    out = args.out or LOG_DIR / f"dtof_line_compare_{pair_name}.json"
    summary_out = args.summary_out or LOG_DIR / f"dtof_line_compare_{pair_name}_summary.txt"
    decision_out = args.decision_out or LOG_DIR / f"dtof_line_compare_{pair_name}_decision.json"
    decision_summary_out = (
        args.decision_summary_out or LOG_DIR / f"dtof_line_compare_{pair_name}_decision_summary.txt"
    )

    for path in (out, summary_out, decision_out, decision_summary_out):
        path.parent.mkdir(parents=True, exist_ok=True)

    print(f"LEFT_LABEL={left_label}")
    print(f"LEFT_ARTIFACT={left_path}")
    print(f"RIGHT_LABEL={right_label}")
    print(f"RIGHT_ARTIFACT={right_path}")
    print(f"COMPARE_JSON={out}")
    print(f"COMPARE_SUMMARY={summary_out}")

    rc = run_compare(left_label, left_path, right_label, right_path, out, summary_out)
    if rc != 0:
        print(f"compare failed with rc={rc}", file=sys.stderr)
        return rc

    report = json.loads(out.read_text(encoding="utf-8"))
    decision_report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "left": {"label": left_label, "path": str(left_path)},
        "right": {"label": right_label, "path": str(right_path)},
        "compare_json": str(out),
        "compare_summary": str(summary_out),
        "scope": (
            "This decision only evaluates whether saved RAW12+LINE artifacts changed between "
            "conditions. It does not prove DtofProcess distance correctness."
        ),
        "decision": decide(report),
    }
    decision_summary = build_decision_summary(decision_report)
    decision_out.write_text(json.dumps(decision_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    decision_summary_out.write_text(decision_summary + "\n", encoding="utf-8")
    print(f"DECISION_JSON={decision_out}")
    print(f"DECISION_SUMMARY={decision_summary_out}")
    print(decision_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
