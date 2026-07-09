#!/usr/bin/env python3
"""End-to-end acceptance run for the receive-only parking sensor link.

This script starts only perception and communication components:

- official board camera+dToF case7 sample
- board receive-only STM32 USB serial UDP forwarder
- VM ROS2 parking_bridge receivers

It does not start MCU, CAN, motor, steering, brake, throttle, or actuator code,
and it never writes bytes to STM32.
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
SENSOR_MANAGER = ROOT / "tools" / "sensor_suite_manager.py"
AUDIT_TOOL = ROOT / "tools" / "parking_link_audit.py"
REPORT_ROOT = ROOT / "artifacts" / "parking_link_acceptance"


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


def sensor_cmd(action: str, args: argparse.Namespace, extra: list[str] | None = None) -> list[str]:
    parts = [
        str(PYTHON),
        str(SENSOR_MANAGER),
        action,
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
    if action in {"deploy", "start", "stop"}:
        parts.append("--allow-risk")
    if extra:
        parts.extend(extra)
    return parts


def audit_cmd(args: argparse.Namespace, *, json_output: bool = True, no_report: bool = True) -> list[str]:
    parts = [
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
    ]
    if json_output:
        parts.append("--json")
    if no_report:
        parts.append("--no-report")
    return parts


def extract_audit_json(output: str) -> dict[str, Any] | None:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_record_dir(output: str) -> str | None:
    matches = re.findall(r"VM_RECORD_DIR\s+(\S+)", output)
    return matches[-1] if matches else None


def check_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    start_rc = report["steps"]["start"]["returncode"]
    health_rc = report["steps"]["health"]["returncode"]
    stop_rc = report["steps"]["stop"]["returncode"]
    record_dir = report.get("record_dir")
    final_audit = report.get("final_audit") or {}
    vm_summary = final_audit.get("vm_summary") if isinstance(final_audit, dict) else {}
    sensor = vm_summary.get("latest_sensor_session") if isinstance(vm_summary, dict) else None
    stm32 = vm_summary.get("latest_stm32_session") if isinstance(vm_summary, dict) else None

    add("start_exit_code", start_rc == 0, f"exit_code={start_rc}")
    add("health_exit_code", health_rc == 0, f"exit_code={health_rc}")
    add("stop_exit_code", stop_rc == 0, f"exit_code={stop_rc}")
    add("record_dir_detected", bool(record_dir), str(record_dir))

    sensor_path = sensor.get("path", "") if isinstance(sensor, dict) else ""
    stm32_path = stm32.get("path", "") if isinstance(stm32, dict) else ""
    add("sensor_session_is_new_run", bool(record_dir and sensor_path.startswith(record_dir + "/")), sensor_path)
    add("stm32_session_is_new_run", bool(record_dir and stm32_path.startswith(record_dir + "/")), stm32_path)

    camera_frames = int(sensor.get("camera_frames", 0)) if isinstance(sensor, dict) else 0
    dtof_lines = int(sensor.get("dtof_metadata_lines", 0)) if isinstance(sensor, dict) else 0
    sync_lines = int(sensor.get("sync_lines", 0)) if isinstance(sensor, dict) else 0
    any_both_ok = bool(sensor.get("any_both_ok")) if isinstance(sensor, dict) else False
    stm32_bytes = int(stm32.get("raw_bytes", 0)) if isinstance(stm32, dict) else 0
    analysis = stm32.get("analysis") if isinstance(stm32, dict) else None

    add("camera_frames_recorded", camera_frames >= args.min_camera_frames, f"{camera_frames} >= {args.min_camera_frames}")
    add("dtof_packets_recorded", dtof_lines >= args.min_dtof_packets, f"{dtof_lines} >= {args.min_dtof_packets}")
    add("sync_pairs_recorded", sync_lines >= args.min_sync_pairs, f"{sync_lines} >= {args.min_sync_pairs}")
    add("camera_and_dtof_were_simultaneously_healthy", any_both_ok, str(any_both_ok))
    add("stm32_bytes_recorded", stm32_bytes >= args.min_stm32_bytes, f"{stm32_bytes} >= {args.min_stm32_bytes}")
    add("stm32_protocol_analysis_written", isinstance(analysis, dict), "analysis present" if isinstance(analysis, dict) else "missing")

    audit_checks = final_audit.get("checks", []) if isinstance(final_audit, dict) else []
    audit_failures = [item for item in audit_checks if item.get("status") == "FAIL"]
    forbidden_failures = [
        item for item in audit_failures
        if "forbidden_control_processes" in item.get("name", "")
    ]
    add("final_audit_has_no_failures", not audit_failures, json.dumps(audit_failures, ensure_ascii=False))
    add("no_forbidden_control_processes", not forbidden_failures, json.dumps(forbidden_failures, ensure_ascii=False))

    warnings = [item for item in audit_checks if item.get("status") == "WARN"]
    unexpected_warnings = [
        item for item in warnings
        if item.get("name") not in {"board_ch341_driver_mode", "formal_ch341_route"}
    ]
    add("only_expected_warnings", not unexpected_warnings, json.dumps(unexpected_warnings, ensure_ascii=False))

    report["checks"] = checks
    if any(item["status"] == "FAIL" for item in checks):
        report["overall"] = "FAIL"
    elif warnings:
        report["overall"] = "WARN"
    else:
        report["overall"] = "PASS"


def trim_output(text: str, limit: int = 20000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...[trimmed]...\n" + text[-limit // 2 :]


def run_step(report: dict[str, Any], name: str, parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    print(f"=== {name} ===", flush=True)
    result = run(parts, timeout=timeout)
    print(trim_output(result.stdout), end="", flush=True)
    print(f"\n{name}_EXIT_CODE {result.returncode}", flush=True)
    report["steps"][name] = {
        "command": subprocess.list2cmdline(parts),
        "returncode": result.returncode,
        "stdout": trim_output(result.stdout, 50000),
    }
    return result


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = REPORT_ROOT / f"acceptance_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true", help="Deploy ROS2 package before acceptance run.")
    parser.add_argument("--run-sec", type=float, default=45.0, help="Seconds to leave the full receive-only link running before health/stop.")
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
    parser.add_argument("--min-camera-frames", type=int, default=5)
    parser.add_argument("--min-dtof-packets", type=int, default=50)
    parser.add_argument("--min-sync-pairs", type=int, default=1)
    parser.add_argument("--min-stm32-bytes", type=int, default=1024)
    parser.add_argument("--no-clean-start", action="store_true", help="Do not run an initial stop before starting.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report: dict[str, Any] = {
        "time_local_epoch": time.time(),
        "objective_scope": "receive_only_camera_dtof_stm32_vm_ros2",
        "safety": {
            "starts_mcu_can_actuator": False,
            "writes_to_stm32": False,
            "uses_official_dtof_baseline": "/opt/sample/official_dtof/sample_dtof_rtsp case7",
        },
        "steps": {},
        "record_dir": None,
        "initial_audit": None,
        "final_audit": None,
        "overall": "FAIL",
    }
    stop_result: subprocess.CompletedProcess[str] | None = None
    try:
        if args.deploy:
            deploy = run_step(report, "deploy", sensor_cmd("deploy", args), timeout=360.0)
            if deploy.returncode != 0:
                raise RuntimeError("deploy failed")

        if not args.no_clean_start:
            run_step(report, "pre_stop", sensor_cmd("stop", args), timeout=args.board_timeout + args.vm_timeout + 60)

        initial = run_step(report, "initial_audit", audit_cmd(args), timeout=args.board_timeout + args.vm_timeout + 120)
        report["initial_audit"] = extract_audit_json(initial.stdout)

        start = run_step(report, "start", sensor_cmd("start", args), timeout=args.board_timeout + args.vm_timeout + 180)
        report["record_dir"] = extract_record_dir(start.stdout)
        if start.returncode != 0:
            raise RuntimeError("start failed")

        print(f"=== collect_for_{args.run_sec:.1f}s ===", flush=True)
        time.sleep(max(0.0, args.run_sec))

        run_step(report, "health", sensor_cmd("health", args), timeout=args.board_timeout + args.vm_timeout + 120)
    except Exception as exc:
        report["exception"] = repr(exc)
    finally:
        stop_result = run_step(report, "stop", sensor_cmd("stop", args), timeout=args.board_timeout + args.vm_timeout + 120)

    latest = run_step(report, "latest_session", sensor_cmd("latest-session", args), timeout=args.board_timeout + args.vm_timeout + 120)
    final = run_step(report, "final_audit", audit_cmd(args), timeout=args.board_timeout + args.vm_timeout + 120)
    report["latest_session_stdout"] = trim_output(latest.stdout, 50000)
    report["final_audit"] = extract_audit_json(final.stdout)
    check_report(args, report)
    path = write_report(report)

    print(f"PARKING_LINK_ACCEPTANCE {report['overall']}")
    for check in report["checks"]:
        print(f"{check['status']:4} {check['name']} - {check['detail']}")
    print(f"ACCEPTANCE_RECORD_DIR {report.get('record_dir')}")
    print(f"ACCEPTANCE_REPORT {path}")
    return 0 if report["overall"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
