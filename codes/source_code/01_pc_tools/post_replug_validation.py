#!/usr/bin/env python3
"""Post-replug validation for the receive-only parking board links.

This script is meant to be run after a board power cycle, USB serial replug, or
host/VM migration. It validates that the board still identifies the STM32 USB
serial adapter, that the VM can receive STM32 data through ROS2, and that no
forbidden control process is running.

It does not send bytes to STM32 and does not start MCU, CAN, motor, steering,
brake, throttle, or actuator code.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
AUDIT_TOOL = ROOT / "tools" / "parking_link_audit.py"
STM32_MANAGER = ROOT / "tools" / "stm32_link_manager.py"
LATEST_ANALYSIS_TOOL = ROOT / "tools" / "vm_print_latest_stm32_analysis.py"
FULL_ACCEPTANCE_TOOL = ROOT / "tools" / "parking_link_acceptance.py"
REPORT_ROOT = ROOT / "artifacts" / "post_replug_validation"


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


def trim_output(text: str, limit: int = 50000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...[trimmed]...\n" + text[-limit // 2 :]


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


def check_by_name(audit: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not audit:
        return None
    for item in audit.get("checks", []):
        if item.get("name") == name:
            return item
    return None


def audit_cmd(args: argparse.Namespace) -> list[str]:
    return [
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
        "--vm-record-root",
        args.vm_record_root,
        "--json",
        "--no-report",
    ]


def stm32_check_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(STM32_MANAGER),
        "check",
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
        "--udp-port",
        str(args.stm32_udp_port),
        "--stm32-baud",
        str(args.stm32_baud),
        "--check-vm-duration-sec",
        str(args.stm32_vm_duration_sec),
        "--check-board-duration-sec",
        str(args.stm32_board_duration_sec),
        "--check-receiver-warmup-sec",
        str(args.stm32_receiver_warmup_sec),
        "--allow-risk",
    ]


def latest_analysis_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(LATEST_ANALYSIS_TOOL),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--timeout",
        str(args.vm_timeout),
        "--record-root",
        "/home/ebaina/parking_sensor_records/stm32_ros_live",
        "--record-root",
        "/home/ebaina/parking_sensor_records/stm32_ros_check",
        "--record-root",
        args.vm_record_root,
    ]


def full_acceptance_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(FULL_ACCEPTANCE_TOOL),
        "--run-sec",
        str(args.full_sensor_run_sec),
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
        "--vm-record-root",
        args.vm_record_root,
    ]


def run_step(report: dict[str, Any], name: str, parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    print(f"=== {name} ===", flush=True)
    result = run(parts, timeout=timeout)
    print(trim_output(result.stdout), end="", flush=True)
    print(f"\n{name}_EXIT_CODE {result.returncode}", flush=True)
    report["steps"][name] = {
        "command": subprocess.list2cmdline(parts),
        "returncode": result.returncode,
        "stdout": trim_output(result.stdout),
    }
    return result


def add_check(checks: list[dict[str, str]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})


def bytes_from_analysis_output(output: str) -> int:
    match = re.search(r'"bytes"\s*:\s*(\d+)', output)
    return int(match.group(1)) if match else 0


def build_checks(args: argparse.Namespace, report: dict[str, Any]) -> None:
    checks: list[dict[str, str]] = []
    initial_audit = report.get("initial_audit")
    final_audit = report.get("final_audit")
    stm32_step = report["steps"].get("stm32_check", {})
    analysis_step = report["steps"].get("latest_analysis", {})
    full_step = report["steps"].get("full_sensor_acceptance")

    for audit_name, audit in (("initial", initial_audit), ("final", final_audit)):
        add_check(checks, f"{audit_name}_audit_json", isinstance(audit, dict), "parsed" if isinstance(audit, dict) else "missing")
        for check_name in ("board_console", "vm_ssh", "board_wired_192_168_137_2", "board_usb_serial_ready"):
            item = check_by_name(audit, check_name)
            add_check(
                checks,
                f"{audit_name}_{check_name}",
                bool(item and item.get("status") == "PASS"),
                json.dumps(item, ensure_ascii=False) if item else "missing",
            )

    add_check(
        checks,
        "stm32_check_passed",
        stm32_step.get("returncode") == 0 and "STM32_END_TO_END_CHECK PASS" in stm32_step.get("stdout", ""),
        f"exit_code={stm32_step.get('returncode')}",
    )
    analysis_bytes = bytes_from_analysis_output(analysis_step.get("stdout", ""))
    add_check(
        checks,
        "latest_analysis_has_bytes",
        analysis_step.get("returncode") == 0 and analysis_bytes >= args.min_stm32_bytes,
        f"bytes={analysis_bytes} >= {args.min_stm32_bytes}",
    )

    final_checks = final_audit.get("checks", []) if isinstance(final_audit, dict) else []
    final_failures = [item for item in final_checks if item.get("status") == "FAIL"]
    final_warnings = [item for item in final_checks if item.get("status") == "WARN"]
    unexpected_warnings = [item for item in final_warnings if item.get("name") not in EXPECTED_WARNINGS]
    add_check(checks, "final_audit_has_no_failures", not final_failures, json.dumps(final_failures, ensure_ascii=False))
    add_check(checks, "only_expected_warnings", not unexpected_warnings, json.dumps(unexpected_warnings, ensure_ascii=False))

    for check_name in ("board_no_residual_sensor_processes", "vm_no_residual_sensor_processes"):
        item = check_by_name(final_audit, check_name)
        add_check(
            checks,
            check_name,
            bool(item and item.get("status") == "PASS"),
            json.dumps(item, ensure_ascii=False) if item else "missing",
        )
    for check_name in ("board_no_forbidden_control_processes", "vm_no_forbidden_control_processes"):
        item = check_by_name(final_audit, check_name)
        add_check(
            checks,
            check_name,
            bool(item and item.get("status") == "PASS"),
            json.dumps(item, ensure_ascii=False) if item else "missing",
        )

    if full_step is not None:
        add_check(
            checks,
            "full_sensor_acceptance_passed",
            full_step.get("returncode") == 0 and "PARKING_LINK_ACCEPTANCE" in full_step.get("stdout", ""),
            f"exit_code={full_step.get('returncode')}",
        )

    report["checks"] = checks
    if any(item["status"] == "FAIL" for item in checks):
        report["overall"] = "FAIL"
    elif final_warnings:
        report["overall"] = "WARN"
    else:
        report["overall"] = "PASS"


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"post_replug_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-timeout", type=float, default=120.0)
    parser.add_argument("--vm-host", default="192.168.137.100")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--vm-record-root", default="/home/ebaina/parking_sensor_records/sensor_suite_live")
    parser.add_argument("--stm32-udp-port", type=int, default=24680)
    parser.add_argument("--stm32-baud", type=int, default=9600)
    parser.add_argument("--stm32-vm-duration-sec", type=int, default=35)
    parser.add_argument("--stm32-board-duration-sec", type=float, default=25.0)
    parser.add_argument("--stm32-receiver-warmup-sec", type=float, default=6.0)
    parser.add_argument("--min-stm32-bytes", type=int, default=1024)
    parser.add_argument("--full-sensor", action="store_true", help="Also run camera+dToF+STM32 full acceptance.")
    parser.add_argument("--full-sensor-run-sec", type=float, default=35.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "time_local_epoch": time.time(),
        "scope": "post_replug_receive_only_validation",
        "safety": {
            "starts_mcu_can_actuator": False,
            "writes_to_stm32": False,
            "default_camera_dtof_baseline_untouched": not args.full_sensor,
        },
        "steps": {},
        "initial_audit": None,
        "final_audit": None,
        "checks": [],
        "overall": "FAIL",
    }

    try:
        initial = run_step(report, "initial_audit", audit_cmd(args), timeout=args.board_timeout + args.vm_timeout + 120)
        report["initial_audit"] = extract_json_object(initial.stdout)
        run_step(
            report,
            "stm32_check",
            stm32_check_cmd(args),
            timeout=args.stm32_vm_duration_sec + args.stm32_board_duration_sec + args.board_timeout + args.vm_timeout + 240,
        )
        run_step(report, "latest_analysis", latest_analysis_cmd(args), timeout=args.vm_timeout)
        if args.full_sensor:
            run_step(
                report,
                "full_sensor_acceptance",
                full_acceptance_cmd(args),
                timeout=args.full_sensor_run_sec + args.board_timeout + args.vm_timeout + 360,
            )
    except subprocess.TimeoutExpired as exc:
        report["exception"] = f"COMMAND_TIMEOUT {exc}"
    finally:
        final = run_step(report, "final_audit", audit_cmd(args), timeout=args.board_timeout + args.vm_timeout + 120)
        report["final_audit"] = extract_json_object(final.stdout)

    build_checks(args, report)
    path = write_report(report)
    print(f"POST_REPLUG_VALIDATION {report['overall']}")
    for check in report["checks"]:
        print(f"{check['status']:4} {check['name']} - {check['detail']}")
    print(f"POST_REPLUG_REPORT {path}")
    return 0 if report["overall"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
