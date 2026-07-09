#!/usr/bin/env python3
"""Run RTSP+dToF case7 without reloading board media modules."""

from __future__ import annotations

import argparse
import subprocess
import time


VM_DTOF_COMMAND = [
    r".\.venv\Scripts\python",
    r".\tools\vm_dtof_udp_check.py",
    "--seconds",
    "60",
    "--max-packets",
    "30",
]

VM_RTSP_COMMAND = [
    r".\.venv\Scripts\python",
    r".\tools\vm_rtsp_check.py",
    "--seconds",
    "60",
    "--attempt-timeout",
    "8",
    "--min-stream-seconds",
    "5",
]


def build_board_command(binary: str) -> str:
    return f"""cd /opt/sample/official_dtof
( sleep 35; echo ) | timeout 70 ./{binary} 7 192.168.137.100
rc=$?
echo CASE7_NO_RELOAD_RC=$rc"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="sample_dtof_rtsp")
    parser.add_argument("--board-timeout", default="180")
    parser.add_argument("--login-password", default="ebaina")
    args = parser.parse_args()

    board_command = build_board_command(args.binary)

    print("VM dToF UDP listener command:")
    print(" ".join(VM_DTOF_COMMAND))
    print("\nVM RTSP checker command:")
    print(" ".join(VM_RTSP_COMMAND))
    print("\nBoard-side command:")
    print(board_command)

    dtof_listener = subprocess.Popen(
        VM_DTOF_COMMAND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    rtsp_checker = subprocess.Popen(
        VM_RTSP_COMMAND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)

    board_cmd = [
        r".\.venv\Scripts\python",
        r".\tools\board_serial.py",
        "--login-password",
        args.login_password,
        "--timeout",
        args.board_timeout,
        "run",
        board_command,
    ]
    board_result = subprocess.run(board_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    dtof_out, _ = dtof_listener.communicate(timeout=75)
    rtsp_out, _ = rtsp_checker.communicate(timeout=75)

    print("\n=== Board output ===")
    print(board_result.stdout, end="")
    print("\n=== VM dToF UDP listener output ===")
    print(dtof_out, end="")
    print("\n=== VM RTSP checker output ===")
    print(rtsp_out, end="")

    ok = (
        board_result.returncode == 0
        and "CASE7_NO_RELOAD_RC=0" in board_result.stdout
        and "DTOF_UDP_CHECK=PASS" in dtof_out
        and "RTSP_CHECK=PASS" in rtsp_out
    )
    print(f"\nCASE7_NO_RELOAD_COMBINED_CHECK={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
