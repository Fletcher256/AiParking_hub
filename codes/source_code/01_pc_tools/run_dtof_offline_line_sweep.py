#!/usr/bin/env python3
"""Run the board-side offline RAW12+LINE sweep on a saved dToF dump file."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"
SAFE_BINARY_RE = re.compile(r"^sample_dtof[A-Za-z0-9_.-]*$")
SAFE_DUMP_RE = re.compile(r"^dtof_line_dump_f\d{3}\.bin$")
SWEEP_RE = re.compile(
    r"^\[OFFLINE_SWEEP\]\s+variant=(?P<variant>\S+)\s+amplitude=(?P<amplitude>\d+)\s+"
    r"active_bins=(?P<active_bins>\d+)\s+ret=(?P<ret>-?\d+)\s+"
    r"min=(?P<min>\d+)\s+p25=(?P<p25>\d+)\s+median=(?P<median>\d+)\s+"
    r"p75=(?P<p75>\d+)\s+max=(?P<max>\d+)\s+mean=(?P<mean>[0-9.]+)\s+"
    r"lt1000=(?P<lt1000>\d+)\s+eq2=(?P<eq2>\d+)\s+zero=(?P<zero>\d+)\s+"
    r"unique=(?P<unique>\d+)\s+center=(?P<center>\d+)"
)


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be a sample_dtof* file name without path or shell characters"
    if not SAFE_DUMP_RE.fullmatch(args.dump):
        return "--dump must be a dtof_line_dump_fNNN.bin file name"
    return None


def run_and_log(command: list[str], log_path: Path, env: dict[str, str]) -> int:
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        return proc.wait()


def parse_sweep(log_path: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    input_lines: list[str] = []
    errors: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("[OFFLINE_SWEEP_INPUT]"):
            input_lines.append(line)
        if line.startswith("[OFFLINE_SWEEP_ERROR]"):
            errors.append(line)
        match = SWEEP_RE.match(line.strip())
        if not match:
            continue
        row: dict[str, object] = {"variant": match.group("variant")}
        for key in (
            "amplitude",
            "active_bins",
            "ret",
            "min",
            "p25",
            "median",
            "p75",
            "max",
            "lt1000",
            "eq2",
            "zero",
            "unique",
            "center",
        ):
            row[key] = int(match.group(key))
        row["mean"] = float(match.group("mean"))
        row["near_valid_lt1000"] = max(0, int(row["lt1000"]) - int(row["eq2"]) - int(row["zero"]))
        row["near_majority"] = row["near_valid_lt1000"] > 600
        rows.append(row)

    best = sorted(
        rows,
        key=lambda row: (
            -int(row["near_valid_lt1000"]),
            int(row["median"]),
            int(row["eq2"]),
            int(row["amplitude"]),
            str(row["variant"]),
        ),
    )[:10]
    return {
        "input_lines": input_lines,
        "errors": errors,
        "variant_count": len(rows),
        "near_majority_count": sum(1 for row in rows if row["near_majority"]),
        "best_by_lt1000": best,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="offline_line_sweep")
    parser.add_argument("--binary", default="sample_dtof_official_offline_line_sweep_dbg")
    parser.add_argument("--dump", default="dtof_line_dump_f001.bin")
    args = parser.parse_args()

    validation_error = validate_args(args)
    if validation_error:
        print(f"Invalid argument: {validation_error}", file=sys.stderr)
        return 2
    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = safe_name(args.condition)
    prefix = f"dtof_offline_line_sweep_{label}_{stamp}"
    board_log = LOG_DIR / f"{prefix}_board.log"
    cmd_log = LOG_DIR / f"{prefix}_commands.txt"
    report_json = LOG_DIR / f"{prefix}_report.json"

    board_inner = (
        "cd /opt/sample/official_dtof; "
        f"./{args.binary} {args.dump}; "
        "echo OFFLINE_SWEEP_RC=$?"
    )
    board_cmd = [str(PYTHON), "tools/board_run.py", board_inner]
    cmd_log.write_text(
        "Board command:\n"
        + " ".join(board_cmd)
        + "\n\nPurpose: run offline DtofProcess line-compression hypothesis sweep on a saved dump file.\n"
        + "Risk: CPU-only board process that reads a saved dtof_line_dump file; no sensor, VI, MIPI, UDP, or actuator path.\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"COMMAND_LOG={cmd_log}")
    print(f"BOARD_LOG={board_log}")
    board_rc = run_and_log(board_cmd, board_log, env)
    report = parse_sweep(board_log)
    report["board_log"] = str(board_log)
    report["command_log"] = str(cmd_log)
    report["board_rc"] = board_rc
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"REPORT_JSON={report_json}")
    print(f"BOARD_RC={board_rc}")
    print(f"VARIANT_COUNT={report['variant_count']}")
    print(f"NEAR_MAJORITY_COUNT={report['near_majority_count']}")
    for idx, row in enumerate(report["best_by_lt1000"][:5], 1):
        print(
            "BEST_%d variant=%s amplitude=%s median=%s near_valid_lt1000=%s lt1000=%s eq2=%s zero=%s center=%s"
            % (
                idx,
                row["variant"],
                row["amplitude"],
                row["median"],
                row["near_valid_lt1000"],
                row["lt1000"],
                row["eq2"],
                row["zero"],
                row["center"],
            )
        )
    return 0 if board_rc == 0 and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
