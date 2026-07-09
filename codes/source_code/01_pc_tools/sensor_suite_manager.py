#!/usr/bin/env python3
"""Manage the full receive-only parking sensor suite.

This starts only perception and communication components:

- board official case7 RTSP+dToF sample
- board receive-only STM32 USB serial UDP forwarder
- VM ROS2 parking_bridge receiver/recorder

It does not start MCU, CAN, motor, steering, brake, throttle, or actuator code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
BOARD_TOOL = ROOT / "tools" / "board_serial.py"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
BOARD_STM32_SCRIPT = ROOT / "tools" / "board_stm32_usb_serial_udp_bridge.py"

REMOTE_STM32_SCRIPT = "/tmp/board_stm32_usb_serial_udp_bridge.py"
BOARD_STATE_DIR = "/tmp/parking_sensor_link"
VM_STATE_DIR = "/tmp/parking_sensor_link"

CASE7_PID_FILE = f"{BOARD_STATE_DIR}/case7.pid"
CASE7_FIFO = f"{BOARD_STATE_DIR}/case7.stdin"
CASE7_LOG = f"{BOARD_STATE_DIR}/case7.log"
STM32_PID_FILE = f"{BOARD_STATE_DIR}/stm32_bridge.pid"
STM32_LOG = f"{BOARD_STATE_DIR}/stm32_bridge.log"
VM_PID_FILE = f"{VM_STATE_DIR}/parking_ros.pid"
VM_LOG = f"{VM_STATE_DIR}/parking_ros.log"
VM_RECORD_DIR_FILE = f"{VM_STATE_DIR}/parking_record_dir"
BOARD_LOG_TAIL_CMD = "tail -c 12000 {path} 2>/dev/null | tr '\\000' '.' || true"


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


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


def board_tool_base(args: argparse.Namespace) -> list[str]:
    return [
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
    ]


def vm_tool_base(args: argparse.Namespace) -> list[str]:
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


def deploy_ros_cmd(args: argparse.Namespace) -> list[str]:
    return [
        str(PYTHON),
        str(ROOT / "tools" / "deploy_ros_package.py"),
        "--host",
        args.vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
        "--allow-risk",
    ]


def upload_stm32_cmd(args: argparse.Namespace) -> list[str]:
    return board_tool_base(args) + [
        "--allow-risk",
        "put-text",
        "--allow-risk",
        str(BOARD_STM32_SCRIPT),
        REMOTE_STM32_SCRIPT,
    ]


def vm_start_shell(args: argparse.Namespace) -> str:
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
nohup setsid bash -lc 'source /opt/ros/humble/setup.bash && source ~/parking_ws/install/setup.bash && exec ros2 launch parking_bridge parking.launch.py record_dir:="'$record_dir'" rtsp_url:={args.rtsp_url} dtof_port:={args.dtof_port} camera_scale:={args.camera_scale} sync_slop_ms:={args.sync_slop_ms} visualize_window:=false enable_recording:=true enable_stm32:=true stm32_udp_port:={args.stm32_udp_port} stm32_analysis_sample_bytes:={args.stm32_analysis_sample_bytes}' > {sh_quote(VM_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(VM_PID_FILE)}
echo VM_PARKING_ROS_PID "$pid"
echo VM_RECORD_DIR "$record_dir"
echo VM_PARKING_ROS_LOG {sh_quote(VM_LOG)}
''')}"""


