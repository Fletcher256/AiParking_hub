#!/usr/bin/env python3
"""Read-only preflight check before live dToF perception captures.

This script intentionally uses only fixed read-only commands. It checks that no
known dToF sample or actuator-like processes are running, UDP 2368 is free, and
the expected official dToF binaries/configs are present on the board.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"

EXPECTED_BOARD_SHA256 = {
    "sample_dtof_official_j4cfg_dbg": "a6398c9cb6c36c3bf36b97ea8c0d8bc00fbfd3c3c8467a307d18f06353a7b56c",
    "sample_dtof_official_line_dump_cp_dbg": "3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea",
    "sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg": "b2786dfc14b858ee3cb3536de6e16c6113d68d1664e2c2d4e7375e93c951bac7",
    "dtof_init.sh": "eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0",
    "dtof.ini": "7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6",
    "gs1860_register.ini": "3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb",
}

BOARD_BASIC_CMD = "echo BOARD_BASIC; date; whoami; uname -a"
BOARD_PROCESS_CMD = (
    "echo BOARD_PROCESS_CHECK; "
    "ps -ef | grep -e sample_dtof -e rtsp -e dtof -e mcu -e actuator "
    "-e motor -e steer -e brake -e throttle -e can -e serial | grep -v grep || true"
)
BOARD_HASH_CMD = (
    "cd /opt/sample/official_dtof && echo BOARD_HASHES; "
    "for f in sample_dtof_official_j4cfg_dbg sample_dtof_official_line_dump_cp_dbg "
    "sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg dtof_init.sh dtof.ini "
    "gs1860_register.ini; do "
    'if [ -f "$f" ]; then sha256sum "$f"; else echo MISSING "$f"; fi; '
    "done"
)
BOARD_MEDIA_CMD = (
    "echo BOARD_MEDIA_PORTS; echo MODULES; "
    "cat /proc/modules | grep -i -e mipi -e vi -e isp -e vpss -e sensor -e os08 "
    "-e gs1860 -e ot_ -e ss_ || true; "
    "echo UDP_2368; "
    "ss -lunp 2>/dev/null | grep 2368 || true; "
    "netstat -lunp 2>/dev/null | grep 2368 || true"
)
VM_BASIC_CMD = "echo VM_BASIC; date; whoami; hostname; uname -a"
VM_PROCESS_PORT_CMD = (
    "echo VM_PROCESS_AND_PORTS; "
    "ps -ef | grep -e sample_dtof -e rtsp -e dtof -e mcu -e actuator "
    "-e motor -e steer -e brake -e throttle -e can -e serial -e foxglove_bridge "
    "-e ros2 | grep -v grep || true; "
    "echo UDP_2368; ss -lunp | grep 2368 || true; "
    "echo TCP_8765; ss -ltnp | grep 8765 || true"
)

PROCESS_DANGER_RE = re.compile(
    r"sample_dtof|rtsp|dtof|mcu|actuator|motor|steer|brake|throttle|serial|"
    r"\bcan\b|can_|_can|canbus|socketcan|candump|cansend",
    re.IGNORECASE,
)
ALLOWED_PROCESS_RE = re.compile(r"wpa_supplicant|foxglove_bridge", re.IGNORECASE)
SHA_RE = re.compile(r"^([0-9a-f]{64})\s+(.+?)\s*$", re.IGNORECASE)


def run_command(command: list[str], timeout: float = 180.0) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_board(command: str) -> dict[str, Any]:
    return run_command([str(PYTHON), "tools/board_run.py", command])


def run_vm(command: str) -> dict[str, Any]:
    return run_command([str(PYTHON), "tools/vm_ssh_run.py", "run", command])


def lines_after_marker(output: str, marker: str, stop_markers: set[str] | None = None) -> list[str]:
    stop_markers = stop_markers or set()
    lines = output.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == marker:
            in_section = True
            continue
        if in_section and stripped in stop_markers:
            break
        if in_section:
            if stripped and not stripped.startswith("[vm_ssh_run]"):
                out.append(line)
    return out


def unsafe_process_lines(lines: list[str]) -> list[str]:
    unsafe: list[str] = []
    for line in lines:
        if ALLOWED_PROCESS_RE.search(line):
            continue
        if PROCESS_DANGER_RE.search(line):
            unsafe.append(line)
    return unsafe


def parse_board_hashes(output: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in output.splitlines():
        match = SHA_RE.match(line.strip())
        if not match:
            continue
        digest, raw_name = match.groups()
        hashes[Path(raw_name).name] = digest.lower()
    return hashes


def build_report() -> dict[str, Any]:
    checks = {
        "board_basic": run_board(BOARD_BASIC_CMD),
        "board_process": run_board(BOARD_PROCESS_CMD),
        "board_hashes": run_board(BOARD_HASH_CMD),
        "board_media_ports": run_board(BOARD_MEDIA_CMD),
        "vm_basic": run_vm(VM_BASIC_CMD),
        "vm_process_ports": run_vm(VM_PROCESS_PORT_CMD),
    }

    issues: list[str] = []
    warnings: list[str] = []

    for name, check in checks.items():
        if check["returncode"] != 0:
            issues.append(f"{name} returned rc={check['returncode']}")

    board_process_lines = lines_after_marker(checks["board_process"]["stdout"], "BOARD_PROCESS_CHECK")
    board_unsafe = unsafe_process_lines(board_process_lines)
    if board_unsafe:
        issues.append("unsafe board process lines were observed")

    vm_process_lines = lines_after_marker(
        checks["vm_process_ports"]["stdout"],
        "VM_PROCESS_AND_PORTS",
        {"UDP_2368", "TCP_8765"},
    )
    vm_unsafe = unsafe_process_lines(vm_process_lines)
    if vm_unsafe:
        issues.append("unsafe VM process lines were observed")

    board_udp_2368 = lines_after_marker(checks["board_media_ports"]["stdout"], "UDP_2368")
    if board_udp_2368:
        issues.append("board UDP 2368 appears occupied")

    vm_udp_2368 = lines_after_marker(checks["vm_process_ports"]["stdout"], "UDP_2368", {"TCP_8765"})
    if vm_udp_2368:
        issues.append("VM UDP 2368 appears occupied")

    vm_tcp_8765 = lines_after_marker(checks["vm_process_ports"]["stdout"], "TCP_8765")
    if vm_tcp_8765:
        warnings.append("VM TCP 8765 is occupied, usually by the existing Foxglove bridge")

    hashes = parse_board_hashes(checks["board_hashes"]["stdout"])
    hash_status: dict[str, dict[str, Any]] = {}
    for name, expected in EXPECTED_BOARD_SHA256.items():
        actual = hashes.get(name)
        ok = actual == expected
        hash_status[name] = {
            "expected": expected,
            "actual": actual,
            "ok": ok,
        }
        if actual is None:
            issues.append(f"missing board file hash for {name}")
        elif not ok:
            issues.append(f"board hash mismatch for {name}")

    modules = checks["board_media_ports"]["stdout"]
    required_modules = ["ot_mipi_rx", "ot_vi", "ot_isp", "ot_vpss"]
    missing_modules = [name for name in required_modules if name not in modules]
    if missing_modules:
        issues.append("missing expected media modules: " + ",".join(missing_modules))

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "purpose": "Read-only safety/status preflight before live dToF perception capture.",
        "risk": "Runs fixed read-only board/VM inspection commands only; does not start dToF sample, UDP listener, or actuator path.",
        "pass": not issues,
        "issues": issues,
        "warnings": warnings,
        "board_process_lines": board_process_lines,
        "board_unsafe_process_lines": board_unsafe,
        "vm_process_lines": vm_process_lines,
        "vm_unsafe_process_lines": vm_unsafe,
        "board_udp_2368_lines": board_udp_2368,
        "vm_udp_2368_lines": vm_udp_2368,
        "vm_tcp_8765_lines": vm_tcp_8765,
        "board_hash_status": hash_status,
        "checks": checks,
    }


def build_summary(report: dict[str, Any]) -> str:
    lines = ["DTOF_LIVE_PREFLIGHT_SUMMARY"]
    lines.append(f"timestamp={report['timestamp']}")
    lines.append(f"pass={report['pass']}")
    lines.append(f"issues={json.dumps(report['issues'], ensure_ascii=False, separators=(',', ':'))}")
    lines.append(f"warnings={json.dumps(report['warnings'], ensure_ascii=False, separators=(',', ':'))}")
    lines.append(f"board_unsafe_process_count={len(report['board_unsafe_process_lines'])}")
    lines.append(f"vm_unsafe_process_count={len(report['vm_unsafe_process_lines'])}")
    lines.append(f"board_udp_2368_occupied={bool(report['board_udp_2368_lines'])}")
    lines.append(f"vm_udp_2368_occupied={bool(report['vm_udp_2368_lines'])}")
    lines.append(f"vm_tcp_8765_lines={len(report['vm_tcp_8765_lines'])}")
    ok_hashes = [
        name for name, status in report["board_hash_status"].items()
        if status.get("ok")
    ]
    bad_hashes = [
        name for name, status in report["board_hash_status"].items()
        if not status.get("ok")
    ]
    lines.append("board_hash_ok=" + ",".join(ok_hashes))
    lines.append("board_hash_bad=" + ",".join(bad_hashes))
    if report["board_process_lines"]:
        lines.append("board_process_lines=" + json.dumps(report["board_process_lines"], ensure_ascii=False))
    if report["vm_tcp_8765_lines"]:
        lines.append("vm_tcp_8765=" + json.dumps(report["vm_tcp_8765_lines"], ensure_ascii=False))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Full JSON output path.")
    parser.add_argument("--summary-out", type=Path, help="Compact summary output path.")
    args = parser.parse_args()

    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out or LOG_DIR / f"dtof_live_preflight_{stamp}.json"
    summary_path = args.summary_out or LOG_DIR / f"dtof_live_preflight_{stamp}_summary.txt"

    report = build_report()
    summary = build_summary(report)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(summary + "\n", encoding="utf-8")

    print(f"PREFLIGHT_JSON={out_path}")
    print(f"PREFLIGHT_SUMMARY={summary_path}")
    print(summary)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
