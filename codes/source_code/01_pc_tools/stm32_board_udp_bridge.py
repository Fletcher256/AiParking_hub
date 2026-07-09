#!/usr/bin/env python3
"""Approval-gated launcher for the board-side STM32 serial UDP forwarder."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD_TOOL = ROOT / "tools" / "board_serial.py"
BOARD_BRIDGE_SCRIPT = ROOT / "tools" / "board_stm32_usb_serial_udp_bridge.py"
REMOTE_SCRIPT = "/tmp/board_stm32_usb_serial_udp_bridge.py"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def board_tool_base(args: argparse.Namespace) -> list[str]:
    return [
        str(ROOT / ".venv" / "Scripts" / "python"),
        str(BOARD_TOOL),
        "--port",
        args.port,
        "--baud",
        str(args.board_baud),
        "--login-user",
        args.login_user,
        "--login-password",
        args.login_password,
        "--timeout",
        str(args.timeout),
    ]


def board_bridge_command(args: argparse.Namespace) -> str:
    parts = [
        "python3",
        REMOTE_SCRIPT,
        "--vm-ip",
        args.vm_ip,
        "--udp-port",
        str(args.udp_port),
        "--vid",
        args.vid,
        "--pid",
        args.pid,
        "--baud",
        str(args.stm32_baud),
        "--chunk-size",
        str(args.chunk_size),
        "--duration-sec",
        str(args.duration_sec),
    ]
    if args.bind_generic:
        parts.append("--bind-generic")
    if args.no_record:
        parts.append("--no-record")
    return " ".join(shell_quote(part) for part in parts)


def approval_text(args: argparse.Namespace) -> str:
    upload = board_tool_base(args) + [
        "--allow-risk",
        "put-text",
        "--allow-risk",
        str(BOARD_BRIDGE_SCRIPT),
        REMOTE_SCRIPT,
    ]
    run = board_tool_base(args) + [
        "--allow-risk",
        "run",
        "--allow-risk",
        board_bridge_command(args),
    ]
    return f"""This action needs explicit approval before execution.

Command 1, upload board UDP forwarder:
{cmdline(upload)}

Command 2, run receive-only UDP forwarding:
{cmdline(run)}

Purpose:
- Copy the board-side receive-only STM32 USB serial UDP forwarder to /tmp.
- Open the detected CH340/CH341 serial device at {args.stm32_baud} 8N1.
- Forward received serial bytes to VM {args.vm_ip}:{args.udp_port}.
- Keep local board-side raw/chunk records unless --no-record is used.
- Run for {args.duration_sec} seconds for a bounded validation run.

Risk:
- Writes one helper file under /tmp on the board.
- May write VID:PID {args.vid}:{args.pid} to usbserial_generic new_id if --bind-generic is used and no serial device exists.
- Opens the USB serial device and changes its terminal settings.
- Some STM32 boards reset when a serial device is opened because of DTR/RTS wiring.
- Sends UDP packets to the VM, but sends no bytes to STM32 and does not start MCU/CAN/motor/steering/brake/throttle control.

Rerun this tool with --allow-risk only after approval."""


def run_command(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--login-user", default="root")
    parser.add_argument("--login-password", default="ebaina")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--vm-ip", default="192.168.137.100")
    parser.add_argument("--udp-port", type=int, default=24680)
    parser.add_argument("--vid", default="1a86")
    parser.add_argument("--pid", default="7523")
    parser.add_argument("--stm32-baud", type=int, default=9600)
    parser.add_argument("--chunk-size", type=int, default=256)
    parser.add_argument("--duration-sec", type=float, default=30.0)
    parser.add_argument("--bind-generic", dest="bind_generic", action="store_true", default=True)
    parser.add_argument("--no-bind-generic", dest="bind_generic", action="store_false")
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()

    if not args.allow_risk:
        print(approval_text(args))
        return 4

    upload = run_command(
        board_tool_base(args)
        + ["--allow-risk", "put-text", "--allow-risk", str(BOARD_BRIDGE_SCRIPT), REMOTE_SCRIPT],
        args.timeout,
    )
    print(upload.stdout, end="")
    if upload.returncode != 0:
        return upload.returncode

    run = run_command(
        board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", board_bridge_command(args)],
        max(args.timeout, args.duration_sec + 30),
    )
    print(run.stdout, end="")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
