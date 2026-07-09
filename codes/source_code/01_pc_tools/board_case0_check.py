#!/usr/bin/env python3
"""Run the approved official sample_dtof case 0 check on the board.

By default this script only prints the exact board-side command. Pass
--execute-approved after the user has approved that exact command.
"""

from __future__ import annotations

import argparse
import subprocess


BOARD_COMMAND = """cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
cd /opt/sample/official_dtof
( sleep 8; echo ) | timeout 20 ./sample_dtof 0 192.168.137.100
rc=$?
echo CASE0_RC=$rc"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--timeout", default="90")
    parser.add_argument("--login-password", default="ebaina")
    args = parser.parse_args()

    print("Board-side command:")
    print(BOARD_COMMAND)

    if not args.execute_approved:
        print("\nNot executed. Re-run with --execute-approved after explicit user approval.")
        return 0

    cmd = [
        r".\.venv\Scripts\python",
        r".\tools\board_serial.py",
        "--login-password",
        args.login_password,
        "--timeout",
        args.timeout,
        "--allow-risk",
        "run",
        BOARD_COMMAND,
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
