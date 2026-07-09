#!/usr/bin/env python3
"""Manage the camera+dToF receive chain without the board Ethernet cable.

Topology:

- board joins the same phone hotspot/Wi-Fi or Ethernet subnet as the Windows host
- Windows host auto-discovers the board over SSH
- VM is controlled through VMware NAT/host-only SSH
- board UDP dToF stream either targets the VM directly when it has an address
  on the board subnet, or targets the Windows host
- Windows host forwards UDP packets only when the direct VM route is unavailable

This is perception-only by default. It starts camera+dToF capture/receive code
and does not start MCU, CAN, serial actuator, motor, steering, brake, throttle,
or actuator processes. The optional STM32 receive-only path is disabled unless
--enable-stm32 is passed explicitly.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
BOARD_AUTO = ROOT / "tools" / "board_auto_ssh.py"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
DEPLOY_ROS = ROOT / "tools" / "deploy_ros_package.py"
UDP_FORWARDER = ROOT / "tools" / "udp_forwarder.py"
BOARD_STM32_SCRIPT = ROOT / "tools" / "board_stm32_usb_serial_udp_bridge.py"

STATE_DIR = ROOT / "artifacts" / "wifi_sensor_link"
FORWARDER_PID = STATE_DIR / "udp_forwarder.pid"
FORWARDER_LOG = STATE_DIR / "udp_forwarder.log"
FORWARDER_STATS = STATE_DIR / "udp_forwarder_stats.json"
LINK_STATE = STATE_DIR / "link_state.json"

BOARD_STATE_DIR = "/tmp/parking_sensor_link"
VM_STATE_DIR = "/tmp/parking_sensor_link"
REMOTE_STM32_SCRIPT = "/tmp/board_stm32_usb_serial_udp_bridge.py"

CASE7_PID_FILE = f"{BOARD_STATE_DIR}/case7.pid"
CASE7_FIFO = f"{BOARD_STATE_DIR}/case7.stdin"
CASE7_LOG = f"{BOARD_STATE_DIR}/case7.log"
STM32_PID_FILE = f"{BOARD_STATE_DIR}/stm32_bridge.pid"
STM32_LOG = f"{BOARD_STATE_DIR}/stm32_bridge.log"
VM_PID_FILE = f"{VM_STATE_DIR}/parking_ros.pid"
VM_LOG = f"{VM_STATE_DIR}/parking_ros.log"
VM_RECORD_DIR_FILE = f"{VM_STATE_DIR}/parking_record_dir"


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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


def windows_ipv4_addresses() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-NetIPAddress -AddressFamily IPv4 | "
        "Select-Object InterfaceAlias,IPAddress,PrefixLength,AddressState | "
        "ConvertTo-Json -Compress",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    return [item for item in payload if isinstance(item, dict)]


def pick_host_forward_ip(board_host: str, board: dict[str, str], explicit: str) -> str:
    if explicit:
        return explicit
    try:
        with socket.create_connection((board_host, 22), timeout=5.0) as sock:
            local_ip = sock.getsockname()[0]
        if local_ip and not local_ip.startswith("127."):
            alias = windows_interface_alias(local_ip)
            detail = f" interface={alias}" if alias else ""
            print(f"HOST_FORWARD_IP_AUTO {local_ip} source=socket{detail}")
            return local_ip
    except OSError as exc:
        print(f"HOST_FORWARD_IP_SOCKET_WARN {exc}")
    wlan_candidates: list[tuple[int, str, str]] = []
    other_candidates: list[tuple[int, str, str]] = []
    try:
        board_ip = ipaddress.ip_address(board_host)
    except ValueError:
        board_ip = None
    for item in windows_ipv4_addresses():
        if str(item.get("AddressState", "")).lower() != "preferred":
            continue
        ip = str(item.get("IPAddress", ""))
        alias = str(item.get("InterfaceAlias", ""))
        try:
            prefix = int(item.get("PrefixLength", 24))
            network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        except Exception:
            continue
        if board_ip is not None and board_ip not in network:
            continue
        score = 0
        alias_l = alias.lower()
        if alias_l == "wlan" or "wi-fi" in alias_l or "wireless" in alias_l:
            score += 100
        if "apple mobile device ethernet" in alias_l or "以太网 2" == alias_l:
            score -= 50
        candidate = (score, ip, alias)
        if score >= 100:
            wlan_candidates.append(candidate)
        else:
            other_candidates.append(candidate)
    candidates = sorted(wlan_candidates or other_candidates, key=lambda item: (-item[0], item[2], item[1]))
    if candidates:
        score, ip, alias = candidates[0]
        print(f"HOST_FORWARD_IP_AUTO {ip} interface={alias} score={score}")
        return ip
    host_ip = board.get("interface") or ""
    if host_ip:
        print(f"HOST_FORWARD_IP_AUTO {host_ip} source=board_discovery")
    return host_ip


def windows_interface_alias(ip_addr: str) -> str:
    if os.name != "nt":
        return ""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-NetIPAddress -IPAddress '{ip_addr}' -ErrorAction SilentlyContinue).InterfaceAlias",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def print_result(title: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"\n=== {title} ===")
    print(result.stdout, end="")
    print(f"{title}_EXIT_CODE {result.returncode}")


def board_auto_base(args: argparse.Namespace) -> list[str]:
    parts = [
        str(PYTHON),
        str(BOARD_AUTO),
        "--user",
        args.board_user,
        "--password",
        args.board_password,
        "--port",
        str(args.board_ssh_port),
        "--socket-timeout",
        "2",
        "--ssh-timeout",
        str(args.board_ssh_timeout),
        "--command-timeout",
        str(args.board_timeout),
    ]
    if args.board_host:
        parts.extend(["--host", args.board_host])
    return parts


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


def discover_board(args: argparse.Namespace) -> dict[str, str]:
    if args.board_host:
        try:
            with socket.create_connection((args.board_host, args.board_ssh_port), timeout=args.board_ssh_timeout):
                pass
        except OSError as exc:
            raise RuntimeError(f"explicit board host {args.board_host}:{args.board_ssh_port} is not reachable: {exc}") from exc
        return {"host": args.board_host, "source": "explicit", "interface": ""}

    parts = board_auto_base(args) + ["discover", "--json"]
    # board_auto_ssh expects subcommand before common args; rebuild explicitly.
    parts = [
        str(PYTHON),
        str(BOARD_AUTO),
        "discover",
        "--json",
        "--user",
        args.board_user,
        "--password",
        args.board_password,
        "--port",
        str(args.board_ssh_port),
        "--socket-timeout",
        "2",
        "--ssh-timeout",
        str(args.board_ssh_timeout),
        "--command-timeout",
        str(args.board_timeout),
    ]
    if args.board_host:
        parts.extend(["--host", args.board_host])
    result = run_command(parts, args.board_timeout)
    if result.returncode != 0:
        raise RuntimeError(f"board discovery failed:\n{result.stdout}")
    matches = json.loads(result.stdout)
    if not matches:
        raise RuntimeError("board discovery returned no matches")
    return matches[0]


def board_run_cmd(args: argparse.Namespace, command: str, *, allow_risk: bool = False) -> list[str]:
    parts = [
        str(PYTHON),
        str(BOARD_AUTO),
        "run",
        "--user",
        args.board_user,
        "--password",
        args.board_password,
        "--port",
        str(args.board_ssh_port),
        "--socket-timeout",
        "2",
        "--ssh-timeout",
        str(args.board_ssh_timeout),
        "--command-timeout",
        str(args.board_timeout),
    ]
    if args.board_host:
        parts.extend(["--host", args.board_host])
    if allow_risk:
        parts.append("--allow-risk")
    parts.append(command)
    return parts


def board_put_cmd(args: argparse.Namespace, local_file: Path, remote_file: str) -> list[str]:
    parts = [
        str(PYTHON),
        str(BOARD_AUTO),
        "put-text",
        "--user",
        args.board_user,
        "--password",
        args.board_password,
        "--port",
        str(args.board_ssh_port),
        "--socket-timeout",
        "2",
        "--ssh-timeout",
        str(args.board_ssh_timeout),
        "--command-timeout",
        str(args.board_timeout),
    ]
    if args.board_host:
        parts.extend(["--host", args.board_host])
    parts.extend(["--allow-risk", str(local_file), remote_file])
    return parts


def deploy_ros_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(DEPLOY_ROS),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--allow-risk",
    ]


def vm_run_cmd(args: argparse.Namespace, command: str, *, allow_risk: bool = False) -> list[str]:
    parts = vm_base(args)
    if allow_risk:
        parts.append("--allow-risk")
    parts.extend(["run"])
    if allow_risk:
        parts.append("--allow-risk")
    parts.append(command)
    return parts


def vm_start_shell(args: argparse.Namespace, rtsp_url: str) -> str:
    enable_stm32 = "true" if args.enable_stm32 else "false"
    return f"""bash -lc {sh_quote(f'''
set -e
mkdir -p {sh_quote(VM_STATE_DIR)} {sh_quote(args.vm_record_root)}
if [ -s {sh_quote(VM_PID_FILE)} ]; then
  old=$(cat {sh_quote(VM_PID_FILE)} 2>/dev/null || true)
  if [ -n "$old" ] && [ -d "/proc/$old" ]; then
    echo VM_PARKING_ROS_ALREADY_RUNNING "$old"
    cat {sh_quote(VM_RECORD_DIR_FILE)} 2>/dev/null || true
    exit 0
  fi
fi
run_id=$(date +%Y%m%d_%H%M%S)
record_dir={sh_quote(args.vm_record_root)}/run_$run_id
mkdir -p "$record_dir"
echo "$record_dir" > {sh_quote(VM_RECORD_DIR_FILE)}
nohup setsid bash -lc 'source /opt/ros/humble/setup.bash && source ~/parking_ws/install/setup.bash && exec ros2 launch parking_bridge parking.launch.py record_dir:="'$record_dir'" rtsp_url:={rtsp_url} dtof_port:={args.dtof_port} camera_backend:={args.camera_backend} camera_ffmpeg_low_delay:={str(args.camera_ffmpeg_low_delay).lower()} camera_scale:={args.camera_scale} camera_rotate:={args.camera_rotate} publish_camera_raw:={str(args.publish_camera_raw).lower()} camera_jpeg_quality:={args.camera_jpeg_quality} camera_publish_stride:={args.camera_publish_stride} camera_record_stride:={args.camera_record_stride} publish_yolo_input:={str(args.publish_yolo_input).lower()} yolo_input_topic:={args.yolo_input_topic} yolo_input_publish_stride:={args.yolo_input_publish_stride} yolo_camera_input_width:={args.yolo_camera_input_width} yolo_camera_roi_top_fraction:={args.yolo_camera_roi_top_fraction} yolo_camera_roi_bottom_fraction:={args.yolo_camera_roi_bottom_fraction} yolo_camera_clahe_clip_limit:={args.yolo_camera_clahe_clip_limit} yolo_camera_sharpen_amount:={args.yolo_camera_sharpen_amount} yolo_camera_gamma:={args.yolo_camera_gamma} yolo_camera_jpeg_quality:={args.yolo_camera_jpeg_quality} camera_drop_flat_frames:={str(args.camera_drop_flat_frames).lower()} camera_flat_luma_std_threshold:={args.camera_flat_luma_std_threshold} camera_flat_color_delta_threshold:={args.camera_flat_color_delta_threshold} camera_flat_reconnect_threshold:={args.camera_flat_reconnect_threshold} sync_slop_ms:={args.sync_slop_ms} preview_stride:={args.preview_stride} publish_pointcloud:={str(args.publish_pointcloud).lower()} dtof_depth_record_stride:={args.dtof_depth_record_stride} dtof_visual_publish_stride:={args.dtof_visual_publish_stride} dtof_visual_jpeg_quality:={args.dtof_visual_jpeg_quality} dtof_visual_width:={args.dtof_visual_width} dtof_visual_height:={args.dtof_visual_height} dtof_visual_max_mm:={args.dtof_visual_max_mm} dtof_obstacle_near_mm:={args.dtof_obstacle_near_mm} dtof_obstacle_warn_mm:={args.dtof_obstacle_warn_mm} visualize_window:=false enable_vision_preprocess:={str(args.enable_vision_preprocess).lower()} enable_yolo_person:={str(args.enable_yolo_person).lower()} yolo_process_stride:={args.yolo_process_stride} yolo_input_size:={args.yolo_input_size} yolo_confidence_threshold:={args.yolo_confidence_threshold} enable_parking_yolo:={str(args.enable_parking_yolo).lower()} enable_parking_planner:={str(args.enable_parking_planner).lower()} parking_yolo_model_path:={args.parking_yolo_model_path} parking_yolo_class_names:={args.parking_yolo_class_names} parking_yolo_empty_class_names:={args.parking_yolo_empty_class_names} parking_yolo_occupied_class_names:={args.parking_yolo_occupied_class_names} parking_yolo_slot_class_names:={args.parking_yolo_slot_class_names} parking_yolo_process_stride:={args.parking_yolo_process_stride} parking_yolo_input_size:={args.parking_yolo_input_size} parking_yolo_confidence_threshold:={args.parking_yolo_confidence_threshold} parking_yolo_nms_threshold:={args.parking_yolo_nms_threshold} parking_planner_fallback_to_pixel_candidates:={args.parking_planner_fallback_to_pixel_candidates} parking_planner_stale_after_sec:={args.parking_planner_stale_after_sec} parking_planner_max_steering_deg:={args.parking_planner_max_steering_deg} parking_planner_nominal_reverse_speed_cm_s:={args.parking_planner_nominal_reverse_speed_cm_s} enable_recording:=true enable_stm32:={enable_stm32} stm32_udp_port:={args.stm32_udp_port} stm32_analysis_sample_bytes:={args.stm32_analysis_sample_bytes}' > {sh_quote(VM_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(VM_PID_FILE)}
echo VM_PARKING_ROS_PID "$pid"
echo VM_RECORD_DIR "$record_dir"
echo VM_PARKING_ROS_LOG {sh_quote(VM_LOG)}
''')}"""


def vm_stop_shell(include_stm32: bool = False) -> str:
    orphan_pattern = "parking_bridge.*sensor_suite_node|parking_sensor_suite"
    if include_stm32:
        orphan_pattern += "|parking_bridge.*stm32_udp_bridge|parking_stm32_udp_bridge"
    return f"""bash -lc {sh_quote(f'''
if [ -s {sh_quote(VM_PID_FILE)} ]; then
  pid=$(cat {sh_quote(VM_PID_FILE)} 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill -INT -"$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
    sleep 5
    if kill -0 -"$pid" 2>/dev/null || [ -d "/proc/$pid" ]; then
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
      sleep 2
    fi
  fi
  echo VM_PARKING_ROS_STOPPED "$pid"
  if [ -s {sh_quote(VM_RECORD_DIR_FILE)} ]; then
    echo VM_RECORD_DIR "$(cat {sh_quote(VM_RECORD_DIR_FILE)} 2>/dev/null)"
  fi
else
  echo VM_PARKING_ROS_NOT_RUNNING
fi
orphans=$(ps -eo pid,args | awk '/{orphan_pattern}/ && !/awk/ {{print $1}}')
if [ -n "$orphans" ]; then
  echo VM_SENSOR_ORPHANS "$orphans"
  for child in $orphans; do kill -INT "$child" 2>/dev/null || true; done
  sleep 3
  for child in $orphans; do if [ -d "/proc/$child" ]; then kill -TERM "$child" 2>/dev/null || true; fi; done
fi
''')}"""


def board_case7_start_shell(args: argparse.Namespace, udp_dest_ip: str) -> str:
    requested_case7_bin = args.board_case7_binary.strip()
    return f"""sh -lc {sh_quote(f'''
set -e
mkdir -p {sh_quote(BOARD_STATE_DIR)}
if [ -s {sh_quote(CASE7_PID_FILE)} ]; then
  old=$(cat {sh_quote(CASE7_PID_FILE)} 2>/dev/null || true)
  if [ -n "$old" ] && [ -d "/proc/$old" ]; then
    echo BOARD_CASE7_ALREADY_RUNNING "$old"
    exit 0
  fi
fi
rm -f {sh_quote(CASE7_FIFO)}
mkfifo {sh_quote(CASE7_FIFO)}
(
  cd /opt/sample/official_dtof
  if [ -x ./dtof_init.sh ]; then
    echo BOARD_DTOF_INIT_BEGIN
    ./dtof_init.sh
    echo BOARD_DTOF_INIT_END
  else
    echo BOARD_DTOF_INIT_MISSING
  fi
  cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
  cd /opt/sample/official_dtof
  case7_bin=./sample_dtof_rtsp
  if [ -x ./sample_dtof_rtsp_keepattr ]; then
    case7_bin=./sample_dtof_rtsp_keepattr
  fi
  if [ -x ./sample_dtof_rtsp_stable ]; then
    case7_bin=./sample_dtof_rtsp_stable
  fi
  requested_case7_bin={sh_quote(requested_case7_bin)}
  if [ -n "$requested_case7_bin" ]; then
    case7_bin="$requested_case7_bin"
  fi
  echo BOARD_CASE7_BINARY "$case7_bin"
  cat {sh_quote(CASE7_FIFO)} | "$case7_bin" 7 {sh_quote(udp_dest_ip)}
  echo CASE7_EXIT_CODE=$?
) > {sh_quote(CASE7_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(CASE7_PID_FILE)}
echo BOARD_CASE7_PID "$pid"
echo BOARD_CASE7_LOG {sh_quote(CASE7_LOG)}
''')}"""


def board_stm32_start_shell(args: argparse.Namespace, udp_dest_ip: str) -> str:
    bridge = [
        "python3",
        REMOTE_STM32_SCRIPT,
        "--vm-ip",
        udp_dest_ip,
        "--udp-port",
        str(args.stm32_udp_port),
        "--vid",
        args.stm32_vid,
        "--pid",
        args.stm32_pid,
        "--baud",
        str(args.stm32_baud),
        "--chunk-size",
        str(args.stm32_chunk_size),
        "--record-dir",
        args.board_stm32_record_dir,
    ]
    if args.bind_generic:
        bridge.append("--bind-generic")
    bridge_cmd = " ".join(sh_quote(part) for part in bridge)
    return f"""sh -lc {sh_quote(f'''
set -e
mkdir -p {sh_quote(BOARD_STATE_DIR)} {sh_quote(args.board_stm32_record_dir)}
if [ -s {sh_quote(STM32_PID_FILE)} ]; then
  old=$(cat {sh_quote(STM32_PID_FILE)} 2>/dev/null || true)
  if [ -n "$old" ] && [ -d "/proc/$old" ]; then
    echo BOARD_STM32_ALREADY_RUNNING "$old"
    exit 0
  fi
fi
nohup {bridge_cmd} > {sh_quote(STM32_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(STM32_PID_FILE)}
echo BOARD_STM32_PID "$pid"
echo BOARD_STM32_LOG {sh_quote(STM32_LOG)}
''')}"""


def board_stop_shell(include_stm32: bool = False) -> str:
    stm32_block = f'''
if [ -s {sh_quote(STM32_PID_FILE)} ]; then
  pid=$(cat {sh_quote(STM32_PID_FILE)} 2>/dev/null || true)
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    kill -INT "$pid" 2>/dev/null || true
    sleep 2
    if [ -d "/proc/$pid" ]; then kill -TERM "$pid" 2>/dev/null || true; fi
  fi
  echo BOARD_STM32_STOPPED "$pid"
else
  echo BOARD_STM32_NOT_RUNNING
fi
''' if include_stm32 else '''
echo BOARD_STM32_SKIPPED_DISABLED
'''
    return f"""sh -lc {sh_quote(f'''
{stm32_block}
if [ -p {sh_quote(CASE7_FIFO)} ]; then
  ( echo > {sh_quote(CASE7_FIFO)} ) 2>/dev/null &
  fifo_writer=$!
  sleep 1
  if [ -d "/proc/$fifo_writer" ]; then
    kill "$fifo_writer" 2>/dev/null || true
    wait "$fifo_writer" 2>/dev/null || true
    echo BOARD_CASE7_FIFO_SIGNAL_TIMEOUT "$fifo_writer"
  else
    wait "$fifo_writer" 2>/dev/null || true
    echo BOARD_CASE7_FIFO_SIGNALLED
  fi
  sleep 2
fi
if [ -s {sh_quote(CASE7_PID_FILE)} ]; then
  pid=$(cat {sh_quote(CASE7_PID_FILE)} 2>/dev/null || true)
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    kill -INT "$pid" 2>/dev/null || true
    sleep 2
    if [ -d "/proc/$pid" ]; then kill -TERM "$pid" 2>/dev/null || true; fi
  fi
  echo BOARD_CASE7_STOPPED "$pid"
else
  echo BOARD_CASE7_NOT_RUNNING
fi
rm -f {sh_quote(CASE7_FIFO)}
''')}"""


def latest_session_code(record_roots: list[str], include_stm32: bool) -> str:
    return f"""from pathlib import Path
