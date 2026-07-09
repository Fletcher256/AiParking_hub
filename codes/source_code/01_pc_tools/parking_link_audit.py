#!/usr/bin/env python3
"""Read-only audit for the parking perception and communication link.

This tool does not start camera, dToF, STM32, MCU, CAN, motor, steering,
brake, throttle, or actuator processes. It checks the current board and VM
state plus the latest recorded evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
BOARD_TOOL = ROOT / "tools" / "board_serial.py"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
CH341_CHECK = ROOT / "tools" / "ch341_readiness_check.py"
REPORT_ROOT = ROOT / "artifacts" / "parking_link_audit"


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run(parts: list[str], timeout: float, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        parts,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@dataclass
class Check:
    name: str
    status: str
    detail: str


def status_from(condition: bool, ok: str = "PASS", bad: str = "FAIL") -> str:
    return ok if condition else bad


def parse_json_lines(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def board_audit_command() -> str:
    body = r"""
echo BOARD_AUDIT_BEGIN
uname -a
echo BOARD_NET_137
cat /proc/net/fib_trie | grep 192.168.137 || true
echo BOARD_USB_STATUS
cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true
echo BOARD_TTYS
for d in /dev/ttyCH341USB* /dev/ttyUSB* /dev/ttyACM*; do
  [ -e "$d" ] && ls -l "$d"
done
echo BOARD_USB_SERIAL_DRIVER
for d in /sys/bus/usb-serial/devices/*; do
  [ -e "$d" ] || continue
  echo "$(basename "$d") $(readlink -f "$d/driver" 2>/dev/null || true)"
done
echo BOARD_HELPERS
[ -x /etc/udev/ch341-autobind.sh ] && echo CH341_AUTOBIND_SH yes || echo CH341_AUTOBIND_SH no
[ -f /etc/udev/rules.d/98-ch341-autobind.rules ] && echo CH341_UDEV_RULE yes || echo CH341_UDEV_RULE no
[ -x /etc/init.d/S81wired137 ] && echo WIRED137_INIT yes || echo WIRED137_INIT no
[ -x /etc/init.d/S99parkinglink ] && echo PARKING_LINK_INIT yes || echo PARKING_LINK_INIT no
[ -x /opt/sample/official_dtof/sample_dtof_rtsp ] && echo OFFICIAL_CASE7_BIN yes || echo OFFICIAL_CASE7_BIN no
echo BOARD_RESIDUAL_SENSOR_PROCESSES
residual_sensor=$(ps | grep -E 'sample_dtof_rtsp|board_stm32_usb_serial_udp_bridge' | grep -v grep || true)
if [ -n "$residual_sensor" ]; then
  echo BOARD_RESIDUAL_SENSOR_COUNT "$(printf '%s\n' "$residual_sensor" | sed '/^$/d' | wc -l)"
  printf '%s\n' "$residual_sensor"
else
  echo BOARD_RESIDUAL_SENSOR_COUNT 0
fi
echo BOARD_FORBIDDEN_CONTROL_PROCESSES
forbidden_control=$(ps | grep -E 'parking_mcu_bridge|CAN|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true)
if [ -n "$forbidden_control" ]; then
  echo BOARD_FORBIDDEN_CONTROL_COUNT "$(printf '%s\n' "$forbidden_control" | sed '/^$/d' | wc -l)"
  printf '%s\n' "$forbidden_control"
else
  echo BOARD_FORBIDDEN_CONTROL_COUNT 0
fi
echo BOARD_AUDIT_END
"""
    return "sh -lc " + sh_quote(body)


def vm_audit_code(record_root: str) -> str:
    return f"""from pathlib import Path
import json
import subprocess

record_root = Path({record_root!r})
sensor_sessions = []
stm32_sessions = []
for root in [
    record_root,
    Path('/home/ebaina/parking_sensor_records/stm32_ros_live'),
    Path('/home/ebaina/parking_sensor_records/stm32_ros_check'),
]:
    sensor_sessions.extend(root.glob('run_*/session_*'))
    sensor_sessions.extend(root.glob('session_*'))
    stm32_sessions.extend(root.glob('run_*/stm32_session_*'))
    stm32_sessions.extend(root.glob('stm32_session_*'))