def board_case7_start_shell(args: argparse.Namespace) -> str:
    load_cmd = (
        "cd /opt/ko && "
        "./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 "
        "-sensor2 os08a20 -sensor3 os08a20"
    )
    sample_cmd = (
        "cd /opt/sample/official_dtof && "
        f"cat {sh_quote(CASE7_FIFO)} | ./sample_dtof_rtsp 7 {sh_quote(args.vm_host)}"
    )
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
  {load_cmd}
  {sample_cmd}
  echo CASE7_EXIT_CODE=$?
) > {sh_quote(CASE7_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(CASE7_PID_FILE)}
echo BOARD_CASE7_PID "$pid"
echo BOARD_CASE7_LOG {sh_quote(CASE7_LOG)}
''')}"""


def board_stm32_start_shell(args: argparse.Namespace) -> str:
    bridge = [
        "python3",
        REMOTE_STM32_SCRIPT,
        "--vm-ip",
        args.vm_host,
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


def vm_start_cmd(args: argparse.Namespace) -> list[str]:
    return vm_tool_base(args) + ["--allow-risk", "run", "--allow-risk", vm_start_shell(args)]


def board_case7_start_cmd(args: argparse.Namespace) -> list[str]:
    return board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", board_case7_start_shell(args)]


def board_stm32_start_cmd(args: argparse.Namespace) -> list[str]:
    return board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", board_stm32_start_shell(args)]


def board_stop_shell() -> str:
    return f"""sh -lc {sh_quote(f'''
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


def vm_stop_shell() -> str:
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
orphans=$(ps -eo pid,args | awk '/parking_bridge.*sensor_suite_node|parking_sensor_suite|parking_bridge.*stm32_udp_bridge|parking_stm32_udp_bridge/ && !/awk/ {{print $1}}')
if [ -n "$orphans" ]; then
  echo VM_SENSOR_ORPHANS "$orphans"
  for child in $orphans; do kill -INT "$child" 2>/dev/null || true; done
  sleep 3
  for child in $orphans; do if [ -d "/proc/$child" ]; then kill -TERM "$child" 2>/dev/null || true; fi; done
fi
''')}"""


def board_stop_cmd(args: argparse.Namespace) -> list[str]:
    return board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", board_stop_shell()]


def vm_stop_cmd(args: argparse.Namespace) -> list[str]:
    return vm_tool_base(args) + ["--allow-risk", "run", "--allow-risk", vm_stop_shell()]


def latest_session_code(record_roots: list[str]) -> str:
    return f"""from pathlib import Path
import json
roots = [Path(p) for p in {record_roots!r}]
sensor_sessions = []
stm32_sessions = []
for root in roots:
    sensor_sessions.extend(root.glob("run_*/session_*"))
    sensor_sessions.extend(root.glob("session_*"))
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
    print("VM_HEALTH_LINES", count_lines("health.jsonl"))
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
        print("VM_LAST_CAMERA_FRAMES", last.get("camera", {{}}).get("frames"))
        print("VM_LAST_DTOF_OK", last.get("dtof", {{}}).get("ok"))
        print("VM_LAST_DTOF_PACKETS", last.get("dtof", {{}}).get("packets"))
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
    code = latest_session_code([
        args.vm_record_root,
        "/home/ebaina/parking_sensor_records/case7_ros_check",
        "/home/ebaina/parking_sensor_records/stm32_ros_live",
        "/home/ebaina/parking_sensor_records/stm32_ros_check",
    ])
    return f"""bash -lc {sh_quote(f'''
echo VM_SENSOR_LINK_HEALTH
hostname
uname -a
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
tail -80 {sh_quote(VM_LOG)} 2>/dev/null || true
echo VM_LOG_TAIL_END
''')}"""


def board_health_shell() -> str:
    return f"""sh -lc {sh_quote(f'''
echo BOARD_SENSOR_LINK_HEALTH
uname -a
cat /proc/net/fib_trie | grep 192.168.137 || true
for item in CASE7:{sh_quote(CASE7_PID_FILE)} STM32:{sh_quote(STM32_PID_FILE)}; do
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
cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true
ls -l /dev/ttyUSB* /dev/ttyCH341USB* 2>/dev/null || true
readlink -f /sys/bus/usb-serial/devices/ttyUSB0/driver 2>/dev/null || true
echo BOARD_CASE7_LOG_TAIL_BEGIN
{BOARD_LOG_TAIL_CMD.format(path=sh_quote(CASE7_LOG))}
echo BOARD_CASE7_LOG_TAIL_END
echo BOARD_STM32_LOG_TAIL_BEGIN
{BOARD_LOG_TAIL_CMD.format(path=sh_quote(STM32_LOG))}
echo BOARD_STM32_LOG_TAIL_END
''')}"""


def vm_health_cmd(args: argparse.Namespace) -> list[str]:
    return vm_tool_base(args) + ["run", vm_health_shell(args)]


def board_health_cmd(args: argparse.Namespace) -> list[str]:
    return board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", board_health_shell()]


def vm_logs_cmd(args: argparse.Namespace) -> list[str]:
    return vm_tool_base(args) + ["run", f"bash -lc {sh_quote('tail -180 ' + sh_quote(VM_LOG) + ' 2>/dev/null || true')}"]


def board_logs_cmd(args: argparse.Namespace) -> list[str]:
    command = (
        "echo CASE7_LOG; " + BOARD_LOG_TAIL_CMD.format(path=sh_quote(CASE7_LOG)) +
        "; echo STM32_LOG; " + BOARD_LOG_TAIL_CMD.format(path=sh_quote(STM32_LOG))
    )
    return board_tool_base(args) + ["run", f"sh -lc {sh_quote(command)}"]


def latest_cmd(args: argparse.Namespace) -> list[str]:
    return vm_tool_base(args) + ["run", vm_health_shell(args)]


def print_result(title: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"\n=== {title} ===")
    print(result.stdout, end="")
    print(f"{title}_EXIT_CODE {result.returncode}")


def preview(args: argparse.Namespace) -> int:
    commands: list[tuple[str, list[str]]] = []
    if args.action == "deploy":
        commands = [("deploy ROS2 package", deploy_ros_cmd(args)), ("upload STM32 board bridge", upload_stm32_cmd(args))]
    elif args.action == "start":
        if args.deploy:
            commands.append(("deploy ROS2 package", deploy_ros_cmd(args)))
        commands.extend([
            ("upload STM32 board bridge", upload_stm32_cmd(args)),
            ("start VM ROS2 parking.launch", vm_start_cmd(args)),
            ("start board STM32 forwarder", board_stm32_start_cmd(args)),
            ("start board official case7 sample", board_case7_start_cmd(args)),
        ])
    elif args.action == "stop":
        commands = [("stop board case7 and STM32", board_stop_cmd(args)), ("stop VM ROS2 receivers", vm_stop_cmd(args))]

    print("This action needs explicit approval before execution.")
    print()
    for title, command in commands:
        print(f"{title}:")
        print(cmdline(command))
        print()
    print("Purpose:")
    print("- Manage the receive-only camera+dToF+STM32 perception link.")
    print("- Use /opt/sample/official_dtof/sample_dtof_rtsp case7 as the board baseline.")
    print("- Record ROS2 sensor data under a fresh VM directory.")
    print()
    print("Risk:")
    print("- Starts/stops only perception and communication processes.")
    print("- Opens the STM32 USB serial port receive-only and may use usbserial_generic fallback.")
    print("- Starts the official board media sample, which uses camera/dToF hardware and UDP/RTSP output.")
    print("- Sends no bytes to STM32 and starts no MCU/CAN/motor/steering/brake/throttle control.")
    print()
    print("Rerun with --allow-risk only after approval.")
    return 4


def do_deploy(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Deploy ROS2 Package", deploy_ros_cmd(args), 300.0),
        ("Upload STM32 Board Bridge", upload_stm32_cmd(args), args.board_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    return overall


def do_start(args: argparse.Namespace) -> int:
    overall = 0
    if args.deploy:
        result = run_command(deploy_ros_cmd(args), 300.0)
        print_result("Deploy ROS2 Package", result)
        if result.returncode != 0:
            return result.returncode
    for title, command, timeout in (
        ("Upload STM32 Board Bridge", upload_stm32_cmd(args), args.board_timeout),
        ("Start VM ROS2 Parking Receiver", vm_start_cmd(args), args.vm_timeout),
        ("Start Board STM32 Forwarder", board_stm32_start_cmd(args), args.board_timeout),
        ("Start Board Official Case7", board_case7_start_cmd(args), args.board_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
        if result.returncode != 0:
            break
    return overall


def do_stop(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Stop Board Sensor Processes", board_stop_cmd(args), args.board_timeout),
        ("Stop VM ROS2 Parking Receiver", vm_stop_cmd(args), args.vm_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    return overall


def do_health(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Board Sensor Link Health", board_health_cmd(args), args.board_timeout),
        ("VM Sensor Link Health", vm_health_cmd(args), args.vm_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    return overall


def do_logs(args: argparse.Namespace) -> int:
    overall = 0
    for title, command, timeout in (
        ("Board Sensor Logs", board_logs_cmd(args), args.board_timeout),
        ("VM Sensor Logs", vm_logs_cmd(args), args.vm_timeout),
    ):
        result = run_command(command, timeout)
        print_result(title, result)
        overall = overall or result.returncode
    return overall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deploy", "start", "stop", "health", "logs", "latest-session"])
    parser.add_argument("--allow-risk", action="store_true")
    parser.add_argument("--deploy", action="store_true", help="Deploy ROS2 package before start.")
    parser.add_argument("--board-port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-timeout", type=float, default=120.0)
    parser.add_argument("--vm-host", default="192.168.137.100")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.137.2:554/live0")
    parser.add_argument("--dtof-port", type=int, default=2368)
    parser.add_argument("--camera-scale", default="0.5")
    parser.add_argument("--sync-slop-ms", default="700.0")
    parser.add_argument("--stm32-udp-port", type=int, default=24680)
    parser.add_argument("--stm32-analysis-sample-bytes", type=int, default=8192)
    parser.add_argument("--stm32-vid", default="1a86")
    parser.add_argument("--stm32-pid", default="7523")
    parser.add_argument("--stm32-baud", type=int, default=9600)
    parser.add_argument("--stm32-chunk-size", type=int, default=256)
    parser.add_argument("--bind-generic", dest="bind_generic", action="store_true", default=True)
    parser.add_argument("--no-bind-generic", dest="bind_generic", action="store_false")
    parser.add_argument("--board-stm32-record-dir", default="/tmp/stm32_serial_bridge_records")
    parser.add_argument("--vm-record-root", default="/home/ebaina/parking_sensor_records/sensor_suite_live")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action in {"deploy", "start", "stop"} and not args.allow_risk:
        return preview(args)
    actions = {
        "deploy": do_deploy,
        "start": do_start,
        "stop": do_stop,
        "health": do_health,
        "logs": do_logs,
        "latest-session": do_health,
    }
    try:
        return actions[args.action](args)
    except subprocess.TimeoutExpired as exc:
        print(f"COMMAND_TIMEOUT {exc}", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
