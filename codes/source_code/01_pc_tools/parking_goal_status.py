#!/usr/bin/env python3
"""Summarize objective-level evidence for the receive-only parking link goal.

This is a read-only status tool. It gathers current audit output plus the latest
acceptance/post-replug artifacts and reports which objective requirements are
proved, which are expected warnings, and which still need external evidence.
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
AUDIT_TOOL = ROOT / "tools" / "parking_link_audit.py"
REPORT_ROOT = ROOT / "artifacts" / "parking_goal_status"
ACCEPTANCE_ROOT = ROOT / "artifacts" / "parking_link_acceptance"
POST_REPLUG_ROOT = ROOT / "artifacts" / "post_replug_validation"


EXPECTED_WARNINGS = {"board_ch341_driver_mode", "formal_ch341_route"}


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
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


def latest_json(root: Path, pattern: str) -> tuple[Path | None, dict[str, Any] | None]:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if not files:
        return None, None
    path = files[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return path, None
    return path, data if isinstance(data, dict) else None


def extract_json_object(output: str) -> dict[str, Any] | None:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def check_item(checks: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in checks:
        if item.get("name") == name:
            return item
    return None


def all_report_checks_pass(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    return all(item.get("status") == "PASS" for item in report.get("checks", []))


def audit_no_failures_except_expected(audit: dict[str, Any] | None) -> bool:
    if not audit:
        return False
    checks = audit.get("checks", [])
    failures = [item for item in checks if item.get("status") == "FAIL"]
    unexpected_warnings = [
        item for item in checks
        if item.get("status") == "WARN" and item.get("name") not in EXPECTED_WARNINGS
    ]
    return not failures and not unexpected_warnings


def add(requirements: list[dict[str, str]], name: str, status: str, evidence: str) -> None:
    requirements.append({"name": name, "status": status, "evidence": evidence})


def source_contains(path: Path, *tokens: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return all(token in text for token in tokens)


def run_live_audit(args: argparse.Namespace) -> tuple[subprocess.CompletedProcess[str] | None, dict[str, Any] | None]:
    if args.skip_live_audit:
        return None, None
    command = [
        str(PYTHON),
        str(AUDIT_TOOL),
        "--board-port",
        args.board_port,
        "--board-baud",
        str(args.board_baud),
        "--board-user",
        args.board_user,
        "--board-password",
        args.board_password,
        "--board-timeout",
        str(args.board_timeout),
        "--vm-host",
        args.vm_host,
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
        "--vm-timeout",
        str(args.vm_timeout),
        "--json",
        "--no-report",
    ]
    result = run(command, timeout=args.board_timeout + args.vm_timeout + 120)
    return result, extract_json_object(result.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-live-audit", action="store_true", help="Use only saved artifacts; do not query board/VM.")
    parser.add_argument("--physical-verified-note", default="", help="User-provided note proving real power-cycle or USB replug validation.")
    parser.add_argument("--board-port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-timeout", type=float, default=120.0)
    parser.add_argument("--vm-host", default="192.168.137.100")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    acceptance_path, acceptance = latest_json(ACCEPTANCE_ROOT, "acceptance_*.json")
    post_path, post_replug = latest_json(POST_REPLUG_ROOT, "post_replug_*.json")
    live_result, live_audit = run_live_audit(args)

    requirements: list[dict[str, str]] = []

    vm_analysis_source_ok = source_contains(
        ROOT / "tools" / "vm_print_latest_stm32_analysis.py",
        "VM_TOOL",
        "vm_ssh_run.py",
        "python3 -c",
    )
    add(
        requirements,
        "vm_latest_stm32_analysis_over_ssh",
        "PASS" if vm_analysis_source_ok else "FAIL",
        "tools/vm_print_latest_stm32_analysis.py uses tools/vm_ssh_run.py and remote python3"
        if vm_analysis_source_ok else "SSH-based latest analysis reader not proven",
    )

    receive_only_source_ok = source_contains(
        ROOT / "tools" / "board_stm32_usb_serial_udp_bridge.py",
        "receive-only",
        "never writes bytes to the STM32",
        "os.read",
    )
    add(
        requirements,
        "stm32_board_bridge_receive_only",
        "PASS" if receive_only_source_ok else "FAIL",
        "board bridge reads serial and forwards UDP; source declares no STM32 writes"
        if receive_only_source_ok else "receive-only bridge source invariant missing",
    )

    add(
        requirements,
        "latest_post_replug_validation",
        "PASS" if post_replug and all_report_checks_pass(post_replug) else "FAIL",
        str(post_path) if post_path else "missing post_replug report",
    )

    add(
        requirements,
        "latest_full_acceptance",
        "PASS" if acceptance and all_report_checks_pass(acceptance) else "FAIL",
        str(acceptance_path) if acceptance_path else "missing acceptance report",
    )

    final_audit = live_audit or (acceptance or {}).get("final_audit")
    add(
        requirements,
        "current_live_audit_no_unexpected_failures",
        "PASS" if audit_no_failures_except_expected(final_audit) else "FAIL",
        "live audit" if live_audit else "latest acceptance final_audit",
    )

    board_driver = (final_audit or {}).get("board_driver_status") or {}
    driver_mode = board_driver.get("driver_mode")
    add(
        requirements,
        "driver_state_explicitly_documented",
        "PASS" if driver_mode in {"generic_fallback", "formal_ch341"} else "FAIL",
        f"driver_mode={driver_mode or 'unknown'}",
    )
    add(
        requirements,
        "formal_ch341_gap_recorded",
        "WARN" if driver_mode == "generic_fallback" else "PASS",
        "Current usable route is usbserial_generic fallback; formal CH341 still needs matching 4.19.90 inputs"
        if driver_mode == "generic_fallback" else "formal_ch341 active",
    )

    one_click_tools_ok = all(
        (ROOT / item).exists()
        for item in [
            "tools/stm32_link_manager.py",
            "tools/sensor_suite_manager.py",
            "tools/post_replug_validation.py",
            "tools/parking_link_acceptance.py",
            "tools/parking_link_audit.py",
        ]
    )
    add(
        requirements,
        "one_click_operations_available",
        "PASS" if one_click_tools_ok else "FAIL",
        "stm32_link_manager, sensor_suite_manager, post_replug_validation, acceptance, audit present",
    )

    sensor = ((acceptance or {}).get("final_audit") or {}).get("vm_summary", {}).get("latest_sensor_session") or {}
    stm32 = ((acceptance or {}).get("final_audit") or {}).get("vm_summary", {}).get("latest_stm32_session") or {}
    add(
        requirements,
        "camera_dtof_stm32_records_complete",
        "PASS" if sensor.get("camera_frames", 0) > 0 and sensor.get("dtof_metadata_lines", 0) > 0 and stm32.get("raw_bytes", 0) > 0 else "FAIL",
        f"camera_frames={sensor.get('camera_frames')}; dtof_metadata={sensor.get('dtof_metadata_lines')}; stm32_raw_bytes={stm32.get('raw_bytes')}",
    )

    no_forbidden = True
    for audit in (final_audit, (acceptance or {}).get("final_audit"), (post_replug or {}).get("final_audit")):
        if not audit:
            continue
        checks = audit.get("checks", [])
        for name in ("board_no_forbidden_control_processes", "vm_no_forbidden_control_processes"):
            item = check_item(checks, name)
            no_forbidden = no_forbidden and bool(item and item.get("status") == "PASS")
    add(
        requirements,
        "no_forbidden_control_processes_observed",
        "PASS" if no_forbidden else "FAIL",
        "audit/acceptance/post-replug reports show no forbidden control processes",
    )

    boot_helpers_ok = all(
        source_contains(ROOT / "docs" / "perception_link_runbook.md", token)
        for token in ("/etc/init.d/S81wired137", "/etc/init.d/S99parkinglink")
    )
    add(
        requirements,
        "migration_and_boot_helpers_documented",
        "PASS" if boot_helpers_ok else "FAIL",
        "runbook documents S81wired137 and S99parkinglink" if boot_helpers_ok else "boot helper docs missing",
    )

    physical_note = args.physical_verified_note.strip()
    add(
        requirements,
        "physical_power_or_usb_replug_validation",
        "PASS" if physical_note else "WARN",
        physical_note if physical_note else "soft reboot is verified; real power-cycle or USB replug still needs user-side action",
    )

    report: dict[str, Any] = {
        "time_local_epoch": time.time(),
        "overall": "FAIL",
        "acceptance_report": str(acceptance_path) if acceptance_path else None,
        "post_replug_report": str(post_path) if post_path else None,
        "live_audit_exit_code": live_result.returncode if live_result else None,
        "live_audit": live_audit,
        "requirements": requirements,
    }
    statuses = [item["status"] for item in requirements]
    if any(status == "FAIL" for status in statuses):
        report["overall"] = "FAIL"
    elif any(status == "WARN" for status in statuses):
        report["overall"] = "WARN"
    else:
        report["overall"] = "PASS"

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"status_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"PARKING_GOAL_STATUS {report['overall']}")
    for item in requirements:
        print(f"{item['status']:4} {item['name']} - {item['evidence']}")
    print(f"GOAL_STATUS_REPORT {path}")
    return 0 if report["overall"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
