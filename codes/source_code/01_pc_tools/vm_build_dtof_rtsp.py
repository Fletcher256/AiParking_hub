#!/usr/bin/env python3
"""Build the RTSP-enabled official dToF sample on the Ubuntu VM."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
VM_TOOL = REPO_ROOT / "tools" / "vm_ssh_run.py"
LOCAL_SAMPLE_DTOF = (
    REPO_ROOT
    / "vendor"
    / "SS928V100_SDK_V2.0.2.2_MPP_Sample-master"
    / "src"
    / "dtof"
    / "sample_dtof.c"
)

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASSWORD = "ebaina"
BUILD_DIR = "/home/ebaina/official_dtof_rtsp_build_20260530_0100"
REMOTE_SAMPLE_DTOF = f"{BUILD_DIR}/src/dtof/sample_dtof.c"

PREPARE_CMD = f"""set -e
BUILD={BUILD_DIR}
mkdir -p "$BUILD"
cd "$BUILD"
python3 - <<'PY'
import zipfile
from pathlib import Path

with zipfile.ZipFile('/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip') as zf:
    for member in zf.infolist():
        normalized = member.filename.replace('\\\\', '/')
        if not normalized:
            continue
        target = Path(normalized)
        if member.is_dir() or normalized.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open('wb') as dst:
            dst.write(src.read())
PY
test -f "$BUILD/src/dtof/sample_dtof.c"
echo RTSP_BUILD_DIR="$BUILD"
"""

BUILD_CMD = f"""set -e
cd {BUILD_DIR}/src/dtof
PATH=/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:$PATH \\
make OS_TYPE=linux \\
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \\
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \\
  all
sha256sum sample_dtof
"""


def vm_run_args(command: str, timeout: float) -> list[str]:
    return [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        VM_HOST,
        "--user",
        VM_USER,
        "--password",
        VM_PASSWORD,
        "--timeout",
        str(timeout),
        "--allow-risk",
        "run",
        command,
    ]


def vm_put_args(timeout: float) -> list[str]:
    return [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        VM_HOST,
        "--user",
        VM_USER,
        "--password",
        VM_PASSWORD,
        "--timeout",
        str(timeout),
        "--allow-risk",
        "put-text",
        str(LOCAL_SAMPLE_DTOF),
        REMOTE_SAMPLE_DTOF,
    ]


def print_command(argv: list[str]) -> None:
    print(" ".join(f'"{arg}"' if " " in arg or "\n" in arg else arg for arg in argv))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args()

    commands = [
        vm_run_args(PREPARE_CMD, 120),
        vm_put_args(120),
        vm_run_args(BUILD_CMD, 600),
    ]

    if not args.execute_approved:
        print("Dry run only. After approval, rerun with --execute-approved.")
        print(f"Local patched source: {LOCAL_SAMPLE_DTOF}")
        print(f"VM build directory: {BUILD_DIR}")
        print()
        for i, command in enumerate(commands, 1):
            print(f"[{i}]")
            print_command(command)
            print()
        return 0

    for command in commands:
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
