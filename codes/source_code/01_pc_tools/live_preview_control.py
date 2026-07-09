#!/usr/bin/env python3
"""Start/status/stop live camera+dToF preview for the verified case7 chain."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time


try:
    import paramiko
except ImportError:
    paramiko = None


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
BOARD_TOOL = ROOT / "tools" / "board_serial.py"
LOG_DIR = ROOT / "logs"
LIVE_VIEWER = ROOT / "tools" / "parking_live_viewer.py"

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASSWORD = "ebaina"
BOARD_PASSWORD = "ebaina"

BOARD_START_COMMAND = """lsmod | grep -q '^ot_vi' || { echo MEDIA_STACK_NOT_LOADED; exit 2; }
cd /opt/sample/official_dtof
rm -f /tmp/sample_dtof_rtsp_live.log /tmp/sample_dtof_rtsp_live.pid /tmp/sample_dtof_rtsp_live.rc
( (sleep 1800; echo) | timeout 1810 ./sample_dtof_rtsp_keepattr 7 192.168.137.100 > /tmp/sample_dtof_rtsp_live.log 2>&1; echo $? > /tmp/sample_dtof_rtsp_live.rc ) &
echo $! > /tmp/sample_dtof_rtsp_live.pid
sleep 5
echo BOARD_LIVE_PID=$(cat /tmp/sample_dtof_rtsp_live.pid)
tail -60 /tmp/sample_dtof_rtsp_live.log 2>/dev/null || true"""

BOARD_STATUS_COMMAND = """echo BOARD_SAMPLE_PROCESS
ps | grep sample_dtof_rtsp | grep -v grep || true
echo BOARD_RTSP_LISTEN
netstat -lntp 2>/dev/null | grep ':554' || true
echo BOARD_LOG_TAIL
tail -80 /tmp/sample_dtof_rtsp_live.log 2>/dev/null || true"""

BOARD_STOP_COMMAND = """echo BOARD_STOP
for pid in $(ps | awk '/[s]ample_dtof_rtsp/ {print $1}'); do kill "$pid" 2>/dev/null || true; done
for pid in $(ps | awk '/[t]imeout 1810 .*sample_dtof_rtsp/ {print $1}'); do kill "$pid" 2>/dev/null || true; done
for pid in $(ps | awk '/[s]leep 1800/ {print $1}'); do kill "$pid" 2>/dev/null || true; done
sleep 1
for pid in $(ps | awk '/[s]ample_dtof_rtsp/ {print $1}'); do kill -9 "$pid" 2>/dev/null || true; done
ps | grep sample_dtof_rtsp | grep -v grep || true
netstat -lntp 2>/dev/null | grep ':554' || true"""


VM_START_COMMAND = """bash -lc '
set -e
source /opt/ros/humble/setup.bash
source ~/parking_ws/install/setup.bash
record_dir=/home/ebaina/parking_sensor_records/live_preview_$(date +%Y%m%d_%H%M%S)
mkdir -p "$record_dir"
echo "$record_dir" > /tmp/parking_sensor_live_record_dir
rm -f /tmp/parking_sensor_live.log /tmp/parking_sensor_live.pid /tmp/parking_live_viewer.log /tmp/parking_live_viewer.pid
nohup timeout 1800 ros2 launch parking_bridge parking.launch.py \
  record_dir:="$record_dir" \
  camera_scale:=0.5 \
  sync_slop_ms:=700.0 \
  visualize_window:=false \
  enable_recording:=true > /tmp/parking_sensor_live.log 2>&1 &
echo $! > /tmp/parking_sensor_live.pid
nohup python3 /home/ebaina/parking_live_viewer.py --host 0.0.0.0 --port 8090 > /tmp/parking_live_viewer.log 2>&1 &
echo $! > /tmp/parking_live_viewer.pid
sleep 2
echo VM_LIVE_PID=$(cat /tmp/parking_sensor_live.pid)
echo VM_VIEWER_PID=$(cat /tmp/parking_live_viewer.pid)
echo VIEWER_URL=http://192.168.137.100:8090/
echo RECORD_DIR="$record_dir"
tail -80 /tmp/parking_sensor_live.log 2>/dev/null || true
echo VM_VIEWER_LOG
tail -20 /tmp/parking_live_viewer.log 2>/dev/null || true
'"""

VM_STATUS_COMMAND = """bash -lc '
echo VM_ROS_PROCESS
ps -eo pid,cmd | grep -E "sensor_suite_node|ros2 launch parking_bridge" | grep -v grep || true
echo VM_VIEWER_PROCESS
ps -eo pid,cmd | grep -E "parking_live_viewer.py|python3 /home/ebaina/parking_live_viewer.py" | grep -v grep || true
echo VM_VIEWER_URL
echo http://192.168.137.100:8090/
echo VM_RECORD_DIR
cat /tmp/parking_sensor_live_record_dir 2>/dev/null || true
echo VM_LOG_TAIL
tail -120 /tmp/parking_sensor_live.log 2>/dev/null || true
echo VM_VIEWER_LOG_TAIL
tail -40 /tmp/parking_live_viewer.log 2>/dev/null || true
echo VM_RECORD_COUNTS
python3 - <<'"'"'PY'"'"'
from pathlib import Path
record_file = Path("/tmp/parking_sensor_live_record_dir")
if not record_file.exists():
    raise SystemExit(0)
root = Path(record_file.read_text().strip())
sessions = sorted(root.glob("session_*"))
print("record_root", root)
print("sessions", len(sessions))
if sessions:
    s = sessions[-1]
    def lines(name):
        p = s / name
        return len(p.read_text(errors="replace").splitlines()) if p.exists() else 0
    print("session", s)
    print("camera_frames", len(list((s / "camera_frames").glob("*.jpg"))))
    print("dtof_metadata_lines", lines("dtof_metadata.jsonl"))
    print("sync_lines", lines("sync_pairs.jsonl"))
    print("preview_files", len(list((s / "preview").glob("*.jpg"))))
PY
'"""

