#!/usr/bin/env python3
"""Acceptance audit for the current perception-only phase-1/phase-2 goal.

This script deliberately excludes STM32, CAN, actuator, chassis, and driver
work. It verifies only the OS08A20 camera + SS-LD-AS01 dToF receive path,
ROS2 topics, rosbag replay, Foxglove/browser visualization, and safety scan.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
BOARD_TOOL = ROOT / "tools" / "board_auto_ssh.py"
HEALTH_TOOL = ROOT / "tools" / "wifi_sensor_suite_manager.py"
FOXGLOVE_BRIDGE_TOOL = ROOT / "tools" / "foxglove_bridge_control.py"
FOXGLOVE_LITE_TOOL = ROOT / "tools" / "foxglove_lite_control.py"
FOXGLOVE_LITE_PROBE = ROOT / "tools" / "foxglove_lite_probe.py"
FOXGLOVE_LITE_VISUAL = ROOT / "tools" / "foxglove_lite_visual_check.py"
REPORT_ROOT = ROOT / "artifacts" / "perception_phase12_status"

REQUIRED_TOPICS = [
    "/parking/camera/image_jpeg",
    "/parking/camera/image_raw",
    "/parking/dtof/camera_info",
    "/parking/dtof/confidence",
    "/parking/dtof/depth",
    "/parking/dtof/points",
    "/parking/dtof/raw_packet",
    "/parking/sensors/health",
    "/parking/sensors/sync_pair",
]

FORBIDDEN_PROCESS_RE = re.compile(
    r"\b(stm32|can|motor|steer|brake|throttle|pwm|actuator|chassis)\b",
    re.IGNORECASE,
)


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in parts],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def add(checks: list[dict[str, str]], name: str, status: str, evidence: str) -> None:
    checks.append({"name": name, "status": status, "evidence": evidence})


def line_value(output: str, key: str) -> str | None:
    prefix = f"{key} "
    equals_prefix = f"{key}="
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
        if line.startswith(equals_prefix):
            return line[len(equals_prefix):].strip()
    return None


def contains_line(output: str, text: str) -> bool:
    return any(line.strip() == text for line in output.splitlines())


def parse_forwarder_json(output: str) -> dict[str, Any] | None:
    marker = "=== Host UDP Forwarder Health ==="
    idx = output.find(marker)
    if idx < 0:
        return None
    tail = output[idx + len(marker):]
    start = tail.find("{")
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        value, _end = decoder.raw_decode(tail[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def host_wifi_socket_check(board_host: str, expected_local_ip: str, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((board_host, 22), timeout=timeout) as sock:
            local_ip = sock.getsockname()[0]
    except OSError as exc:
        return False, f"connect failed: {exc}"
    if expected_local_ip and local_ip != expected_local_ip:
        return False, f"source_ip={local_ip}, expected={expected_local_ip}"
    return True, f"source_ip={local_ip}, target={board_host}:22"


def windows_interface_alias(ip_addr: str) -> tuple[bool, str]:
    result = run([
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-NetIPAddress -IPAddress '{ip_addr}' -ErrorAction SilentlyContinue).InterfaceAlias",
    ], timeout=10.0)
    alias = result.stdout.strip()
    if result.returncode != 0 or not alias:
        return False, f"interface lookup failed rc={result.returncode}"
    usb_like = any(token in alias.lower() for token in ("apple mobile", "iphone usb", "usb"))
    wireless_like = any(token in alias.lower() for token in ("wlan", "wi-fi", "wifi", "wireless"))
    if usb_like or not wireless_like:
        return False, f"interface_alias={alias}"
    return True, f"interface_alias={alias}"


def upload_and_run_vm_script(script: Path, remote: str, args: argparse.Namespace, timeout: float) -> subprocess.CompletedProcess[str]:
    upload = run([
        PYTHON,
        VM_TOOL,
        "--host",
        args.vm_host,
        "--timeout",
        str(args.vm_timeout),
        "put-text",
        "--allow-risk",
        script,
        remote,
    ], timeout=args.vm_timeout + 20)
    if upload.returncode != 0:
        return upload
    return run([
        PYTHON,
        VM_TOOL,
        "--host",
        args.vm_host,
        "--timeout",
        str(timeout),
        "run",
        f"bash {remote}",
    ], timeout=timeout + 20)


def scan_forbidden_processes(args: argparse.Namespace) -> tuple[bool, str]:
    board = run([
        PYTHON,
        BOARD_TOOL,
        "run",
        "--host",
        args.board_host,
        "--allow-risk",
        "ps",
    ], timeout=args.board_timeout)
    vm = run([
        PYTHON,
        VM_TOOL,
        "--host",
        args.vm_host,
        "--timeout",
        str(args.vm_timeout),
        "run",
        "ps -eo pid,args",
    ], timeout=args.vm_timeout + 10)
    matches: list[str] = []
    for label, result in (("board", board), ("vm", vm)):
        if result.returncode != 0:
            matches.append(f"{label}: ps failed rc={result.returncode}")
            continue
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            if any(token in line for token in ("board_auto_ssh", "vm_ssh_run.py", "perception_phase12_status.py")):
                continue
            if "enable_stm32:=false" in line:
                continue
            if FORBIDDEN_PROCESS_RE.search(line):
                matches.append(f"{label}: {line}")
    return not matches, "; ".join(matches) if matches else "no forbidden process matches"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-host", default="172.20.10.2")
    parser.add_argument("--vm-host", default="192.168.247.129")
    parser.add_argument("--host-forward-ip", default="172.20.10.8")
    parser.add_argument("--ssid", default="iPhone")
    parser.add_argument("--board-timeout", type=float, default=80.0)
    parser.add_argument("--vm-timeout", type=float, default=60.0)
    parser.add_argument("--skip-rosbag", action="store_true")
    parser.add_argument("--skip-visual", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks: list[dict[str, str]] = []
    evidence: dict[str, Any] = {}

    ok, detail = host_wifi_socket_check(args.board_host, args.host_forward_ip, 5.0)
    add(checks, "windows_to_board_wifi_ssh", "PASS" if ok else "FAIL", detail)

    ok, detail = windows_interface_alias(args.host_forward_ip)
    add(checks, "windows_forward_ip_is_wireless", "PASS" if ok else "FAIL", detail)

    health = run([
        PYTHON,
        HEALTH_TOOL,
        "--vm-host",
        args.vm_host,
        "--board-host",
        args.board_host,
        "--host-forward-ip",
        args.host_forward_ip,
        "health",
    ], timeout=args.board_timeout + args.vm_timeout + 30)
    evidence["health_output"] = health.stdout
    add(checks, "wifi_sensor_health_command", "PASS" if health.returncode == 0 else "FAIL", f"rc={health.returncode}")

    board_wifi_ok = (
        line_value(health.stdout, "ssid") == args.ssid
        and line_value(health.stdout, "wpa_state") == "COMPLETED"
        and line_value(health.stdout, "ip_address") == args.board_host
    )
    add(checks, "board_wifi_state", "PASS" if board_wifi_ok else "FAIL", f"ssid={line_value(health.stdout, 'ssid')} ip={line_value(health.stdout, 'ip_address')}")

    board_case7_ok = (
        line_value(health.stdout, "BOARD_CASE7_RUNNING") == "yes"
        and (line_value(health.stdout, "BOARD_CASE7_BINARY") or "").startswith("./sample_dtof_rtsp")
        and "[DTOF_DBG] keep vi_pipe 1 attr" in health.stdout
    )
    add(checks, "board_case7_running", "PASS" if board_case7_ok else "FAIL", f"binary={line_value(health.stdout, 'BOARD_CASE7_BINARY')}")

    vm_camera_frames = int(line_value(health.stdout, "VM_CAMERA_FRAMES") or "0")
    vm_dtof_lines = int(line_value(health.stdout, "VM_DTOF_METADATA_LINES") or "0")
    vm_sync_lines = int(line_value(health.stdout, "VM_SYNC_LINES") or "0")
    vm_ok = (
        line_value(health.stdout, "VM_PARKING_ROS_RUNNING") == "yes"
        and line_value(health.stdout, "VM_LAST_CAMERA_OK") == "True"
        and line_value(health.stdout, "VM_LAST_DTOF_OK") == "True"
        and line_value(health.stdout, "VM_ANY_BOTH_OK") == "True"
        and line_value(health.stdout, "VM_STM32_SESSION_COUNT") == "0"
        and vm_camera_frames > 0
        and vm_dtof_lines > 0
        and vm_sync_lines > 0
    )
    add(
        checks,
        "vm_live_camera_dtof_sync",
        "PASS" if vm_ok else "FAIL",
        f"camera={vm_camera_frames} dtof={vm_dtof_lines} sync={vm_sync_lines} stm32_sessions={line_value(health.stdout, 'VM_STM32_SESSION_COUNT')}",
    )

    forwarder = parse_forwarder_json(health.stdout)
    evidence["forwarder"] = forwarder
    forwarder_ok = False
    forwarder_detail = "missing forwarder JSON"
    if forwarder:
        rules = ((forwarder.get("stats") or {}).get("rules") or [])
        rule = rules[0] if rules else {}
        errors = int(rule.get("errors") or 0)
        target = str(rule.get("target") or "")
        last_source = str(rule.get("last_source") or "")
        last_rx = float(rule.get("last_rx_time") or 0)
        age = time.time() - last_rx if last_rx else 999999.0
        forwarder_ok = bool(forwarder.get("running")) and errors == 0 and target == f"{args.vm_host}:2368" and last_source.startswith(args.board_host) and age < 10.0
        forwarder_detail = f"running={forwarder.get('running')} target={target} last_source={last_source} errors={errors} age={age:.2f}s"
    add(checks, "host_udp_forwarder_live", "PASS" if forwarder_ok else "FAIL", forwarder_detail)

    perception = upload_and_run_vm_script(
        ROOT / "tools" / "vm_perception_goal_check.sh",
        "/tmp/vm_perception_goal_check.sh",
        args,
        90.0,
    )
    evidence["perception_goal_check_output"] = perception.stdout
    topics_ok = all(contains_line(perception.stdout, topic) for topic in REQUIRED_TOPICS)
    dtof_packet_ok = all(
        token in perception.stdout
        for token in (
            "DTOF_LAST packet_size 4873",
            "DTOF_LAST expected_packet_size 4873",
            "DTOF_LAST width 40",
            "DTOF_LAST height 30",
            "DTOF_LAST pixel_number 1200",
            "DTOF_LAST expected_shape True",
            "DTOF_LAST depth_flat False",
            "DTOF_LAST depth_ok True",
            "HEALTH_LAST_CAMERA_OK True",
            "HEALTH_LAST_DTOF_OK True",
            "HEALTH_RECENT_ANY_BOTH_OK True",
        )
    )
    add(checks, "ros2_topics_available", "PASS" if perception.returncode == 0 and topics_ok else "FAIL", f"rc={perception.returncode}")
    add(checks, "dtof_packet_and_depth_verified", "PASS" if dtof_packet_ok else "FAIL", "4873-byte, 40x30, non-flat depth")

    if args.skip_rosbag:
        add(checks, "rosbag_replay", "WARN", "skipped by --skip-rosbag")
    else:
        replay = upload_and_run_vm_script(
            ROOT / "tools" / "vm_rosbag_replay_check.sh",
            "/tmp/vm_rosbag_replay_check.sh",
            args,
            90.0,
        )
        evidence["rosbag_replay_output"] = replay.stdout
        replay_ok = all(
            token in replay.stdout
            for token in ("REPLAY_CAMERA_RC 0", "REPLAY_DEPTH_RC 0", "REPLAY_HEALTH_RC 0")
        )
        add(checks, "rosbag_replay", "PASS" if replay.returncode == 0 and replay_ok else "FAIL", f"rc={replay.returncode}")

    bridge = run([PYTHON, FOXGLOVE_BRIDGE_TOOL, "--vm-host", args.vm_host, "status"], timeout=args.vm_timeout + 20)
    evidence["foxglove_bridge_output"] = bridge.stdout
    bridge_recorded = "FOXGLOVE_BRIDGE_INSTALLED no" in bridge.stdout and "RECOMMENDED_PACKAGE ros-humble-foxglove-bridge" in bridge.stdout
    bridge_available = "FOXGLOVE_BRIDGE_INSTALLED yes" in bridge.stdout
    add(
        checks,
        "official_foxglove_bridge_status_recorded",
        "PASS" if bridge.returncode == 0 and (bridge_recorded or bridge_available) else "FAIL",
        "installed" if bridge_available else "missing recorded with recommended package",
    )

    lite = run([PYTHON, FOXGLOVE_LITE_TOOL, "--vm-host", args.vm_host, "status"], timeout=args.vm_timeout + 20)
    evidence["foxglove_lite_status_output"] = lite.stdout
    lite_status_ok = lite.returncode == 0 and "FOXGLOVE_LITE_PROCESS" in lite.stdout and f"WS_URL ws://{args.vm_host}:8765" in lite.stdout
    add(checks, "foxglove_lite_running", "PASS" if lite_status_ok else "FAIL", f"rc={lite.returncode}")

    probe = run([PYTHON, FOXGLOVE_LITE_PROBE, "--url", f"ws://{args.vm_host}:8765", "--listen-sec", "12", "--require-all"], timeout=25.0)
    evidence["foxglove_lite_probe_output"] = probe.stdout
    foxglove_channels_ok = all(
        f"MESSAGE_DATA {idx} {topic}" in probe.stdout
        for idx, topic in enumerate([
            "/parking/camera/image",
            "/parking/dtof/preview",
            "/parking/preview/composite",
            "/parking/dtof/points_lite",
            "/parking/sensors/health_lite",
            "/parking/dtof/metadata_lite",
        ], start=1)
    )
    add(checks, "foxglove_lite_channels", "PASS" if probe.returncode == 0 and foxglove_channels_ok else "FAIL", f"rc={probe.returncode}")

    if args.skip_visual:
        add(checks, "browser_dashboard_render", "WARN", "skipped by --skip-visual")
    else:
        visual = run([PYTHON, FOXGLOVE_LITE_VISUAL, "--host", args.vm_host], timeout=35.0)
        evidence["foxglove_lite_visual_output"] = visual.stdout
        render_path = ROOT / "logs" / "foxglove_lite_render_latest.png"
        visual_ok = visual.returncode == 0 and "FOXGLOVE_LITE_RENDER_MISSING []" in visual.stdout and render_path.exists() and render_path.stat().st_size > 0
        add(checks, "browser_dashboard_render", "PASS" if visual_ok else "FAIL", str(render_path))

    safe, safe_detail = scan_forbidden_processes(args)
    add(checks, "no_forbidden_motion_processes", "PASS" if safe else "FAIL", safe_detail)

    docs_ok = all((ROOT / path).exists() for path in (
        "docs/perception_phase1_phase2_status.md",
        "docs/perception_link_runbook.md",
        "ros/parking_bridge/README.md",
    ))
    add(checks, "documentation_present", "PASS" if docs_ok else "FAIL", "status, runbook, ROS README")

    statuses = [item["status"] for item in checks]
    if any(status == "FAIL" for status in statuses):
        overall = "FAIL"
    elif any(status == "WARN" for status in statuses):
        overall = "WARN"
    else:
        overall = "PASS"

    report = {
        "time_local_epoch": time.time(),
        "overall": overall,
        "inputs": {
            "board_host": args.board_host,
            "vm_host": args.vm_host,
            "host_forward_ip": args.host_forward_ip,
            "ssid": args.ssid,
        },
        "checks": checks,
        "evidence": evidence,
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_ROOT / f"status_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"PERCEPTION_PHASE12_STATUS {overall}")
        for item in checks:
            print(f"{item['status']:4} {item['name']} - {item['evidence']}")
        print(f"PERCEPTION_PHASE12_REPORT {report_path}")
    return 0 if overall in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
