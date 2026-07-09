#!/usr/bin/env python3
"""Run the EEPROM-only dToF board diagnostic and extract the 521-byte GS1860 calibration block."""

from __future__ import annotations

import argparse
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
SAFE_CASE_RE = re.compile(r"^\d+$")
SAFE_VM_IP_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be a sample_dtof* file name without path or shell characters"
    if not SAFE_CASE_RE.fullmatch(args.case):
        return "--case must be numeric"
    if not SAFE_VM_IP_RE.fullmatch(args.vm_ip):
        return "--vm-ip contains unsupported characters"
    if args.seconds <= 0 or args.seconds > 120:
        return "--seconds must be in range 1..120"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", default="j4_eeprom")
    parser.add_argument("--binary", default="sample_dtof_official_eeprom_dump_dbg")
    parser.add_argument("--case", default="2")
    parser.add_argument("--vm-ip", default="192.168.137.100")
    parser.add_argument("--seconds", type=int, default=20)
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
    prefix = f"dtof_eeprom_{label}_{stamp}"
    board_log = LOG_DIR / f"{prefix}_board.log"
    cmd_log = LOG_DIR / f"{prefix}_commands.txt"

    board_inner = (
        "cd /opt/sample/official_dtof; "
        f"./dtof_init.sh; timeout {args.seconds} ./{args.binary} {args.case} {args.vm_ip}; "
        "echo DTOF_EEPROM_RC=$?"
    )
    board_cmd = [str(PYTHON), "tools/board_run.py", board_inner]
    cmd_log.write_text(
        "Board command:\n"
        + " ".join(board_cmd)
        + "\n\nPurpose: run official dToF path only far enough to read and print the GS1860 EEPROM block.\n"
        + "Risk: starts board media/dToF sensor initialization, then skips vi_bayerdump, DtofProcess, UDP depth output, and all actuator paths.\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    print(f"COMMAND_LOG={cmd_log}")
    print(f"BOARD_LOG={board_log}")
    board_rc = run_and_log(board_cmd, board_log, env)
    print(f"BOARD_RC={board_rc}")

    extract_cmd = [
        str(PYTHON),
        "tools/dtof_eeprom_log_extract.py",
        str(board_log),
    ]
    extract_rc = run_and_log(extract_cmd, board_log.with_suffix(".extract_stdout.log"), env)
    print(f"EXTRACT_RC={extract_rc}")
    return 0 if board_rc == 0 and extract_rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
