#!/usr/bin/env python3
"""Run an official dToF sample case over the current Wi-Fi UDP path.

This is a perception-only diagnostic. It starts a temporary host UDP forwarder,
starts a VM UDP packet checker, and runs one board-side official dToF sample
case. It does not start STM32, MCU, CAN, motor, steering, brake, throttle, or
actuator software.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
UDP_FORWARDER = ROOT / "tools" / "udp_forwarder.py"
VM_DTOF_CHECK = ROOT / "tools" / "vm_dtof_udp_check.py"
BOARD_TOOL = ROOT / "tools" / "board_auto_ssh.py"
ARTIFACT_DIR = ROOT / "artifacts" / "wifi_dtof_case_check"

DEFAULT_BOARD_HOST = "172.20.10.2"
DEFAULT_VM_HOST = "192.168.247.129"
DEFAULT_HOST_FORWARD_IP = "172.20.10.8"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_print(parts: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        parts,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(result.stdout, end="")
    return result


def board_case_command(args: argparse.Namespace) -> str:
    duration = int(args.seconds)
    timeout_sec = duration + 20
    return f"""sh -lc {shell_quote(f'''
set -e
cd /opt/sample/official_dtof
if [ -x ./dtof_init.sh ]; then
  echo BOARD_DTOF_INIT_BEGIN
  ./dtof_init.sh
  echo BOARD_DTOF_INIT_END
fi
cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
cd /opt/sample/official_dtof
( sleep {duration}; printf "\\n" ) | timeout {timeout_sec} ./{args.binary} {args.case_index} {args.host_forward_ip}
rc=$?
echo WIFI_DTOF_CASE_RC=$rc
''')}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-host", default=DEFAULT_BOARD_HOST)
    parser.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--host-forward-ip", default=DEFAULT_HOST_FORWARD_IP)
    parser.add_argument("--case-index", type=int, default=1)
    parser.add_argument("--binary", default="sample_dtof")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--max-packets", type=int, default=200)
    parser.add_argument("--board-timeout", type=float, default=90.0)
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats_path = ARTIFACT_DIR / f"case{args.case_index}_{stamp}_forwarder_stats.json"

    forwarder = [
        str(PYTHON),
        str(UDP_FORWARDER),
        "--listen-ip",
        args.host_forward_ip,
        "--forward",
        f"2368:{args.vm_host}:2368",
        "--duration-sec",
        str(args.seconds + 25),
        "--stats-json",
        str(stats_path),
    ]
    listener = [
        str(PYTHON),
        str(VM_DTOF_CHECK),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--seconds",
        str(args.seconds + 5),
        "--max-packets",
        str(args.max_packets),
    ]
    board = [
        str(PYTHON),
        str(BOARD_TOOL),
        "run",
        "--host",
        args.board_host,
        "--allow-risk",
        board_case_command(args),
    ]

    print("WIFI_DTOF_CASE_CHECK")
    print(f"CASE {args.case_index}")
    print(f"BOARD {args.board_host}")
    print(f"HOST_FORWARD {args.host_forward_ip}:2368 -> {args.vm_host}:2368")
    print(f"STATS {stats_path}")

    forwarder_proc = subprocess.Popen(
        forwarder,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(1.5)
        listener_proc = subprocess.Popen(
            listener,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        time.sleep(2.0)
        print("\n=== Board official dToF case ===")
        board_result = run_print(board, timeout=args.board_timeout)
        print("\n=== VM dToF UDP listener ===")
        listener_out, _ = listener_proc.communicate(timeout=args.seconds + 20)
        print(listener_out, end="")
        return_code = board_result.returncode
        if "DTOF_UDP_CHECK=PASS" not in listener_out:
            return_code = return_code or 6
        return return_code
    finally:
        if forwarder_proc.poll() is None:
            forwarder_proc.terminate()
            try:
                forwarder_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forwarder_proc.kill()
        forwarder_out = forwarder_proc.stdout.read() if forwarder_proc.stdout else ""
        print("\n=== Host UDP forwarder ===")
        print(forwarder_out, end="")


if __name__ == "__main__":
    raise SystemExit(main())
