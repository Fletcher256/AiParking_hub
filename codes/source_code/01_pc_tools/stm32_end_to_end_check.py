#!/usr/bin/env python3
"""Approval-gated end-to-end STM32 serial -> board -> VM ROS2 check."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def deploy_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(ROOT / "tools" / "deploy_ros_package.py"),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--allow-risk",
    ]


def self_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(ROOT / "tools" / "stm32_end_to_end_check.py"),
        "--vm-host",
        args.vm_host,
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
        "--udp-port",
        str(args.udp_port),
        "--vm-duration-sec",
        str(args.vm_duration_sec),
        "--board-duration-sec",
        str(args.board_duration_sec),
        "--vm-timeout",
        str(args.vm_timeout),
        "--board-timeout",
        str(args.board_timeout),
        "--receiver-warmup-sec",
        str(args.receiver_warmup_sec),
        "--allow-risk",
    ]


def vm_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(ROOT / "tools" / "vm_stm32_ros_check.py"),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--udp-port",
        str(args.udp_port),
        "--duration-sec",
        str(args.vm_duration_sec),
        "--timeout",
        str(args.vm_timeout),
        "--allow-risk",
    ]


def board_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(ROOT / "tools" / "stm32_board_udp_bridge.py"),
        "--vm-ip",
        args.vm_host,
        "--udp-port",
        str(args.udp_port),
        "--duration-sec",
        str(args.board_duration_sec),
        "--timeout",
        str(args.board_timeout),
        "--allow-risk",
    ]


def approval_text(args: argparse.Namespace) -> str:
    return f"""This action needs explicit approval before execution.

Command:
{cmdline(self_cmd(args))}

It will execute these steps:

1. Deploy and build the ROS2 package on the VM:
{cmdline(deploy_cmd(args))}

2. Start the VM-side STM32 ROS2 UDP receiver for {args.vm_duration_sec} seconds:
{cmdline(vm_cmd(args))}

3. Start the board-side receive-only STM32 USB serial UDP forwarder for {args.board_duration_sec} seconds:
{cmdline(board_cmd(args))}

Purpose:
- Verify the full current path: STM32 USB serial -> Euler Pi -> UDP -> VM ROS2.
- Confirm `/parking/stm32/raw`, `/parking/stm32/metadata`, and `/parking/stm32/health` are usable through recorded ROS2 output.
- Keep the run bounded and produce PASS/FAIL evidence.

Risk:
- Writes the ROS2 package and colcon build/install/log output on the VM.
- Writes STM32 ROS2 check logs/records on the VM.
- Writes helper scripts and optional STM32 serial records under /tmp on the board.
- Opens the board USB serial device and changes its tty settings; some STM32 boards may reset on open due to DTR/RTS wiring.
- May use usbserial_generic binding for VID:PID 1a86:7523 if the formal ch341 device is not present.
- Sends no bytes to STM32 and does not start MCU/CAN/motor/steering/brake/throttle control.

Rerun with --allow-risk only after approval."""


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            parts,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        output += f"\nCOMMAND_TIMEOUT after {timeout:.1f}s: {cmdline(parts)}\n"
        return subprocess.CompletedProcess(parts, 124, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-host", default="192.168.137.100")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--udp-port", type=int, default=24680)
    parser.add_argument("--vm-duration-sec", type=int, default=45)
    parser.add_argument("--board-duration-sec", type=float, default=30.0)
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--board-timeout", type=float, default=90.0)
    parser.add_argument("--receiver-warmup-sec", type=float, default=6.0)
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()

    if not args.allow_risk:
        print(approval_text(args))
        return 4

    print("=== Deploy ROS2 package ===")
    deploy = run(deploy_cmd(args), 300.0)
    print(deploy.stdout, end="")
    if deploy.returncode != 0:
        print("STM32_END_TO_END_CHECK FAIL deploy_failed")
        return deploy.returncode

    print("\n=== Start VM STM32 ROS2 receiver ===")
    vm_proc = subprocess.Popen(
        vm_cmd(args),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    time.sleep(args.receiver_warmup_sec)

    print("\n=== Start board STM32 USB serial UDP forwarder ===")
    board = run(board_cmd(args), args.board_timeout + args.board_duration_sec)
    print(board.stdout, end="")

    try:
        vm_stdout, _ = vm_proc.communicate(timeout=args.vm_timeout + args.vm_duration_sec)
    except subprocess.TimeoutExpired:
        vm_proc.kill()
        vm_stdout, _ = vm_proc.communicate(timeout=10)
        vm_stdout += "\nVM_RECEIVER_TIMEOUT\n"
    print("\n=== VM STM32 ROS2 receiver output ===")
    print(vm_stdout, end="")

    ok = (
        deploy.returncode == 0
        and board.returncode == 0
        and "STM32_ROS_CHECK PASS" in vm_stdout
    )
    print(f"\nSTM32_END_TO_END_CHECK {'PASS' if ok else 'FAIL'}")
    sys.stdout.flush()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
