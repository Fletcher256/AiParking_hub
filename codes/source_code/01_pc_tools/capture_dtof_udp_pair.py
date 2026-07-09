#!/usr/bin/env python3
"""Capture a paired board perception run and VM dToF UDP check.

This helper is for perception-only dToF experiments where the board command is a
whitelisted sample binary and the VM listens for official dToF UDP packets. It does not
support arbitrary board commands.
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

SAFE_BINARY_RE = re.compile(
    r"^(?:sample_dtof[A-Za-z0-9_.-]*|sample_vio|sample_vio_keyauto|sample_vio_dtof_auto)$"
)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
SAFE_CWD = {
    "/opt/sample/official_dtof",
    "/opt/sample/os08a20_dtof",
    "/opt/sample/open_camera_dtof",
    "/opt/sample/open_camera_dtof_image",
    "/opt/sample/open_camera_dtof_auto",
}


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if args.board_cwd not in SAFE_CWD:
        return f"--board-cwd must be one of: {', '.join(sorted(SAFE_CWD))}"
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be sample_vio, sample_vio_keyauto, sample_vio_dtof_auto, or a sample_dtof* file name without a path"
    if args.seconds <= 0 or args.seconds > 300:
        return "--seconds must be in range 1..300"
    if args.max_packets <= 0 or args.max_packets > 5000:
        return "--max-packets must be in range 1..5000"
    for token in args.board_args:
        if not SAFE_TOKEN_RE.fullmatch(token):
            return f"unsupported --board-args token: {token!r}"
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
    parser.add_argument("--condition", required=True)
    parser.add_argument("--board-cwd", default="/opt/sample/open_camera_dtof")
    parser.add_argument("--binary", default="sample_vio")
    parser.add_argument("--board-args", nargs="*", default=["1", "192.168.137.100"])
    parser.add_argument("--seconds", type=int, default=35)
    parser.add_argument("--max-packets", type=int, default=120)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
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
    prefix = f"dtof_udp_pair_{label}_{stamp}"
    vm_log = LOG_DIR / f"{prefix}_vm.log"
    board_log = LOG_DIR / f"{prefix}_board.log"
    cmd_log = LOG_DIR / f"{prefix}_commands.txt"
    preflight_json = LOG_DIR / f"{prefix}_preflight.json"
    preflight_summary = LOG_DIR / f"{prefix}_preflight_summary.txt"
    preflight_stdout = LOG_DIR / f"{prefix}_preflight_stdout.log"

    board_arg_text = " ".join(args.board_args)
    run_timeout = args.seconds + 10
    delayed_enter = f'( sleep {args.seconds}; printf "\\n" )'
    board_inner = (
        f"cd {args.board_cwd} && "
        f"{delayed_enter} | timeout {run_timeout} ./{args.binary}"
        + (f" {board_arg_text}" if board_arg_text else "")
        + "; echo DTOF_UDP_PAIR_RC=$?"
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
        + "\n\nPurpose: paired dToF UDP capture for a whitelisted perception sample.\n"
        + "Risk: starts only the selected board perception sample and VM UDP listener after preflight passes.\n",
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
            print("Preflight failed; not starting VM UDP capture or board sample.", file=sys.stderr)
            return preflight_rc
    if args.preflight_only:
        print("PREFLIGHT_ONLY=1")
        print("Not starting VM UDP capture or board sample.")
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

        print("Starting board perception sample...")
        board_rc = run_and_log(board_cmd, board_log, env)

        print("Waiting for VM UDP capture to finish...")
        vm_rc = vm_proc.wait()

    print(vm_log.read_text(encoding="utf-8", errors="replace"), end="")
    print(f"BOARD_RC={board_rc}")
    print(f"VM_RC={vm_rc}")
    return 0 if board_rc == 0 and vm_rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
