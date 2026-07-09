#!/usr/bin/env python3
"""Run an official dToF-only case without reloading SS928 media modules."""

from __future__ import annotations

import argparse
import subprocess
import time


BOARD_COMMAND_TEMPLATE = """cd /opt/sample/official_dtof
if [ -x ./dtof_init.sh ]; then
  echo BOARD_DTOF_INIT_BEGIN
  ./dtof_init.sh
  echo BOARD_DTOF_INIT_END
fi
{reload_block}
( sleep {seconds}; echo ) | timeout {timeout_sec} ./{binary} {case_index} {dst_ip}
rc=$?
echo DTOF_CASE_NO_RELOAD_RC=$rc"""

VM_LISTENER_COMMAND = [
    r".\.venv\Scripts\python",
    r".\tools\vm_dtof_udp_check.py",
    "--seconds",
    "30",
    "--max-packets",
    "20",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-timeout", default="80")
    parser.add_argument("--login-password", default="ebaina")
    parser.add_argument("--binary", default="sample_dtof")
    parser.add_argument("--case-index", type=int, default=1)
    parser.add_argument("--dst-ip", default="192.168.137.100")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--reload-media", action="store_true")
    args = parser.parse_args()
    reload_block = ""
    if args.reload_media:
        reload_block = (
            "cd /opt/ko\n"
            "echo BOARD_MEDIA_RELOAD_BEGIN\n"
            "./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20\n"
            "echo BOARD_MEDIA_RELOAD_END\n"
            "cd /opt/sample/official_dtof"
        )
    board_command = BOARD_COMMAND_TEMPLATE.format(
        binary=args.binary,
        case_index=args.case_index,
        dst_ip=args.dst_ip,
        seconds=args.seconds,
        timeout_sec=args.seconds + 20,
        reload_block=reload_block,
    )
    VM_LISTENER_COMMAND[-4:] = ["--seconds", str(args.seconds + 15), "--max-packets", "80"]

    print("VM listener command:")
    print(" ".join(VM_LISTENER_COMMAND))
    print("\nBoard-side command:")
    print(board_command)

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
        "run",
        board_command,
    ]
    board_result = subprocess.run(board_cmd, text=True)

    listener_out, _ = listener.communicate(timeout=45)
    print("\n=== VM UDP listener output ===")
    print(listener_out, end="")
    return board_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