import json
roots = [Path(p) for p in {record_roots!r}]
sensor_sessions = []
stm32_sessions = []
for root in roots:
    sensor_sessions.extend(root.glob("run_*/session_*"))
    sensor_sessions.extend(root.glob("session_*"))
    if {include_stm32!r}:
        stm32_sessions.extend(root.glob("run_*/stm32_session_*"))
        stm32_sessions.extend(root.glob("stm32_session_*"))
def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0
sensor_sessions = sorted({{p for p in sensor_sessions if p.is_dir()}}, key=mtime)
stm32_sessions = sorted({{p for p in stm32_sessions if p.is_dir()}}, key=mtime)
print("VM_SENSOR_SESSION_COUNT", len(sensor_sessions))
if sensor_sessions:
    s = sensor_sessions[-1]
    print("VM_SENSOR_LATEST_SESSION", s)
    def count_lines(name):
        p = s / name
        return len(p.read_text(errors="replace").splitlines()) if p.exists() else 0
    print("VM_CAMERA_FRAMES", len(list((s / "camera_frames").glob("*.jpg"))))
    print("VM_DTOF_METADATA_LINES", count_lines("dtof_metadata.jsonl"))
    print("VM_SYNC_LINES", count_lines("sync_pairs.jsonl"))
    health_rows = []
    hp = s / "health.jsonl"
    if hp.exists():
        for line in hp.read_text(errors="replace").splitlines():
            if line.strip():
                try:
                    health_rows.append(json.loads(line))
                except Exception:
                    pass
    if health_rows:
        last = health_rows[-1]
        print("VM_LAST_CAMERA_OK", last.get("camera", {{}}).get("ok"))
        print("VM_LAST_DTOF_OK", last.get("dtof", {{}}).get("ok"))
        print("VM_ANY_BOTH_OK", any(row.get("camera", {{}}).get("ok") and row.get("dtof", {{}}).get("ok") for row in health_rows))
