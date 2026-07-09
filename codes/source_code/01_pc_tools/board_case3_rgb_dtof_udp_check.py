#!/usr/bin/env python3
"""Run the approved official sample_dtof case 3 + VM UDP check.

By default this script only prints the exact commands. Pass
--execute-approved after case 0 and case 1 have passed and the user has
approved the combined-mode run.
"""

from __future__ import annotations

import argparse
import subprocess
import time


BOARD_COMMAND = """cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
cd /opt/sample/official_dtof
( sleep 20; echo ) | timeout 45 ./sample_dtof 3 192.168.137.100
rc=$?
echo CASE3_RC=$rc"""

VM_LISTENER_COMMAND = [
    r".\.venv\Scripts\python",
    r".\tools\vm_dtof_udp_check.py",
    "--seconds",
    "40",
    "--max-packets",
    "30",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--board-timeout", default="150")
    parser.add_argument("--login-password", default="ebaina")
    args = parser.parse_args()

    print("VM listener command:")
    print(" ".join(VM_LISTENER_COMMAND))
    print("\nBoard-side command:")
    print(BOARD_COMMAND)

    if not args.execute_approved:
        print("\nNot executed. Re-run with --execute-approved after explicit user approval.")
        return 0

    listener = subprocess.Popen(
        VM_LISTENER_COMMAND,
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
    board_result = subprocess.run(board_cmd, text=True)

    listener_out, _ = listener.communicate(timeout=55)
    print("\n=== VM UDP listener output ===")
    print(listener_out, end="")
    return board_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
