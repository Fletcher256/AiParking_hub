#!/usr/bin/env python3
"""One-command manager for the OS08A20 + SS-LD-AS01 perception link.

The manager discovers the current COM11 + network topology, writes
artifacts/current_link_config.json, then delegates the perception-only start,
adapt, stop, health, and log actions to the existing sensor link manager.
STM32/MCU/CAN/actuator paths are disabled unless explicitly requested by a
future tool; this script exposes no actuator option.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
CONFIG_TOOL = ROOT / "tools" / "perception_link_config.py"
WIFI_MANAGER = ROOT / "tools" / "wifi_sensor_suite_manager.py"
DEFAULT_CONFIG = ROOT / "artifacts" / "current_link_config.json"
VMRUN = Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe")
VMWARE_INVENTORY = Path(os.environ.get("APPDATA", "")) / "VMware" / "inventory.vmls"


def run_command(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
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


def print_result(title: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"\n=== {title} ===")
    print(result.stdout, end="")
    print(f"{title}_EXIT_CODE {result.returncode}")


def socket_open(host: str, port: int = 22, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def default_vmx() -> str:
    env_value = os.environ.get("PARKING_VM_VMX", "")
    if env_value:
        return env_value
    if not VMWARE_INVENTORY.exists():
        return ""
    text = VMWARE_INVENTORY.read_text(encoding="gbk", errors="replace")
    paths = re.findall(r'vmlist\d+\.config\s*=\s*"([^"]+)"', text)
    for path in paths:
        if "\\ebaina\\" in path.lower() or "/ebaina/" in path.lower():
            return path
    return paths[0] if paths else ""


def vmrun_list() -> str:
    if not VMRUN.exists():
        return ""
    result = run_command([str(VMRUN), "list"], timeout=20)
    return result.stdout


def start_vm_if_needed(vmx: str) -> bool:
    if not vmx or not VMRUN.exists():
        return False
    running = vmrun_list()
    if vmx.lower() in running.lower():
        print(f"VM_ALREADY_RUNNING {vmx}")
        return True
    result = run_command([str(VMRUN), "start", vmx, "nogui"], timeout=120)
    print_result("Start VMware VM", result)
    return result.returncode == 0


def run_discovery(args: argparse.Namespace) -> tuple[int, dict]:
    cmd = [
        str(PYTHON),
        str(CONFIG_TOOL),
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
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
        "--vm-timeout",
        str(args.vm_timeout),
        "--output",
        str(args.config),
    ]
    if args.vm_host:
        cmd.extend(["--vm-host", args.vm_host])
    result = run_command(cmd, timeout=args.board_timeout + args.vm_timeout + 60)
    print_result("Discover Perception Link", result)
    config = load_config(args.config)
    return result.returncode, config


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def ensure_config_for_action(args: argparse.Namespace, action: str) -> dict:
    if action == "stop" and args.use_existing_config and args.config.exists():
        config = load_config(args.config)
        if config.get("board_ip") and config.get("vm_ip"):
            return config
    rc, config = run_discovery(args)
    if rc == 0:
        return config
    if action in {"start", "adapt"} and args.auto_start_vm and "vm_ssh_unreachable" in config.get("issues", []):
        vmx = args.vmx or default_vmx()
        if start_vm_if_needed(vmx):
            wait_for_vm(args)
            _rc, config = run_discovery(args)
            return config
    return config


def wait_for_vm(args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.vm_boot_wait_sec
    hosts = []
    if args.vm_host:
        hosts.append(args.vm_host)
    hosts.extend(["192.168.247.129", "192.168.137.100"])
    seen = set()
    hosts = [host for host in hosts if not (host in seen or seen.add(host))]
    while time.monotonic() < deadline:
        for host in hosts:
            if socket_open(host, 22, timeout=1.0):
                print(f"VM_SSH_PORT_OPEN {host}")
                return
        print("VM_SSH_WAIT")
        time.sleep(3)


def wifi_manager_cmd(args: argparse.Namespace, action: str, config: dict) -> list[str]:
    board_ip = config.get("board_ip", "")
    vm_ip = config.get("vm_ip", "")
    host_forward_ip = config.get("host_forward_ip", "")
    rtsp_url = config.get("rtsp_url", "")
    dtof_route = config.get("dtof_udp_route", {}) if isinstance(config.get("dtof_udp_route"), dict) else {}
    dtof_route_mode = str(dtof_route.get("mode") or "host_forwarder")
    board_dtof_target_ip = str(dtof_route.get("board_udp_target_ip") or host_forward_ip)
    cmd = [
        str(PYTHON),
        str(WIFI_MANAGER),
        action,
        "--board-host",
        board_ip,
        "--vm-host",
        vm_ip,
        "--host-forward-ip",
        host_forward_ip,
        "--board-dtof-target-ip",
        board_dtof_target_ip,
        "--board-case7-binary",
        args.board_case7_binary,
        "--rtsp-url",
        rtsp_url,
        "--board-user",
        args.board_user,
        "--board-password",
        args.board_password,
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
        "--board-timeout",
        str(args.board_timeout),
        "--vm-timeout",
        str(args.vm_timeout),
        "--camera-scale",
        args.camera_scale,
        "--camera-rotate",
        args.camera_rotate,
        "--camera-jpeg-quality",
        str(args.camera_jpeg_quality),
        "--camera-publish-stride",
        str(args.camera_publish_stride),
        "--camera-record-stride",
        str(args.camera_record_stride),
        "--camera-drop-flat-frames",
        "--camera-flat-reconnect-threshold",
        str(args.camera_flat_reconnect_threshold),
        "--dtof-visual-publish-stride",
        str(args.dtof_visual_publish_stride),
        "--dtof-depth-record-stride",
        str(args.dtof_depth_record_stride),
        "--dtof-visual-jpeg-quality",
        str(args.dtof_visual_jpeg_quality),
        "--yolo-process-stride",
        str(args.yolo_process_stride),
        "--yolo-input-size",
        str(args.yolo_input_size),
        "--yolo-confidence-threshold",
        str(args.yolo_confidence_threshold),
        "--vm-record-root",
        args.vm_record_root,
    ]
    if dtof_route_mode == "direct_to_vm":
        cmd.append("--skip-host-forwarder")
    if args.camera_ffmpeg_low_delay:
        cmd.append("--camera-ffmpeg-low-delay")
    else:
        cmd.append("--no-camera-ffmpeg-low-delay")
    if args.publish_pointcloud:
        cmd.append("--publish-pointcloud")
    if args.enable_vision_preprocess:
        cmd.append("--enable-vision-preprocess")
    if args.enable_yolo_person:
        cmd.append("--enable-yolo-person")
    else:
        cmd.append("--disable-yolo-person")
    if action in {"start", "adapt", "stop", "deploy"}:
        cmd.append("--allow-risk")
    if args.deploy and action in {"start", "adapt"}:
        cmd.append("--deploy")
    return cmd


def require_link(config: dict) -> bool:
    missing = [key for key in ("board_ip", "vm_ip", "host_forward_ip", "rtsp_url") if not config.get(key)]
    route = config.get("dtof_udp_route", {}) if isinstance(config.get("dtof_udp_route"), dict) else {}
    if not route.get("board_udp_target_ip"):
        missing.append("dtof_udp_route.board_udp_target_ip")
    if missing:
        print("LINK_CONFIG_INCOMPLETE " + ",".join(missing))
        if config.get("issues"):
            print("LINK_CONFIG_ISSUES " + ",".join(config["issues"]))
        return False
    return True


def do_action(args: argparse.Namespace) -> int:
    if args.action == "discover":
        rc, _config = run_discovery(args)
        return rc
    if args.action in {"start", "adapt", "stop"} and not args.allow_risk:
        print("This action starts/stops perception-only camera+dToF processes.")
        print("Purpose: run OS08A20 RTSP + SS-LD-AS01 dToF receive/record/Foxglove chain.")
        print("Risk: starts/stops board case7, VM ROS2 receiver, and host UDP forwarder.")
        print("It does not start MCU, CAN, motor, steering, brake, throttle, or actuator control.")
        print("Rerun with --allow-risk to execute.")
        return 4
    config = ensure_config_for_action(args, args.action)
    if not require_link(config):
        return 2
    mapped_action = args.action
    if mapped_action == "start" and args.force_restart:
        mapped_action = "adapt"
    cmd = wifi_manager_cmd(args, mapped_action, config)
    result = run_command(cmd, timeout=args.manager_timeout)
    print_result(f"Perception Link {args.action}", result)
    print(f"CURRENT_LINK_CONFIG {args.config}")
    if config.get("foxglove_ws_url"):
        print(f"FOXGLOVE_WS_URL {config['foxglove_ws_url']}")
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["discover", "start", "adapt", "health", "logs", "latest-session", "stop"])
    parser.add_argument("--allow-risk", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--board-port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-timeout", type=float, default=120.0)
    parser.add_argument("--board-case7-binary", default="")
    parser.add_argument("--vm-host", default="")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--vmx", default="")
    parser.add_argument("--auto-start-vm", dest="auto_start_vm", action="store_true", default=True)
    parser.add_argument("--no-auto-start-vm", dest="auto_start_vm", action="store_false")
    parser.add_argument("--vm-boot-wait-sec", type=float, default=90.0)
    parser.add_argument("--manager-timeout", type=float, default=240.0)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--force-restart", action="store_true", default=True)
    parser.add_argument("--no-force-restart", dest="force_restart", action="store_false")
    parser.add_argument("--use-existing-config", action="store_true", default=True)
    parser.add_argument("--camera-scale", default="0.5")
    parser.add_argument("--camera-rotate", default="rotate180", choices=["none", "rotate180", "180", "90cw", "90ccw"])
    parser.add_argument("--camera-jpeg-quality", type=int, default=85)
    parser.add_argument("--camera-publish-stride", type=int, default=1)
    parser.add_argument("--camera-record-stride", type=int, default=3)
    parser.add_argument("--camera-ffmpeg-low-delay", action="store_true", default=True)
    parser.add_argument("--no-camera-ffmpeg-low-delay", dest="camera_ffmpeg_low_delay", action="store_false")
    parser.add_argument("--camera-flat-reconnect-threshold", type=int, default=90)
    parser.add_argument("--publish-pointcloud", action="store_true", help="Publish /parking/dtof/points. Disabled by default for the low-bandwidth Foxglove path.")
    parser.add_argument("--dtof-depth-record-stride", type=int, default=2)
    parser.add_argument("--dtof-visual-publish-stride", type=int, default=2)
    parser.add_argument("--dtof-visual-jpeg-quality", type=int, default=80)
    parser.add_argument("--enable-vision-preprocess", action="store_true")
    parser.add_argument("--enable-yolo-person", dest="enable_yolo_person", action="store_true", default=True)
    parser.add_argument("--disable-yolo-person", dest="enable_yolo_person", action="store_false")
    parser.add_argument("--yolo-process-stride", type=int, default=20)
    parser.add_argument("--yolo-input-size", type=int, default=640)
    parser.add_argument("--yolo-confidence-threshold", default="0.50")
    parser.add_argument("--vm-record-root", default="/home/ebaina/parking_sensor_records/sensor_suite_auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return do_action(args)


if __name__ == "__main__":
    raise SystemExit(main())