print("VM_STM32_SESSION_COUNT", len(stm32_sessions))
if stm32_sessions:
    s = stm32_sessions[-1]
    print("VM_STM32_LATEST_SESSION", s)
    raw = s / "stm32_serial_raw.bin"
    print("VM_STM32_RAW_BYTES", raw.stat().st_size if raw.exists() else 0)
    ap = s / "stm32_protocol_analysis.json"
    if ap.exists():
        data = json.loads(ap.read_text(errors="replace"))
        print("VM_STM32_CLASSIFICATION", data.get("classification"))
        print("VM_STM32_PROTOCOL_FAMILY", data.get("protocol_family"))
"""


def vm_health_shell(args: argparse.Namespace) -> str:
    code = latest_session_code([args.vm_record_root], args.enable_stm32)
    return f"""bash -lc {sh_quote(f'''
echo VM_SENSOR_LINK_HEALTH
hostname
hostname -I
if [ -s {sh_quote(VM_PID_FILE)} ]; then
  pid=$(cat {sh_quote(VM_PID_FILE)} 2>/dev/null || true)
  echo VM_PARKING_ROS_PID "$pid"
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then echo VM_PARKING_ROS_RUNNING yes; else echo VM_PARKING_ROS_RUNNING no; fi
else
  echo VM_PARKING_ROS_PID none
  echo VM_PARKING_ROS_RUNNING no
fi
if [ -s {sh_quote(VM_RECORD_DIR_FILE)} ]; then echo VM_RECORD_DIR "$(cat {sh_quote(VM_RECORD_DIR_FILE)} 2>/dev/null)"; fi
python3 -c {sh_quote(code)}
echo VM_LOG_TAIL_BEGIN
tail -100 {sh_quote(VM_LOG)} 2>/dev/null || true
echo VM_LOG_TAIL_END
''')}"""


def board_health_shell(include_stm32: bool) -> str:
    items = "CASE7:{case7}".format(case7=sh_quote(CASE7_PID_FILE))
    if include_stm32:
        items += " STM32:{stm32}".format(stm32=sh_quote(STM32_PID_FILE))
    return f"""sh -lc {sh_quote(f'''
echo BOARD_SENSOR_LINK_HEALTH
uname -a
wpa_cli -i wlan0 status 2>/dev/null | sed -n '/^ssid=/p;/^wpa_state=/p;/^ip_address=/p' || true
for item in {items}; do
  name=${{item%%:*}}
  file=${{item#*:}}
  if [ -s "$file" ]; then
    pid=$(cat "$file" 2>/dev/null || true)
    echo BOARD_${{name}}_PID "$pid"
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then echo BOARD_${{name}}_RUNNING yes; else echo BOARD_${{name}}_RUNNING no; fi
  else
    echo BOARD_${{name}}_PID none
    echo BOARD_${{name}}_RUNNING no
  fi
done
echo BOARD_CASE7_LOG_TAIL_BEGIN
tail -c 10000 {sh_quote(CASE7_LOG)} 2>/dev/null | tr '\\000' '.' || true
echo BOARD_CASE7_LOG_TAIL_END
if {str(include_stm32).lower()}; then
cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true
echo BOARD_STM32_LOG_TAIL_BEGIN
tail -c 10000 {sh_quote(STM32_LOG)} 2>/dev/null | tr '\\000' '.' || true
echo BOARD_STM32_LOG_TAIL_END
fi
''')}"""


def start_forwarder(args: argparse.Namespace, host_ip: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stop_forwarder()
    FORWARDER_STATS.unlink(missing_ok=True)
    log_handle = FORWARDER_LOG.open("ab")
    cmd = [
        str(PYTHON),
        str(UDP_FORWARDER),
        "--listen-ip",
        args.forward_listen_ip,
        "--forward",
        f"{args.dtof_port}:{args.vm_host}:{args.dtof_port}",
        "--stats-json",
        str(FORWARDER_STATS),
    ]
    if args.enable_stm32:
        cmd.extend(["--forward", f"{args.stm32_udp_port}:{args.vm_host}:{args.stm32_udp_port}"])
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=False,
        creationflags=creationflags,
    )
    FORWARDER_PID.write_text(str(proc.pid), encoding="utf-8")
    print(f"HOST_FORWARDER_PID {proc.pid}")
    print(f"HOST_FORWARDER_ROUTE {host_ip}:{args.dtof_port}->{args.vm_host}:{args.dtof_port}")
    if args.enable_stm32:
        print(f"HOST_FORWARDER_ROUTE {host_ip}:{args.stm32_udp_port}->{args.vm_host}:{args.stm32_udp_port}")
    time.sleep(1.0)


def print_forwarder_skipped(args: argparse.Namespace, target_ip: str) -> None:
    print("HOST_FORWARDER_SKIPPED_DIRECT_ROUTE yes")
    print(f"DTOF_DIRECT_ROUTE {target_ip}:{args.dtof_port}")
    if args.enable_stm32:
        print(f"STM32_DIRECT_ROUTE {target_ip}:{args.stm32_udp_port}")


def stop_forwarder() -> None:
    if not FORWARDER_PID.exists():
        return
    try:
        pid = int(FORWARDER_PID.read_text(encoding="utf-8").strip())
    except ValueError:
        FORWARDER_PID.unlink(missing_ok=True)
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    FORWARDER_PID.unlink(missing_ok=True)


def read_forwarder_stats() -> str:
    running = False
    pid = None
    if FORWARDER_PID.exists():
        try:
            pid = int(FORWARDER_PID.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
        if pid:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                running = str(pid) in result.stdout
            else:
                running = Path(f"/proc/{pid}").exists()
    payload = {"running": running, "pid": pid}
    if FORWARDER_STATS.exists():
        try:
            payload["stats"] = json.loads(FORWARDER_STATS.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            payload["stats_text"] = FORWARDER_STATS.read_text(encoding="utf-8", errors="replace")
    else:
        payload["stats"] = {}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def do_deploy(args: argparse.Namespace) -> int:
    overall = 0
    steps = [("Deploy ROS2 Package", deploy_ros_cmd(args), 300.0)]
    if args.enable_stm32:
        steps.append(("Upload STM32 Board Bridge", board_put_cmd(args, BOARD_STM32_SCRIPT, REMOTE_STM32_SCRIPT), args.board_timeout))
    for title, command, timeout in steps:
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    return overall


def do_start(args: argparse.Namespace) -> int:
    board = discover_board(args)
    board_host = args.board_host or board["host"]
    host_ip = pick_host_forward_ip(board_host, board, args.host_forward_ip)
    if not host_ip:
        raise RuntimeError("could not determine host IP facing the board; pass --host-forward-ip")
    dtof_target_ip = args.board_dtof_target_ip or host_ip
    rtsp_url = args.rtsp_url or f"rtsp://{board_host}:554/live0"
    if args.force_restart:
        print("FORCE_RESTART_BEGIN")
        stop_rc = do_stop(args)
        print(f"FORCE_RESTART_STOP_EXIT_CODE {stop_rc}")
        print("FORCE_RESTART_END")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LINK_STATE.write_text(
        json.dumps(
            {
                "board": board,
                "host_forward_ip": host_ip,
                "board_dtof_target_ip": dtof_target_ip,
                "rtsp_url": rtsp_url,
                "vm_host": args.vm_host,
                "skip_host_forwarder": args.skip_host_forwarder,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.skip_host_forwarder:
        stop_forwarder()
        print_forwarder_skipped(args, dtof_target_ip)
    else:
        start_forwarder(args, host_ip)
    overall = 0
    steps = []
    if args.deploy:
        steps.append(("Deploy ROS2 Package", deploy_ros_cmd(args), 300.0))
    if args.enable_stm32:
        steps.append(("Upload STM32 Board Bridge", board_put_cmd(args, BOARD_STM32_SCRIPT, REMOTE_STM32_SCRIPT), args.board_timeout))
    steps.append(("Start VM ROS2 Parking Receiver", vm_run_cmd(args, vm_start_shell(args, rtsp_url), allow_risk=True), args.vm_timeout))
    if args.enable_stm32:
        steps.append(("Start Board STM32 Forwarder", board_run_cmd(args, board_stm32_start_shell(args, dtof_target_ip), allow_risk=True), args.board_timeout))
    steps.append(("Start Board Official Case7", board_run_cmd(args, board_case7_start_shell(args, dtof_target_ip), allow_risk=True), args.board_timeout))
    for title, command, timeout in steps:
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
        if result.returncode != 0:
            break
    return overall


def do_stop(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Stop Board Sensor Processes", board_run_cmd(args, board_stop_shell(args.enable_stm32), allow_risk=True), args.board_timeout),
        ("Stop VM ROS2 Parking Receiver", vm_run_cmd(args, vm_stop_shell(args.enable_stm32), allow_risk=True), args.vm_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    stop_forwarder()
    print("\n=== Stop Host UDP Forwarder ===")
    print("HOST_FORWARDER_STOPPED")
    print("Stop Host UDP Forwarder_EXIT_CODE 0")
    return overall


def do_health(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Board Sensor Link Health", board_run_cmd(args, board_health_shell(args.enable_stm32), allow_risk=True), args.board_timeout),
        ("VM Sensor Link Health", vm_run_cmd(args, vm_health_shell(args)), args.vm_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    print("\n=== Host UDP Forwarder Health ===")
    if args.skip_host_forwarder:
        print(json.dumps({"running": False, "skipped": True, "mode": "direct_to_vm"}, indent=2))
        print("HOST_FORWARDER_SKIPPED_DIRECT_ROUTE yes")
    else:
        print(read_forwarder_stats())
    print("Host UDP Forwarder Health_EXIT_CODE 0")
    return overall


def do_latest(args: argparse.Namespace) -> int:
    result = run_command(vm_run_cmd(args, vm_health_shell(args)), args.vm_timeout)
    print_result("VM Sensor Link Health", result)
    return result.returncode


def do_adapt(args: argparse.Namespace) -> int:
    args.force_restart = True
    return do_start(args)


def do_logs(args: argparse.Namespace) -> int:
    print("\n=== Host UDP Forwarder Log ===")
    if FORWARDER_LOG.exists():
        print(FORWARDER_LOG.read_text(encoding="utf-8", errors="replace")[-12000:])
    print("Host UDP Forwarder Log_EXIT_CODE 0")
    return do_health(args)


def preview(args: argparse.Namespace) -> int:
    print("This action starts/stops the perception-only Wi-Fi sensor link.")
    print("Purpose: relay board dToF UDP through the Windows host to the VM and use RTSP from the board Wi-Fi IP.")
    print("Risk: starts/stops camera+dToF sample, ROS2 receivers, and a local UDP forwarder.")
    print("It does not start STM32, MCU, CAN, motor, steering, brake, throttle, or actuator control.")
    print("If --enable-stm32 is passed, it also starts the receive-only STM32 serial path.")
    print("Rerun with --allow-risk to execute.")
    return 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deploy", "start", "adapt", "stop", "health", "logs", "latest-session"])
    parser.add_argument("--allow-risk", action="store_true")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--force-restart", action="store_true", help="Stop any existing perception receiver/case7 process before start, so changed host IPs take effect.")
    parser.add_argument("--board-host", default="")
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-ssh-port", type=int, default=22)
    parser.add_argument("--board-ssh-timeout", type=float, default=4.0)
    parser.add_argument("--board-timeout", type=float, default=120.0)
    parser.add_argument("--vm-host", default="192.168.247.129")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--host-forward-ip", default="")
    parser.add_argument("--board-dtof-target-ip", default="", help="IP address passed to the board case7 sample as the dToF UDP destination. Defaults to --host-forward-ip.")
    parser.add_argument("--board-case7-binary", default="", help="Board binary to run for case7, e.g. ./sample_dtof_rtsp_sensor3. Defaults to the preferred installed case7 binary.")
    parser.add_argument("--skip-host-forwarder", action="store_true", help="Use a direct board-to-VM dToF UDP route and do not start the Windows UDP forwarder.")
    parser.add_argument("--forward-listen-ip", default="0.0.0.0")
    parser.add_argument("--rtsp-url", default="")
    parser.add_argument("--dtof-port", type=int, default=2368)
    parser.add_argument("--camera-backend", default="ffmpeg_mjpeg", choices=["ffmpeg_mjpeg", "opencv"])
    parser.add_argument("--camera-ffmpeg-low-delay", dest="camera_ffmpeg_low_delay", action="store_true", default=True)
    parser.add_argument("--no-camera-ffmpeg-low-delay", dest="camera_ffmpeg_low_delay", action="store_false")
    parser.add_argument("--camera-scale", default="0.5")
    parser.add_argument("--camera-rotate", default="rotate180", choices=["none", "rotate180", "180", "90cw", "90ccw"])
    parser.add_argument("--publish-camera-raw", action="store_true", help="Publish decoded raw camera images. Disabled by default for lower-latency Wi-Fi viewing.")
    parser.add_argument("--camera-jpeg-quality", type=int, default=85)
    parser.add_argument("--camera-publish-stride", type=int, default=1)
    parser.add_argument("--camera-record-stride", type=int, default=3)
    parser.add_argument("--publish-yolo-input", dest="publish_yolo_input", action="store_true", default=True)
    parser.add_argument("--disable-yolo-input", dest="publish_yolo_input", action="store_false")
    parser.add_argument("--yolo-input-topic", default="/parking/camera/yolo_input_jpeg")
    parser.add_argument("--yolo-input-publish-stride", type=int, default=1)
    parser.add_argument("--yolo-camera-input-width", type=int, default=1280)
    parser.add_argument("--yolo-camera-roi-top-fraction", default="0.0")
    parser.add_argument("--yolo-camera-roi-bottom-fraction", default="1.0")
    parser.add_argument("--yolo-camera-clahe-clip-limit", default="2.0")
    parser.add_argument("--yolo-camera-sharpen-amount", default="0.35")
    parser.add_argument("--yolo-camera-gamma", default="1.0")
    parser.add_argument("--yolo-camera-jpeg-quality", type=int, default=96)
    parser.add_argument("--camera-drop-flat-frames", action="store_true")
    parser.add_argument("--camera-flat-luma-std-threshold", type=float, default=6.0)
    parser.add_argument("--camera-flat-color-delta-threshold", type=float, default=4.0)
    parser.add_argument("--camera-flat-reconnect-threshold", type=int, default=12)
    parser.add_argument("--sync-slop-ms", default="700.0")
    parser.add_argument("--preview-stride", type=int, default=15)
    parser.add_argument("--publish-pointcloud", action="store_true", help="Publish /parking/dtof/points. Disabled by default for low-bandwidth Foxglove viewing.")
    parser.add_argument("--dtof-depth-record-stride", type=int, default=2)
    parser.add_argument("--dtof-visual-publish-stride", type=int, default=2)
    parser.add_argument("--dtof-visual-jpeg-quality", type=int, default=80)
    parser.add_argument("--dtof-visual-width", type=int, default=480)
    parser.add_argument("--dtof-visual-height", type=int, default=360)
    parser.add_argument("--dtof-visual-max-mm", type=int, default=4000)
    parser.add_argument("--dtof-obstacle-near-mm", type=int, default=500)
    parser.add_argument("--dtof-obstacle-warn-mm", type=int, default=1200)
    parser.add_argument("--enable-vision-preprocess", action="store_true")
    parser.add_argument("--enable-yolo-person", dest="enable_yolo_person", action="store_true", default=True)
    parser.add_argument("--disable-yolo-person", dest="enable_yolo_person", action="store_false")
    parser.add_argument("--yolo-process-stride", type=int, default=20)
    parser.add_argument("--yolo-input-size", type=int, default=640)
    parser.add_argument("--yolo-confidence-threshold", default="0.50")
    parser.add_argument("--enable-parking-yolo", action="store_true", help="Start perception-only parking-slot YOLO. Requires a parking ONNX model on the VM.")
    parser.add_argument("--enable-parking-planner", dest="enable_parking_planner", action="store_true", default=True)
    parser.add_argument("--disable-parking-planner", dest="enable_parking_planner", action="store_false")
    parser.add_argument("--parking-yolo-model-path", default="/home/ebaina/parking_models/parking_slot.onnx")
    parser.add_argument("--parking-yolo-class-names", default="Parking")
    parser.add_argument("--parking-yolo-empty-class-names", default="empty,empty_space,vacant,available,free")
    parser.add_argument("--parking-yolo-occupied-class-names", default="occupied,ocupied,occupied_space,car,vehicle")
    parser.add_argument("--parking-yolo-slot-class-names", default="Parking,parking,parking_space,parking_slot,slot,space")
    parser.add_argument("--parking-yolo-process-stride", type=int, default=3)
    parser.add_argument("--parking-yolo-input-size", type=int, default=640)
    parser.add_argument("--parking-yolo-confidence-threshold", default="0.35")
    parser.add_argument("--parking-yolo-nms-threshold", default="0.45")
    parser.add_argument("--parking-planner-fallback-to-pixel-candidates", default="true")
    parser.add_argument("--parking-planner-stale-after-sec", default="1.5")
    parser.add_argument("--parking-planner-max-steering-deg", default="25.0")
    parser.add_argument("--parking-planner-nominal-reverse-speed-cm-s", default="3.0")
    parser.add_argument("--enable-stm32", action="store_true", help="Explicitly include the receive-only STM32 serial path. Disabled by default for perception-only safety.")
    parser.add_argument("--stm32-udp-port", type=int, default=24680)
    parser.add_argument("--stm32-analysis-sample-bytes", type=int, default=8192)
    parser.add_argument("--stm32-vid", default="1a86")
    parser.add_argument("--stm32-pid", default="7523")
    parser.add_argument("--stm32-baud", type=int, default=9600)
    parser.add_argument("--stm32-chunk-size", type=int, default=256)
    parser.add_argument("--bind-generic", dest="bind_generic", action="store_true", default=True)
    parser.add_argument("--no-bind-generic", dest="bind_generic", action="store_false")
    parser.add_argument("--board-stm32-record-dir", default="/tmp/stm32_serial_bridge_records")
    parser.add_argument("--vm-record-root", default="/home/ebaina/parking_sensor_records/sensor_suite_wifi")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action in {"deploy", "start", "adapt", "stop"} and not args.allow_risk:
        return preview(args)
    actions = {
        "deploy": do_deploy,
        "start": do_start,
        "adapt": do_adapt,
        "stop": do_stop,
        "health": do_health,
        "logs": do_logs,
        "latest-session": do_latest,
    }
    try:
        return actions[args.action](args)
    except subprocess.TimeoutExpired as exc:
        print(f"COMMAND_TIMEOUT {exc}", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