def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0

sensor_sessions = sorted({{p for p in sensor_sessions if p.is_dir()}}, key=mtime)
stm32_sessions = sorted({{p for p in stm32_sessions if p.is_dir()}}, key=mtime)
summary = {{
    'hostname': subprocess.getoutput('hostname').strip(),
    'uname': subprocess.getoutput('uname -a').strip(),
    'ros2': {{
        'humble_setup': Path('/opt/ros/humble/setup.bash').exists(),
        'workspace_setup': Path.home().joinpath('parking_ws/install/setup.bash').exists(),
        'package_dir': Path.home().joinpath('parking_ws/src/parking_bridge').exists(),
    }},
    'latest_sensor_session': None,
    'latest_stm32_session': None,
    'residual_sensor_processes': subprocess.getoutput(\"ps -ef | grep -E 'parking_sensor_suite|sensor_suite_node|parking_stm32_udp_bridge|stm32_udp_bridge|ros2 launch parking_bridge parking' | grep -v grep || true\").splitlines(),
    'forbidden_control_processes': subprocess.getoutput(\"ps -ef | grep -E 'parking_mcu_bridge|CAN|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true\").splitlines(),
}}
if sensor_sessions:
    s = sensor_sessions[-1]
    def count_lines(name):
        p = s / name
        return len(p.read_text(errors='replace').splitlines()) if p.exists() else 0
    health_rows = []
    hp = s / 'health.jsonl'
    if hp.exists():
        for line in hp.read_text(errors='replace').splitlines():
            if line.strip():
                try:
                    health_rows.append(json.loads(line))
                except Exception:
                    pass
    latest = {{
        'path': str(s),
        'camera_frames': len(list((s / 'camera_frames').glob('*.jpg'))),
        'dtof_metadata_lines': count_lines('dtof_metadata.jsonl'),
        'sync_lines': count_lines('sync_pairs.jsonl'),
        'health_lines': count_lines('health.jsonl'),
        'any_both_ok': any(row.get('camera', {{}}).get('ok') and row.get('dtof', {{}}).get('ok') for row in health_rows),
    }}
    if health_rows:
        latest['last_health'] = health_rows[-1]
    summary['latest_sensor_session'] = latest
if stm32_sessions:
    s = stm32_sessions[-1]
    raw = s / 'stm32_serial_raw.bin'
    ap = s / 'stm32_protocol_analysis.json'
    latest = {{
        'path': str(s),
        'raw_bytes': raw.stat().st_size if raw.exists() else 0,
        'analysis': None,
    }}
    if ap.exists():
        latest['analysis'] = json.loads(ap.read_text(errors='replace'))
    summary['latest_stm32_session'] = latest
print(json.dumps(summary, ensure_ascii=False, indent=2))
"""


def vm_audit_command(record_root: str) -> str:
    return "python3 -c " + sh_quote(vm_audit_code(record_root))


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


def run_board_audit(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    return run(
        [
            str(PYTHON),
            str(BOARD_TOOL),
            "--port",
            args.board_port,
            "--baud",
            str(args.board_baud),
            "--login-user",
            args.board_user,
            "--login-password",
            args.board_password,
            "--timeout",
            str(args.board_timeout),
            "--allow-risk",
            "run",
            "--allow-risk",
            board_audit_command(),
        ],
        timeout=args.board_timeout + 20,
    )


def run_vm_audit(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    return run(
        [
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
            "run",
            vm_audit_command(args.vm_record_root),
        ],
        timeout=args.vm_timeout + 20,
    )


def run_ch341_audit(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    return run(
        [
            str(PYTHON),
            str(CH341_CHECK),
            "--host",
            args.vm_host,
            "--user",
            args.vm_user,
            "--password",
            args.vm_password,
            "--timeout",
            str(args.vm_timeout),
            "--json",
        ],
        timeout=args.vm_timeout + 40,
    )


def evaluate(board: subprocess.CompletedProcess[str], vm: subprocess.CompletedProcess[str], ch341: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    checks: list[Check] = []
    board_output = board.stdout
    vm_output = vm.stdout
    ch341_output = ch341.stdout

    checks.append(Check("board_console", status_from(board.returncode == 0), f"exit_code={board.returncode}"))
    checks.append(Check("vm_ssh", status_from(vm.returncode == 0), f"exit_code={vm.returncode}"))

    board_json_rows = parse_json_lines(board_output)
    driver_status = next((row for row in reversed(board_json_rows) if row.get("status") == "serial_ready"), None)
    checks.append(
        Check(
            "board_wired_192_168_137_2",
            status_from("192.168.137.2" in board_output),
            "board fib_trie contains 192.168.137.2" if "192.168.137.2" in board_output else "missing 192.168.137.2 in board fib_trie",
        )
    )
    checks.append(
        Check(
            "board_usb_serial_ready",
            status_from(bool(driver_status)),
            json.dumps(driver_status, ensure_ascii=False) if driver_status else "missing /tmp/stm32_usb_serial_driver_status.json serial_ready",
        )
    )
    mode = (driver_status or {}).get("driver_mode")
    checks.append(
        Check(
            "board_ch341_driver_mode",
            "PASS" if mode == "formal_ch341" else "WARN",
            f"driver_mode={mode or 'unknown'}",
        )
    )
    for name, token in (
        ("board_ch341_autobind_installed", "CH341_AUTOBIND_SH yes"),
        ("board_ch341_udev_rule_installed", "CH341_UDEV_RULE yes"),
        ("board_wired137_init_installed", "WIRED137_INIT yes"),
        ("board_parking_link_init_installed", "PARKING_LINK_INIT yes"),
        ("board_official_case7_binary", "OFFICIAL_CASE7_BIN yes"),
    ):
        checks.append(Check(name, status_from(token in board_output), token if token in board_output else "missing"))

    residual_count = extract_count(board_output, "BOARD_RESIDUAL_SENSOR_COUNT")
    forbidden_count = extract_count(board_output, "BOARD_FORBIDDEN_CONTROL_COUNT")
    board_residual = section_lines(board_output, "BOARD_RESIDUAL_SENSOR_PROCESSES", "BOARD_FORBIDDEN_CONTROL_PROCESSES")
    board_forbidden = section_lines(board_output, "BOARD_FORBIDDEN_CONTROL_PROCESSES", "BOARD_AUDIT_END")
    checks.append(
        Check(
            "board_no_residual_sensor_processes",
            status_from(residual_count == 0),
            f"count={residual_count}" if residual_count == 0 else f"count={residual_count}; lines={clean_process_lines(board_residual)!r}",
        )
    )
    checks.append(
        Check(
            "board_no_forbidden_control_processes",
            status_from(forbidden_count == 0),
            f"count={forbidden_count}" if forbidden_count == 0 else f"count={forbidden_count}; lines={clean_process_lines(board_forbidden)!r}",
        )
    )

    vm_summary = extract_json_object(vm_output) or {}
    ros2 = vm_summary.get("ros2", {}) if isinstance(vm_summary.get("ros2"), dict) else {}
    checks.append(
        Check(
            "vm_ros2_workspace_ready",
            status_from(bool(ros2.get("humble_setup") and ros2.get("workspace_setup") and ros2.get("package_dir"))),
            json.dumps(ros2, ensure_ascii=False),
        )
    )
    latest_sensor = vm_summary.get("latest_sensor_session") if isinstance(vm_summary.get("latest_sensor_session"), dict) else None
    sensor_ok = bool(
        latest_sensor
        and latest_sensor.get("camera_frames", 0) > 0
        and latest_sensor.get("dtof_metadata_lines", 0) > 0
        and latest_sensor.get("sync_lines", 0) > 0
        and latest_sensor.get("any_both_ok")
    )
    checks.append(
        Check(
            "vm_latest_camera_dtof_record",
            status_from(sensor_ok),
            json.dumps(latest_sensor, ensure_ascii=False) if latest_sensor else "missing latest sensor session",
        )
    )
    latest_stm32 = vm_summary.get("latest_stm32_session") if isinstance(vm_summary.get("latest_stm32_session"), dict) else None
    analysis = latest_stm32.get("analysis") if isinstance(latest_stm32, dict) else None
    stm32_ok = bool(latest_stm32 and latest_stm32.get("raw_bytes", 0) > 0 and isinstance(analysis, dict))
    checks.append(
        Check(
            "vm_latest_stm32_record",
            status_from(stm32_ok),
            json.dumps(latest_stm32, ensure_ascii=False) if latest_stm32 else "missing latest STM32 session",
        )
    )
    vm_residual = vm_summary.get("residual_sensor_processes", [])
    vm_forbidden = vm_summary.get("forbidden_control_processes", [])
    checks.append(Check("vm_no_residual_sensor_processes", status_from(not vm_residual), repr(vm_residual)))
    checks.append(Check("vm_no_forbidden_control_processes", status_from(not vm_forbidden), repr(vm_forbidden)))

    ch341_summary = extract_json_object(ch341_output) or {}
    assessment = ch341_summary.get("assessment", {}) if isinstance(ch341_summary.get("assessment"), dict) else {}
    checks.append(
        Check(
            "formal_ch341_route",
            "PASS" if assessment.get("can_build_or_install_now") else "WARN",
            json.dumps(assessment, ensure_ascii=False) if assessment else "missing CH341 assessment",
        )
    )

    overall = "PASS"
    if any(check.status == "FAIL" for check in checks):
        overall = "FAIL"
    elif any(check.status == "WARN" for check in checks):
        overall = "WARN"

    return {
        "time_local_epoch": time.time(),
        "overall": overall,
        "checks": [check.__dict__ for check in checks],
        "board_driver_status": driver_status,
        "vm_summary": vm_summary,
        "ch341_summary": ch341_summary,
        "raw_exit_codes": {
            "board": board.returncode,
            "vm": vm.returncode,
            "ch341": ch341.returncode,
        },
    }


def section_lines(output: str, begin: str, end: str) -> list[str]:
    lines = output.splitlines()
    selected: list[str] = []
    inside = False
    for line in lines:
        if begin in line:
            inside = True
            continue
        if inside and end in line:
            break
        if inside:
            selected.append(line)
    return selected


def extract_count(output: str, key: str) -> int | None:
    matches = re.findall(rf"{re.escape(key)}\s+(\d+)", output)
    if not matches:
        return None
    return int(matches[-1])


def clean_process_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if "grep -E" in text or "printf '__CODEX_DONE" in text or text.startswith("~ #"):
            continue
        if text.startswith(">"):
            continue
        cleaned.append(text)
    return cleaned


def print_report(report: dict[str, Any]) -> None:
    print(f"PARKING_LINK_AUDIT {report['overall']}")
    for check in report["checks"]:
        print(f"{check['status']:4} {check['name']} - {check['detail']}")
    vm_summary = report.get("vm_summary") or {}
    sensor = vm_summary.get("latest_sensor_session") if isinstance(vm_summary, dict) else None
    stm32 = vm_summary.get("latest_stm32_session") if isinstance(vm_summary, dict) else None
    if sensor:
        print(f"LATEST_SENSOR_SESSION {sensor.get('path')}")
    if stm32:
        print(f"LATEST_STM32_SESSION {stm32.get('path')}")


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = REPORT_ROOT / f"audit_{stamp}.json"
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
    parser.add_argument("--vm-timeout", type=float, default=60.0)
    parser.add_argument("--vm-record-root", default="/home/ebaina/parking_sensor_records/sensor_suite_live")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--no-report", action="store_true", help="Do not write artifacts/parking_link_audit/audit_*.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    board = run_board_audit(args)
    vm = run_vm_audit(args)
    ch341 = run_ch341_audit(args)
    report = evaluate(board, vm, ch341)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    if not args.no_report:
        path = write_report(report)
        print(f"AUDIT_REPORT {path}")
    return 0 if report["overall"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
