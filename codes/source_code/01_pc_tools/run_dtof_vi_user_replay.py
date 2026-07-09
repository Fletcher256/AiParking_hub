#!/usr/bin/env python3
"""Run the board-side VI user-source replay diagnostic on a saved dToF LINE dump."""

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
DTOF_RE = re.compile(
    r"^\[VI_REPLAY_DTOF\]\s+label=(?P<label>\S+)\s+ret=(?P<ret>-?\d+)\s+"
    r"min=(?P<min>\d+)\s+p25=(?P<p25>\d+)\s+median=(?P<median>\d+)\s+"
    r"p75=(?P<p75>\d+)\s+max=(?P<max>\d+)\s+mean=(?P<mean>[0-9.]+)\s+"
    r"lt1000=(?P<lt1000>\d+)\s+eq2=(?P<eq2>\d+)\s+zero=(?P<zero>\d+)\s+"
    r"unique=(?P<unique>\d+)\s+center=(?P<center>\d+)"
)
FRAME_RE = re.compile(
    r"^\[VI_REPLAY_FRAME\]\s+label=(?P<label>\S+)\s+w=(?P<w>\d+)\s+h=(?P<h>\d+)\s+"
    r"stride=(?P<stride>\d+)\s+pixfmt=(?P<pixfmt>-?\d+)\s+compress=(?P<compress>-?\d+)\s+"
    r"size=(?P<size>\d+)\s+byte_sum=(?P<byte_sum>\d+)\s+nonzero=(?P<nonzero>\d+)"
)
GET_RE = re.compile(r"^\[VI_REPLAY_GET\]\s+label=(?P<label>\S+)\s+ret=0x(?P<ret>[0-9a-fA-F]+)")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be a sample_dtof* file name without path or shell characters"
    if not SAFE_DUMP_RE.fullmatch(args.dump):
        return "--dump must be a dtof_line_dump_fNNN.bin file name"
    if args.pipe < 0 or args.pipe > 15:
        return "--pipe must be a small non-negative VI pipe id"
    if args.dev < 0 or args.dev > 15:
        return "--dev must be a small non-negative VI dev id"
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


def parse_log(log_path: Path) -> dict[str, object]:
    frames: list[dict[str, object]] = []
    dtof_rows: list[dict[str, object]] = []
    gets: list[dict[str, object]] = []
    errors: list[str] = []
    skips: list[str] = []

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("[VI_REPLAY_ERROR]"):
            errors.append(line)
        if line.startswith("[VI_REPLAY_DTOF]") and " skip=" in line:
            skips.append(line)

        match = GET_RE.match(line.strip())
        if match:
            gets.append({"label": match.group("label"), "ret_hex": match.group("ret")})

        match = FRAME_RE.match(line.strip())
        if match:
            row: dict[str, object] = {"label": match.group("label")}
            for key in ("w", "h", "stride", "pixfmt", "compress", "size", "byte_sum", "nonzero"):
                row[key] = int(match.group(key))
            frames.append(row)

        match = DTOF_RE.match(line.strip())
        if match:
            row = {"label": match.group("label")}
            for key in ("ret", "min", "p25", "median", "p75", "max", "lt1000", "eq2", "zero", "unique", "center"):
                row[key] = int(match.group(key))
            row["mean"] = float(match.group("mean"))
            row["near_valid_lt1000"] = max(0, int(row["lt1000"]) - int(row["eq2"]) - int(row["zero"]))
            row["near_majority"] = row["near_valid_lt1000"] > 600
            dtof_rows.append(row)

    return {
        "errors": errors,
        "skips": skips,
        "get_results": gets,
        "frames": frames,
        "dtof_rows": dtof_rows,
        "near_majority_count": sum(1 for row in dtof_rows if row["near_majority"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="vi_user_replay")
    parser.add_argument("--binary", default="sample_dtof_official_vi_user_replay_dbg")
    parser.add_argument("--dump", default="dtof_line_dump_f001.bin")
    parser.add_argument("--pipe", type=int, default=1)
    parser.add_argument("--dev", type=int, default=3)
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
    prefix = f"dtof_vi_user_replay_{label}_{stamp}"
    board_log = LOG_DIR / f"{prefix}_board.log"
    cmd_log = LOG_DIR / f"{prefix}_commands.txt"
    report_json = LOG_DIR / f"{prefix}_report.json"

    board_inner = (
        "cd /opt/sample/official_dtof; "
        f"./{args.binary} {args.dump} {args.pipe} {args.dev}; "
        "echo VI_USER_REPLAY_RC=$?"
    )
    board_cmd = [str(PYTHON), "tools/board_run.py", board_inner]
    cmd_log.write_text(
        "Board command:\n"
        + " ".join(board_cmd)
        + "\n\nPurpose: route one saved RAW12+LINE dToF frame through VI user-source replay and log pipe/FE/BAS outputs.\n"
        + "Risk: starts and stops board MPP SYS/VB and one VI pipe for perception-only media diagnostics; no UDP, MCU, CAN, motor, steering, brake, throttle, or chassis-control path.\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"COMMAND_LOG={cmd_log}")
    print(f"BOARD_LOG={board_log}")
    board_rc = run_and_log(board_cmd, board_log, env)
    report = parse_log(board_log)
    report["board_log"] = str(board_log)
    report["command_log"] = str(cmd_log)
    report["board_rc"] = board_rc
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"REPORT_JSON={report_json}")
    print(f"BOARD_RC={board_rc}")
    print(f"FRAME_COUNT={len(report['frames'])}")
    print(f"DTOF_ROW_COUNT={len(report['dtof_rows'])}")
    print(f"NEAR_MAJORITY_COUNT={report['near_majority_count']}")
    for row in report["frames"]:
        print(
            "FRAME label=%s w=%s h=%s stride=%s pixfmt=%s compress=%s nonzero=%s byte_sum=%s"
            % (
                row["label"],
                row["w"],
                row["h"],
                row["stride"],
                row["pixfmt"],
                row["compress"],
                row["nonzero"],
                row["byte_sum"],
            )
        )
    for row in report["dtof_rows"]:
        print(
            "DTOF label=%s median=%s near_valid_lt1000=%s lt1000=%s eq2=%s zero=%s center=%s"
            % (
                row["label"],
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
