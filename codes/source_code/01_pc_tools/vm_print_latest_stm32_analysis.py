#!/usr/bin/env python3
"""Print the latest VM-side STM32 protocol analysis file over SSH."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
DEFAULT_RECORD_ROOTS = [
    "/home/ebaina/parking_sensor_records/stm32_ros_check",
    "/home/ebaina/parking_sensor_records/stm32_ros_live",
    "/home/ebaina/parking_sensor_records/sensor_suite_live",
]


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_code(record_roots: list[str]) -> str:
    return f"""from pathlib import Path
roots = [Path(p) for p in {record_roots!r}]
files = []
for root in roots:
    files.extend(root.glob("run_*/stm32_session_*/stm32_protocol_analysis.json"))
    files.extend(root.glob("stm32_session_*/stm32_protocol_analysis.json"))
files = sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0)
print("ANALYSIS_COUNT", len(files))
if not files:
    print("LATEST_ANALYSIS none")
    raise SystemExit(1)
latest = files[-1]
print("LATEST_ANALYSIS", latest)
print(latest.read_text(encoding="utf-8", errors="replace"))
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.100")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--record-root",
        action="append",
        default=None,
        help="VM record root to search. May be repeated.",
    )
    args = parser.parse_args(argv)

    record_roots = args.record_root or DEFAULT_RECORD_ROOTS
    command = "python3 -c " + shell_quote(remote_code(record_roots))
    result = subprocess.run(
        [
            str(PYTHON),
            str(VM_TOOL),
            "--host",
            args.host,
            "--user",
            args.user,
            "--password",
            args.password,
            "--timeout",
            str(args.timeout),
            "run",
            command,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(result.stdout, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
