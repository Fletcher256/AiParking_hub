#!/usr/bin/env python3
"""Start/status/stop Foxglove bridge on the Ubuntu VM.

This helper only manages the ROS2 visualization bridge. It does not install
packages and does not touch board, STM32, CAN, motor, steering, brake,
throttle, or actuator paths.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
LOCAL_SCRIPT = ROOT / "tools" / "vm_foxglove_bridge_control.sh"
REMOTE_SCRIPT = "/tmp/vm_foxglove_bridge_control.sh"

DEFAULT_VM_HOST = "192.168.247.129"
DEFAULT_VM_USER = "ebaina"
DEFAULT_VM_PASSWORD = "ebaina"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_command(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
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


def vm_base(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--timeout",
        str(args.vm_timeout),
    ]


def upload_script(args: argparse.Namespace) -> int:
    parts = vm_base(args) + ["put-text", str(LOCAL_SCRIPT), REMOTE_SCRIPT]
    return run_command(parts, args.vm_timeout + 20).returncode


def run_action(args: argparse.Namespace) -> int:
    command = (
        f"ROS_DISTRO={shell_quote(args.ros_distro)} "
        f"PORT={shell_quote(str(args.port))} "
        f"ADDRESS={shell_quote(args.address)} "
        f"VM_HOST_FOR_CLIENT={shell_quote(args.vm_host)} "
        f"bash {shell_quote(REMOTE_SCRIPT)} {shell_quote(args.action)}"
    )
    parts = vm_base(args) + ["run", command]
    return run_command(parts, args.vm_timeout + 20).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "start", "stop"])
    parser.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    parser.add_argument("--vm-user", default=DEFAULT_VM_USER)
    parser.add_argument("--vm-password", default=DEFAULT_VM_PASSWORD)
    parser.add_argument("--vm-timeout", type=float, default=30.0)
    parser.add_argument("--ros-distro", default="humble")
    parser.add_argument("--address", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Use the script already present at /tmp/vm_foxglove_bridge_control.sh.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.skip_upload:
        rc = upload_script(args)
        if rc != 0:
            return rc
    return run_action(args)


if __name__ == "__main__":
    raise SystemExit(main())