VM_STOP_COMMAND = """bash -lc '
echo VM_STOP
pkill -f "[r]os2 launch parking_bridge parking.launch.py" 2>/dev/null || true
pkill -f "[s]ensor_suite_node" 2>/dev/null || true
pkill -f "[t]imeout 1800 ros2 launch parking_bridge" 2>/dev/null || true
pkill -f "[p]arking_live_viewer.py" 2>/dev/null || true
sleep 1
ps -eo pid,cmd | grep -E "[s]ensor_suite_node|[r]os2 launch parking_bridge|[p]arking_live_viewer.py" || true
'"""


def run(args: list[str], timeout: int = 120) -> int:
    result = subprocess.run(args, cwd=ROOT, text=True)
    return result.returncode


def run_capture(args: list[str], timeout: int = 120) -> tuple[int, str]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(result.stdout, end="")
    return result.returncode, result.stdout


def vm_run(command: str, timeout: int = 120) -> tuple[int, str]:
    args = [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        VM_HOST,
        "--user",
        VM_USER,
        "--password",
        VM_PASSWORD,
        "--timeout",
        str(timeout),
        "--allow-risk",
        "run",
        command,
    ]
    return run_capture(args, timeout + 20)


def board_run(command: str, timeout: int = 120) -> tuple[int, str]:
    args = [
        str(PYTHON),
        str(BOARD_TOOL),
        "--login-password",
        BOARD_PASSWORD,
        "--timeout",
        str(timeout),
        "--allow-risk",
        "run",
        command,
    ]
    return run_capture(args, timeout + 20)


def upload_live_viewer() -> None:
    if paramiko is None:
        raise RuntimeError("paramiko is required to upload the live viewer")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        VM_HOST,
        username=VM_USER,
        password=VM_PASSWORD,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(LIVE_VIEWER), "/home/ebaina/parking_live_viewer.py")
        finally:
            sftp.close()
    finally:
        client.close()


def fetch_latest_preview() -> Path | None:
    if paramiko is None:
        return None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        VM_HOST,
        username=VM_USER,
        password=VM_PASSWORD,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open("/tmp/parking_sensor_live_record_dir", "r") as handle:
                record_root = handle.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return None

        candidates: list[str] = []
        for subdir, suffixes in [
            ("session_*/preview", (".jpg",)),
            ("session_*/camera_frames", (".jpg",)),
            ("session_*/dtof_preview", (".png",)),
        ]:
            # SFTP has no glob; use a remote find for reliable ordering.
            command = (
                "find " + shell_quote(record_root) + "/" + subdir +
                " -type f 2>/dev/null | sort | tail -1"
            )
            _stdin, stdout, _stderr = client.exec_command(command, timeout=10)
            path = stdout.read().decode("utf-8", errors="replace").strip()
            if path and path.lower().endswith(suffixes):
                candidates.append(path)
        if not candidates:
            return None
        remote = candidates[0]
        ext = Path(remote).suffix or ".jpg"
        local = LOG_DIR / f"live_preview_latest{ext}"
        sftp.get(remote, str(local))
        return local
    finally:
        try:
            sftp.close()
        except Exception:
            pass
        client.close()


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def start() -> int:
    print("=== Upload VM web live viewer ===")
    upload_live_viewer()
    print("=== Start VM ROS2 live preview ===")
    vm_rc, _ = vm_run(VM_START_COMMAND, timeout=60)
    if vm_rc != 0:
        return vm_rc
    print("\n=== Start board case7 live stream ===")
    board_rc, _ = board_run(BOARD_START_COMMAND, timeout=180)
    if board_rc != 0:
        return board_rc
    print("\n=== Wait for camera and dToF previews ===")
    time.sleep(20)
    print("\n=== Live status ===")
    vm_run(VM_STATUS_COMMAND, timeout=60)
    board_run(BOARD_STATUS_COMMAND, timeout=60)
    preview = fetch_latest_preview()
    if preview:
        print(f"LIVE_PREVIEW_LOCAL={preview}")
    else:
        print("LIVE_PREVIEW_LOCAL=not_ready")
    return 0


def status() -> int:
    print("=== VM status ===")
    vm_run(VM_STATUS_COMMAND, timeout=60)
    print("\n=== Board status ===")
    board_run(BOARD_STATUS_COMMAND, timeout=60)
    preview = fetch_latest_preview()
    if preview:
        print(f"LIVE_PREVIEW_LOCAL={preview}")
    else:
        print("LIVE_PREVIEW_LOCAL=not_ready")
    return 0


def stop() -> int:
    print("=== Stop VM ROS2 live preview ===")
    vm_run(VM_STOP_COMMAND, timeout=60)
    print("\n=== Stop board case7 live stream ===")
    board_run(BOARD_STOP_COMMAND, timeout=60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    args = parser.parse_args()
    if args.action == "start":
        return start()
    if args.action == "status":
        return status()
    if args.action == "stop":
        return stop()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
