#!/usr/bin/env python3
"""Run a VM-side audit for the low-bandwidth Foxglove viewing path.

This check is perception-only. It verifies that the recommended camera and
dToF visualization topics produce messages, that dToF point cloud messages are
idle by default, and that the Foxglove bridge did not advertise blocked
high-bandwidth topics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
LOCAL_SCRIPT = ROOT / "tools" / "vm_foxglove_low_bandwidth_audit.sh"
REMOTE_SCRIPT = "/tmp/vm_foxglove_low_bandwidth_audit.sh"
REPORT_ROOT = ROOT / "artifacts" / "foxglove_low_bandwidth_audit"


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        parts,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def trim(text: str, limit: int = 80000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[trimmed]...\n" + text[-half:]


def parse_checks(text: str) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for line in text.splitlines():
        if not (line.startswith("PASS ") or line.startswith("FAIL ")):
            continue
        status, rest = line.split(" ", 1)
        if " - " in rest:
            name, detail = rest.split(" - ", 1)
        else:
            name, detail = rest, ""
        checks.append({"status": status, "name": name, "detail": detail})
    return checks


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"foxglove_low_bandwidth_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-host", default="192.168.247.129")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=45.0)
    parser.add_argument("--skip-upload", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "safety": {
            "perception_only": True,
            "actuator_control_allowed": False,
            "stm32_enabled": False,
        },
        "vm_host": args.vm_host,
        "steps": {},
        "checks": [],
    }

    if not args.skip_upload:
        upload = run(vm_base(args) + ["put-text", str(LOCAL_SCRIPT), REMOTE_SCRIPT], args.vm_timeout + 20)
        report["steps"]["upload"] = {"returncode": upload.returncode, "stdout": trim(upload.stdout)}
        if upload.returncode != 0:
            report["overall"] = "FAIL"
            path = write_report(report)
            print(f"FOXGLOVE_LOW_BANDWIDTH_AUDIT_REPORT {path}")
            return upload.returncode

    command = f"bash {REMOTE_SCRIPT}"
    audit = run(vm_base(args) + ["run", command], args.vm_timeout + 60)
    report["steps"]["audit"] = {"returncode": audit.returncode, "stdout": trim(audit.stdout)}
    report["checks"] = parse_checks(audit.stdout)
    report["overall"] = "PASS" if audit.returncode == 0 else "FAIL"
    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = write_report(report)
    print(f"FOXGLOVE_LOW_BANDWIDTH_AUDIT_REPORT {path}")
    return audit.returncode


if __name__ == "__main__":
    raise SystemExit(main())
