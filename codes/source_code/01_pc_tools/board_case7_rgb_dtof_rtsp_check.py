#!/usr/bin/env python3
"""Run approved RTSP-enabled sample_dtof case 7 with VM UDP and RTSP checks.

By default this script only prints the exact commands. Pass
--execute-approved after the user approves loading the media stack and
starting the camera+dToF sample on the board.
"""

from __future__ import annotations

import argparse
import subprocess
import time


BOARD_COMMAND = """cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
cd /opt/sample/official_dtof
( sleep 35; echo ) | timeout 70 ./sample_dtof_rtsp 7 192.168.137.100
rc=$?
echo CASE7_RC=$rc"""

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


def print_command(argv: list[str]) -> None:
    print(" ".join(argv))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--board-timeout", default="180")
    parser.add_argument("--login-password", default="ebaina")
    args = parser.parse_args()

    print("VM dToF UDP listener command:")
    print_command(VM_DTOF_COMMAND)
    print("\nVM RTSP checker command:")
    print_command(VM_RTSP_COMMAND)
    print("\nBoard-side command:")
    print(BOARD_COMMAND)

    if not args.execute_approved:
        print("\nNot executed. Re-run with --execute-approved after explicit user approval.")
        return 0

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
        "--allow-risk",
        "run",
        BOARD_COMMAND,
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
        and "CASE7_RC=0" in board_result.stdout
        and "DTOF_UDP_CHECK=PASS" in dtof_out
        and "RTSP_CHECK=PASS" in rtsp_out
    )
    print(f"\nCASE7_COMBINED_CHECK={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
