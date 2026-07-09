#!/usr/bin/env python3
"""Capture one dToF Phase1 condition with board and VM logs.

This helper starts the VM UDP checker first, then runs the selected board
sample_dtof binary for case2/J4. It is perception-only and does not touch any
actuator path.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"

SAFE_BINARY_RE = re.compile(r"^sample_dtof[A-Za-z0-9_.-]*$")
SAFE_CASE_RE = re.compile(r"^\d+$")
SAFE_VM_IP_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_BOARD_DIR_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be a sample_dtof* file name without path or shell characters"
    if not SAFE_CASE_RE.fullmatch(args.case):
        return "--case must be numeric"
    if not SAFE_VM_IP_RE.fullmatch(args.vm_ip):
        return "--vm-ip contains unsupported characters"
    if not SAFE_BOARD_DIR_RE.fullmatch(args.board_dir):
        return "--board-dir must be an absolute board path without shell characters"
    if args.seconds <= 0 or args.seconds > 300:
        return "--seconds must be in range 1..300"
    if args.max_packets <= 0 or args.max_packets > 5000:
        return "--max-packets must be in range 1..5000"
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
    parser.add_argument("--condition", required=True, help="Label such as clear, near30cm, covered")
    parser.add_argument("--binary", default="sample_dtof_official_dbg")
    parser.add_argument("--case", default="2")
    parser.add_argument("--vm-ip", default="192.168.137.100")
    parser.add_argument("--board-dir", default="/opt/sample/official_dtof")
    parser.add_argument("--seconds", type=int, default=35)
    parser.add_argument("--max-packets", type=int, default=120)
    parser.add_argument("--skip-dtof-init", action="store_true")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the read-only safety/status preflight before starting live capture.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run the read-only preflight and exit before starting VM UDP or board sample.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Only capture logs; do not run dtof_phase1_log_report.py afterward.",
    )
    args = parser.parse_args()

    validation_error = validate_args(args)
    if validation_error:
        print(f"Invalid argument: {validation_error}", file=sys.stderr)
        return 2
    if args.skip_preflight and args.preflight_only:
        print("--preflight-only cannot be combined with --skip-preflight", file=sys.stderr)
        return 2

    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = safe_name(args.condition)
    prefix = f"dtof_phase1_{label}_{stamp}"
    vm_log = LOG_DIR / f"{prefix}_vm.log"
    board_log = LOG_DIR / f"{prefix}_board.log"
    cmd_log = LOG_DIR / f"{prefix}_commands.txt"
    report_log = LOG_DIR / f"{prefix}_report.json"
    preflight_json = LOG_DIR / f"{prefix}_preflight.json"
    preflight_summary = LOG_DIR / f"{prefix}_preflight_summary.txt"
    preflight_stdout = LOG_DIR / f"{prefix}_preflight_stdout.log"

    init_part = "" if args.skip_dtof_init else "./dtof_init.sh; "
    run_timeout = args.seconds + 10
    delayed_enter = f'( sleep {args.seconds}; printf "\\n" )'
    board_inner = (
        f"cd {args.board_dir}; "
        f"{init_part}{delayed_enter} | timeout {run_timeout} ./{args.binary} {args.case} {args.vm_ip}; "
        "echo DTOF_PHASE1_RC=$?"
    )

    vm_cmd = [
        str(PYTHON),
        "tools/vm_dtof_udp_check.py",
        "--seconds",
        str(args.seconds),
        "--max-packets",
        str(args.max_packets),
    ]
    board_cmd = [str(PYTHON), "tools/board_run.py", board_inner]
    preflight_cmd = [
        str(PYTHON),
        "tools/dtof_live_preflight.py",
        "--out",
        str(preflight_json),
        "--summary-out",
        str(preflight_summary),
    ]

    cmd_log.write_text(
        "Preflight command:\n"
        + ("SKIPPED\n" if args.skip_preflight else " ".join(preflight_cmd) + "\n")
        + "\nVM command:\n"
        + " ".join(vm_cmd)
        + "\n\nBoard command:\n"
        + " ".join(board_cmd)
        + "\n\nMode:\n"
        + (
            "preflight-only; VM and board live capture commands will not be executed.\n"
            if args.preflight_only
            else "live capture; VM and board commands execute only after preflight passes.\n"
        )
        + "\n\nPurpose: Phase1 dToF J4 raw/output and UDP capture for one physical condition.\n"
        + (
            "Risk: starts a perception-only board sample and VM UDP listener after read-only "
            "preflight passes; no actuator path.\n"
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"COMMAND_LOG={cmd_log}")
    if not args.skip_preflight:
        print(f"PREFLIGHT_JSON={preflight_json}")
        print(f"PREFLIGHT_SUMMARY={preflight_summary}")
        print(f"PREFLIGHT_STDOUT={preflight_stdout}")
        print("Running read-only safety/status preflight...")
        preflight_rc = run_and_log(preflight_cmd, preflight_stdout, env)
        print(f"PREFLIGHT_RC={preflight_rc}")
        if preflight_rc != 0:
            print("Preflight failed; not starting VM UDP capture or board dToF sample.", file=sys.stderr)
            return preflight_rc
    if args.preflight_only:
        print("PREFLIGHT_ONLY=1")
        print("Not starting VM UDP capture or board dToF sample.")
        return 0

    print(f"VM_LOG={vm_log}")
    print(f"BOARD_LOG={board_log}")
    print("Starting VM UDP capture...")
    with vm_log.open("w", encoding="utf-8", errors="replace") as vm_out:
        vm_proc = subprocess.Popen(
            vm_cmd,
            cwd=ROOT,
            env=env,
            stdout=vm_out,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(2.0)

        print("Starting board dToF sample...")
        board_rc = run_and_log(board_cmd, board_log, env)

        print("Waiting for VM UDP capture to finish...")
        vm_rc = vm_proc.wait()

    print(vm_log.read_text(encoding="utf-8", errors="replace"), end="")

    print(f"BOARD_RC={board_rc}")
    print(f"VM_RC={vm_rc}")
    final_rc = 0 if board_rc == 0 and vm_rc == 0 else 1

    if not args.no_report:
        report_cmd = [
            str(PYTHON),
            "tools/dtof_phase1_log_report.py",
            "--condition",
            args.condition,
            "--board-log",
            str(board_log),
            "--vm-log",
            str(vm_log),
            "--out",
            str(report_log),
        ]
        print(f"REPORT_LOG={report_log}")
        report_rc = run_and_log(report_cmd, report_log.with_suffix(".report_stdout.log"), env)
        print(f"REPORT_RC={report_rc}")
        if report_rc != 0:
            final_rc = report_rc

    return final_rc


if __name__ == "__main__":
    raise SystemExit(main())
