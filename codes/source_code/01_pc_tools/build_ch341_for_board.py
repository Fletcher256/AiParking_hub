#!/usr/bin/env python3
"""Build the official WCH CH341 driver against a matching board kernel tree on the VM."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
DRIVER_DIR = ROOT / "vendor" / "WCHSoftGroup_ch341ser_linux" / "driver"
BOARD_KERNEL_RELEASE = "4.19.90"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def connect(host: str, user: str, password: str):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=15, banner_timeout=15, auth_timeout=15)
    return client


def run_raw(client, command: str, timeout: int = 240) -> int:
    print(f"$ {command}")
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    return rc


def ensure_remote_dir(sftp, path: str) -> None:
    parts = []
    current = path
    while current and current not in {"/", "."}:
        parts.append(current)
        current = os.path.dirname(current)
    for item in reversed(parts):
        try:
            sftp.stat(item)
        except FileNotFoundError:
            sftp.mkdir(item)


def upload_driver(client, remote_dir: str) -> None:
    sftp = client.open_sftp()
    try:
        ensure_remote_dir(sftp, remote_dir)
        for path in DRIVER_DIR.iterdir():
            if path.is_file():
                remote_file = remote_dir.rstrip("/") + "/" + path.name
                print(f"  upload {path} -> {remote_file}")
                sftp.put(str(path), remote_file)
    finally:
        sftp.close()


def quoted(value: str) -> str:
    return shlex.quote(value)


def build_command(args: argparse.Namespace) -> str:
    kernel = quoted(args.kernel_dir)
    work = quoted(args.remote_driver_dir)
    cross = quoted(args.cross_compile)
    arch = quoted(args.arch)
    release = quoted(BOARD_KERNEL_RELEASE)
    return f"""bash -lc '
set -e
KERNELDIR={kernel}
WORK={work}
EXPECTED={release}
if [ ! -d "$KERNELDIR" ]; then
  echo "CH341_BUILD_FAIL missing_kernel_dir=$KERNELDIR"
  exit 2
fi
if [ ! -f "$KERNELDIR/Makefile" ]; then
  echo "CH341_BUILD_FAIL missing_kernel_makefile=$KERNELDIR/Makefile"
  exit 3
fi
if [ ! -f "$KERNELDIR/include/generated/utsrelease.h" ]; then
  echo "CH341_BUILD_FAIL missing_utsrelease=$KERNELDIR/include/generated/utsrelease.h"
  exit 4
fi
if ! grep -q "$EXPECTED" "$KERNELDIR/include/generated/utsrelease.h"; then
  echo "CH341_BUILD_FAIL kernel_release_mismatch expected=$EXPECTED"
  cat "$KERNELDIR/include/generated/utsrelease.h"
  exit 5
fi
cd "$WORK"
make clean >/tmp/ch341_make_clean.log 2>&1 || true
make -C "$KERNELDIR" M="$WORK" ARCH={arch} CROSS_COMPILE={cross} modules
test -f "$WORK/ch341.ko"
echo CH341_BUILD_OUTPUT "$WORK/ch341.ko"
file "$WORK/ch341.ko" || true
modinfo "$WORK/ch341.ko" | sed -n "1,80p" || true
echo CH341_BUILD_PASS
'"""


def approval_text(args: argparse.Namespace) -> str:
    self_cmd = [
        str(ROOT / ".venv" / "Scripts" / "python"),
        str(ROOT / "tools" / "build_ch341_for_board.py"),
        "--host",
        args.host,
        "--user",
        args.user,
        "--password",
        args.password,
        "--kernel-dir",
        args.kernel_dir,
        "--remote-driver-dir",
        args.remote_driver_dir,
        "--cross-compile",
        args.cross_compile,
        "--arch",
        args.arch,
        "--allow-risk",
    ]
    return f"""This action needs explicit approval before execution.

Command:
{cmdline(self_cmd)}

Purpose:
- Upload the official WCH CH340/CH341 Linux driver source to the VM.
- Build ch341.ko against the specified board kernel build directory.
- Refuse to build if the kernel release marker is not {BOARD_KERNEL_RELEASE}.

Risk:
- Writes driver source and build outputs under {args.remote_driver_dir} on the VM.
- Runs make on the VM.
- Does not load, install, or copy a kernel module to the board.
- Does not touch STM32, CAN, motor, steering, brake, throttle, or actuator commands.

Rerun with --allow-risk only after approval."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.100")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--kernel-dir", required=True, help="VM path to matching board kernel build tree.")
    parser.add_argument("--remote-driver-dir", default="/home/ebaina/ch341_board_build/driver")
    parser.add_argument("--cross-compile", default="/opt/linux/x86-arm/aarch64-mix210-linux/bin/aarch64-mix210-linux-")
    parser.add_argument("--arch", default="arm64")
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()

    if not args.allow_risk:
        print(approval_text(args))
        return 4

    if not DRIVER_DIR.exists():
        print(f"CH341_BUILD_FAIL missing_local_driver_dir={DRIVER_DIR}")
        return 2

    client = connect(args.host, args.user, args.password)
    try:
        upload_driver(client, args.remote_driver_dir)
        return run_raw(client, build_command(args), timeout=300)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
