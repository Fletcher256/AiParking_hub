#!/usr/bin/env python3
"""Perception-only acceptance runner for OS08A20 RTSP + SS-LD-AS01 dToF.

This script manages only the sensing path:
- board official dToF + RTSP sample through perception_link_manager
- Windows UDP relay
- VM ROS2 receiver
- VM/Foxglove status and frame audits

It does not start MCU, CAN, serial actuator, motor, steering, brake, throttle,
or any vehicle motion path.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
MANAGER = ROOT / "tools" / "perception_link_manager.py"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
FOXGLOVE = ROOT / "tools" / "foxglove_bridge_control.py"
FOXGLOVE_LOW_BW = ROOT / "tools" / "foxglove_low_bandwidth_audit.py"
REPORT_ROOT = ROOT / "artifacts" / "perception_link_acceptance"
DEFAULT_CONFIG = ROOT / "artifacts" / "current_link_config.json"


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    print(f"RUN {' '.join(parts)}", flush=True)
    proc = subprocess.run(
        parts,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    print(proc.stdout, end="", flush=True)
    print(f"EXIT_CODE {proc.returncode}", flush=True)
    return proc


def trim(text: str, limit: int = 60000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[trimmed]...\n" + text[-half:]


def vm_base(args: argparse.Namespace) -> list[str]:
    if not args.vm_host:
        raise RuntimeError("VM host is unresolved; run discovery first or pass --vm-host.")
    return [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
    ]


def vm_put(args: argparse.Namespace, local: str, remote: str) -> subprocess.CompletedProcess[str]:
    return run(vm_base(args) + ["--allow-risk", "put-text", str(ROOT / local), remote], args.vm_timeout)


def vm_run(args: argparse.Namespace, command: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return run(
        vm_base(args) + ["--timeout", str(timeout or args.vm_timeout), "--allow-risk", "run", command],
        timeout or args.vm_timeout,
    )


def manager(args: argparse.Namespace, action: str, timeout: float) -> subprocess.CompletedProcess[str]:
    cmd = [str(PYTHON), str(MANAGER), action, "--config", str(args.config)]
    if args.vm_host:
        cmd.extend(["--vm-host", args.vm_host])
    if action in {"adapt", "start", "stop"}:
        cmd.append("--allow-risk")
    return run(cmd, timeout)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def summarize_link(config: dict[str, Any]) -> dict[str, Any]:
    route = config.get("dtof_udp_route", {})
    board = config.get("board", {})
    vm = config.get("vm", {})
    return {
        "board_ip": config.get("board_ip", ""),
        "board_addresses": board.get("addresses", []),
        "vm_ip": config.get("vm_ip", ""),
        "vm_addresses": vm.get("addresses", []),
        "host_forward_ip": config.get("host_forward_ip", ""),
        "rtsp_url": config.get("rtsp_url", ""),
        "dtof_udp_mode": route.get("mode") if isinstance(route, dict) else "",
        "board_udp_target_ip": route.get("board_udp_target_ip") if isinstance(route, dict) else "",
        "dtof_udp_route": route.get("target") or route,
        "foxglove_ws_url": config.get("foxglove_ws_url", ""),
        "issues": config.get("issues", []),
    }


def apply_discovered_vm_host(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if not getattr(args, "auto_vm_host", False) and args.vm_host:
        return
    vm_ip = config.get("vm_ip", "")
    if vm_ip:
        args.vm_host = vm_ip


def current_rtsp_url(args: argparse.Namespace, config: dict[str, Any]) -> str:
    return args.rtsp_url or config.get("rtsp_url", "")


def extract_int(text: str, key: str) -> int | None:
    match = re.search(rf"^{re.escape(key)}\s+(-?\d+)", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def extract_bool(text: str, key: str) -> bool | None:
    match = re.search(rf"^{re.escape(key)}\s+(\w+)", text, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).lower()
    if value in {"true", "yes", "1"}:
        return True
    if value in {"false", "no", "0"}:
        return False
    return None


def count_occurrences(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, flags=re.MULTILINE))


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"perception_acceptance_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-sec", type=int, default=600)
    parser.add_argument("--health-interval-sec", type=int, default=60)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--vm-host", default="", help="VM SSH host. Omit for automatic discovery.")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--rtsp-url", default="", help="Override RTSP URL. Omit to use discovered link config.")
    parser.add_argument("--min-camera-frames", type=int, default=1000)
    parser.add_argument("--min-dtof-lines", type=int, default=1000)
    parser.add_argument("--stop-after", action="store_true")
    args = parser.parse_args(argv)
    args.auto_vm_host = not bool(args.vm_host)

    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "safety": {
            "perception_only": True,
            "actuator_control_allowed": False,
            "stm32_enabled": False,
        },
        "run_sec": args.run_sec,
        "steps": {},
        "link_config": {},
        "checks": [],
    }

    discover = manager(args, "discover", args.vm_timeout * 3)
    report["steps"]["discover"] = {"returncode": discover.returncode, "stdout": trim(discover.stdout)}
    config = load_config(args.config)
    report["link_config"]["after_discover"] = summarize_link(config)
    apply_discovered_vm_host(args, config)
    if not args.vm_host:
        report["overall"] = "FAIL"
        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path = write_report(report)
        print("PERCEPTION_LINK_ACCEPTANCE FAIL")
        print("FAIL vm_host_auto_discovery - VM host could not be discovered")
        print(f"PERCEPTION_ACCEPTANCE_REPORT {path}")
        return 2

    uploads = [
        ("tools/vm_perception_goal_check.sh", "/tmp/vm_perception_goal_check.sh"),
        ("tools/vm_camera_frame_audit.py", "/tmp/vm_camera_frame_audit.py"),
        ("tools/vm_rtsp_capture_audit.py", "/tmp/vm_rtsp_capture_audit.py"),
        ("tools/vm_rtsp_quality_latency_audit.py", "/tmp/vm_rtsp_quality_latency_audit.py"),
        ("tools/vm_rtsp_null_decode_check.sh", "/tmp/vm_rtsp_null_decode_check.sh"),
        ("tools/vm_rosbag_replay_check.sh", "/tmp/vm_rosbag_replay_check.sh"),
        ("tools/camera_calibration_tool.py", "/tmp/camera_calibration_tool.py"),
    ]
    for local, remote in uploads:
        proc = vm_put(args, local, remote)
        report["steps"][f"upload_{Path(local).name}"] = {"returncode": proc.returncode, "stdout": trim(proc.stdout)}

    adapt = manager(args, "adapt", args.vm_timeout * 4)
    report["steps"]["adapt"] = {"returncode": adapt.returncode, "stdout": trim(adapt.stdout)}
    config = load_config(args.config)
    report["link_config"]["after_adapt"] = summarize_link(config)
    apply_discovered_vm_host(args, config)

    deadline = time.time() + max(0, args.run_sec)
    health_runs: list[dict[str, Any]] = []
    while time.time() < deadline:
        remaining = int(deadline - time.time())
        sleep_for = min(args.health_interval_sec, max(1, remaining))
        print(f"ACCEPTANCE_WAIT remaining_sec={remaining} next_health_in={sleep_for}", flush=True)
        time.sleep(sleep_for)
        health = manager(args, "health", args.vm_timeout * 4)
        health_runs.append({"returncode": health.returncode, "stdout": trim(health.stdout)})
    report["steps"]["periodic_health"] = health_runs

    final_health = manager(args, "health", args.vm_timeout * 4)
    report["steps"]["final_health"] = {"returncode": final_health.returncode, "stdout": trim(final_health.stdout)}
    config = load_config(args.config)
    report["link_config"]["final"] = summarize_link(config)
    rtsp_url = current_rtsp_url(args, config)

    goal_check = vm_run(args, "ROSBAG_SMOKE=1 bash /tmp/vm_perception_goal_check.sh", args.vm_timeout * 2)
    report["steps"]["vm_goal_check"] = {"returncode": goal_check.returncode, "stdout": trim(goal_check.stdout)}

    rosbag_replay = vm_run(args, "bash /tmp/vm_rosbag_replay_check.sh", args.vm_timeout * 2)
    report["steps"]["rosbag_replay_check"] = {"returncode": rosbag_replay.returncode, "stdout": trim(rosbag_replay.stdout)}

    calibration_help = vm_run(
        args,
        "python3 /tmp/camera_calibration_tool.py --help && "
        "python3 /tmp/camera_calibration_tool.py capture --help && "
        "python3 /tmp/camera_calibration_tool.py calibrate --pattern charuco --help",
        args.vm_timeout,
    )
    report["steps"]["calibration_tool_help"] = {
        "returncode": calibration_help.returncode,
        "stdout": trim(calibration_help.stdout),
    }

    camera_audit = vm_run(args, "python3 /tmp/vm_camera_frame_audit.py --sample 1000", args.vm_timeout * 2)
    report["steps"]["camera_audit"] = {"returncode": camera_audit.returncode, "stdout": trim(camera_audit.stdout)}

    rtsp_audit = vm_run(
        args,
        "python3 /tmp/vm_rtsp_capture_audit.py --url "
        f"{shlex.quote(rtsp_url)} "
        "--seconds 20 --root /tmp/rtsp_capture_audit_acceptance",
        args.vm_timeout * 2,
    )
    report["steps"]["rtsp_capture_audit"] = {"returncode": rtsp_audit.returncode, "stdout": trim(rtsp_audit.stdout)}

    null_decode = vm_run(
        args,
        "bash /tmp/vm_rtsp_null_decode_check.sh "
        f"{shlex.quote(rtsp_url)} 20 "
        "/tmp/rtsp_null_decode_acceptance.log tcp_default",
        args.vm_timeout * 2,
    )
    report["steps"]["rtsp_null_decode"] = {"returncode": null_decode.returncode, "stdout": trim(null_decode.stdout)}

    rtsp_quality = vm_run(
        args,
        "python3 /tmp/vm_rtsp_quality_latency_audit.py --url "
        f"{shlex.quote(rtsp_url)} "
        "--seconds 10 --root /tmp/rtsp_quality_latency_acceptance",
        args.vm_timeout * 3,
    )
    report["steps"]["rtsp_quality_latency_audit"] = {
        "returncode": rtsp_quality.returncode,
        "stdout": trim(rtsp_quality.stdout),
    }

    fox = run([str(PYTHON), str(FOXGLOVE), "--vm-host", args.vm_host, "status"], args.vm_timeout)
    report["steps"]["foxglove_status"] = {"returncode": fox.returncode, "stdout": trim(fox.stdout)}

    fox_low_bw = run([str(PYTHON), str(FOXGLOVE_LOW_BW), "--vm-host", args.vm_host], args.vm_timeout + 120)
    report["steps"]["foxglove_low_bandwidth_audit"] = {
        "returncode": fox_low_bw.returncode,
        "stdout": trim(fox_low_bw.stdout),
    }

    if args.stop_after:
        stop = manager(args, "stop", args.vm_timeout * 4)
        report["steps"]["stop"] = {"returncode": stop.returncode, "stdout": trim(stop.stdout)}

    checks = report["checks"]
    add_check(checks, "adapt_exit_code", adapt.returncode == 0, f"exit_code={adapt.returncode}")
    add_check(checks, "final_health_exit_code", final_health.returncode == 0, f"exit_code={final_health.returncode}")
    add_check(checks, "discovered_rtsp_url", bool(rtsp_url), rtsp_url or "missing")
    add_check(checks, "camera_ok", extract_bool(final_health.stdout, "VM_LAST_CAMERA_OK") is True, "VM_LAST_CAMERA_OK")
    add_check(checks, "dtof_ok", extract_bool(final_health.stdout, "VM_LAST_DTOF_OK") is True, "VM_LAST_DTOF_OK")
    final_route = config.get("dtof_udp_route", {}) if isinstance(config.get("dtof_udp_route"), dict) else {}
    final_route_mode = final_route.get("mode", "")
    if final_route_mode == "direct_to_vm":
        route_ok = "HOST_FORWARDER_SKIPPED_DIRECT_ROUTE yes" in final_health.stdout and extract_bool(final_health.stdout, "VM_LAST_DTOF_OK") is True
        route_detail = f"direct_to_vm target={final_route.get('board_udp_target_ip', '')}"
    else:
        route_ok = '"errors": 0' in final_health.stdout
        route_detail = "host UDP forwarder errors=0"
    add_check(checks, "dtof_udp_route_ok", route_ok, route_detail)
    add_check(checks, "stm32_disabled", "VM_STM32_SESSION_COUNT 0" in final_health.stdout, "STM32 not part of this acceptance")

    camera_frames = extract_int(final_health.stdout, "VM_CAMERA_FRAMES") or 0
    dtof_lines = extract_int(final_health.stdout, "VM_DTOF_METADATA_LINES") or 0
    add_check(checks, "camera_frames_min", camera_frames >= args.min_camera_frames, f"{camera_frames} >= {args.min_camera_frames}")
    add_check(checks, "dtof_lines_min", dtof_lines >= args.min_dtof_lines, f"{dtof_lines} >= {args.min_dtof_lines}")
    add_check(
        checks,
        "vision_topics_present",
        "TOPIC_TYPE /parking/vision/line_debug sensor_msgs/msg/CompressedImage" in goal_check.stdout
        and "TOPIC_TYPE /parking/parking_slot_candidates std_msgs/msg/String" in goal_check.stdout
        and "TOPIC_TYPE /parking/perception/state std_msgs/msg/String" in goal_check.stdout,
        "vision debug, pixel candidates, and perception state topics are present",
    )
    add_check(
        checks,
        "vision_candidates_echo",
        "VISION_CANDIDATES_ONCE_BEGIN" in goal_check.stdout
        and (
            "pixel_only_uncalibrated" in goal_check.stdout
            or "line_count" in goal_check.stdout
            or "processed_image_size" in goal_check.stdout
        ),
        "pixel-only candidate JSON is echoed",
    )
    add_check(
        checks,
        "perception_state_motion_disabled",
        "PERCEPTION_STATE_ONCE_BEGIN" in goal_check.stdout
        and (
            '"motion_enabled": false' in goal_check.stdout.lower().replace("\\", "")
            or '"motion_enabled":false' in goal_check.stdout.lower().replace("\\", "")
        ),
        "perception state reports motion_enabled=false",
    )
    add_check(
        checks,
        "rosbag_smoke_recorded",
        "ROSBAG_SMOKE_BEGIN" in goal_check.stdout
        and "ROSBAG_DIR" in goal_check.stdout
        and "Topic information:" in goal_check.stdout,
        "rosbag smoke record created and inspected",
    )
    add_check(
        checks,
        "rosbag_replay_ok",
        rosbag_replay.returncode == 0 and "ROSBAG_REPLAY_CHECK PASS" in rosbag_replay.stdout,
        "latest rosbag replay checked in an isolated DDS domain",
    )
    add_check(
        checks,
        "calibration_tool_ready",
        calibration_help.returncode == 0
        and "Capture calibration images" in calibration_help.stdout
        and "camera_info YAML" in calibration_help.stdout,
        "camera calibration capture/calibrate helper is available on the VM, including Charuco options",
    )

    add_check(checks, "camera_audit_no_bad_decode", "BAD_DECODE 0" in camera_audit.stdout, "ROS JPEG bad decode=0")
    add_check(checks, "camera_audit_no_flat", "FLAT_COUNT 0" in camera_audit.stdout, "ROS JPEG flat=0")
    add_check(checks, "camera_audit_no_grayish", "GRAYISH_COUNT 0" in camera_audit.stdout, "ROS JPEG grayish=0")
    add_check(checks, "rtsp_capture_no_bad_decode", count_occurrences(rtsp_audit.stdout, r"^BAD_DECODE 0$") >= 2, "both RTSP modes bad_decode=0")
    add_check(checks, "rtsp_capture_no_flat", count_occurrences(rtsp_audit.stdout, r"^FLAT 0$") >= 2, "both RTSP modes flat=0")
    null_bad_match = re.search(r"^NULL_DECODE_BAD_LINES=(\d+)$", null_decode.stdout, flags=re.MULTILINE)
    null_dts_match = re.search(r"^NULL_DTS_WARNING_LINES=(\d+)$", null_decode.stdout, flags=re.MULTILINE)
    null_bad_lines = null_bad_match.group(1) if null_bad_match else "missing"
    null_dts_lines = null_dts_match.group(1) if null_dts_match else "missing"
    add_check(
        checks,
        "rtsp_null_decode_diagnostics_recorded",
        null_decode.returncode == 0 and null_bad_match is not None and null_dts_match is not None,
        f"ffmpeg null decode diagnostics recorded; bad_lines={null_bad_lines}, dts_warning_lines={null_dts_lines}",
    )
    production_camera_quality_ok = (
        extract_bool(final_health.stdout, "VM_LAST_CAMERA_OK") is True
        and "BAD_DECODE 0" in camera_audit.stdout
        and "FLAT_COUNT 0" in camera_audit.stdout
        and "GRAYISH_COUNT 0" in camera_audit.stdout
        and count_occurrences(rtsp_audit.stdout, r"^BAD_DECODE 0$") >= 2
        and count_occurrences(rtsp_audit.stdout, r"^FLAT 0$") >= 2
    )
    rtsp_quality_passed = rtsp_quality.returncode == 0 and "RTSP_QUALITY_LATENCY_AUDIT PASS" in rtsp_quality.stdout
    rtsp_quality_recorded = "RTSP_QUALITY_LATENCY_AUDIT_" in rtsp_quality.stdout or "RTSP_QUALITY_LATENCY_AUDIT " in rtsp_quality.stdout
    rtsp_quality_detail = (
        "RTSP alternatives passed standalone thresholds"
        if rtsp_quality_passed
        else "RTSP standalone diagnostics recorded; production ROS camera output passed bad/flat/gray gates"
    )
    add_check(
        checks,
        "camera_quality_and_rtsp_diagnostics_ok",
        (rtsp_quality_passed or (rtsp_quality_recorded and production_camera_quality_ok)),
        rtsp_quality_detail,
    )
    add_check(checks, "foxglove_status_ok", fox.returncode == 0 and "FOXGLOVE_BRIDGE_RUNNING yes" in fox.stdout, "foxglove bridge running")
    add_check(
        checks,
        "foxglove_low_bandwidth_ok",
        fox_low_bw.returncode == 0 and "FOXGLOVE_LOW_BANDWIDTH_AUDIT PASS" in fox_low_bw.stdout,
        "bridge whitelist active, recommended topics receive messages, point cloud idle",
    )

    report["overall"] = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = write_report(report)

    print(f"PERCEPTION_LINK_ACCEPTANCE {report['overall']}")
    for item in checks:
        print(f"{item['status']:4} {item['name']} - {item['detail']}")
    print(f"PERCEPTION_ACCEPTANCE_REPORT {path}")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
