#!/usr/bin/env python3
"""Start/status/stop Wi-Fi camera+dToF browser preview.

This wraps the verified same-Wi-Fi receive chain and exposes the VM-side
preview images through a tiny HTTP server. It is receive-only and does not
start chassis, MCU, CAN, motor, steering, brake, throttle, or actuator code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
WIFI_MANAGER = ROOT / "tools" / "wifi_sensor_suite_manager.py"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
LIVE_VIEWER = ROOT / "tools" / "parking_live_viewer.py"
LOG_DIR = ROOT / "logs"

DEFAULT_VM_HOST = "192.168.247.129"
DEFAULT_VM_USER = "ebaina"
DEFAULT_VM_PASSWORD = "ebaina"
REMOTE_VIEWER = "/home/ebaina/parking_live_viewer.py"
REMOTE_LIVE_RECORD_FILE = "/tmp/parking_sensor_live_record_dir"
REMOTE_WIFI_RECORD_FILE = "/tmp/parking_sensor_link/parking_record_dir"
REMOTE_VIEWER_LOG = "/tmp/parking_live_viewer.log"
REMOTE_VIEWER_PID = "/tmp/parking_live_viewer.pid"


def run_command(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        parts,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(result.stdout, end="")
    return result


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
        "--allow-risk",
    ]


def vm_run(args: argparse.Namespace, command: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    parts = vm_base(args) + ["run", "--allow-risk", command]
    return run_command(parts, timeout or args.vm_timeout + 20)


def upload_viewer(args: argparse.Namespace) -> int:
    parts = vm_base(args) + ["put-text", "--allow-risk", str(LIVE_VIEWER), REMOTE_VIEWER]
    return run_command(parts, args.vm_timeout + 20).returncode


def wifi_manager(args: argparse.Namespace, action: str) -> int:
    parts = [
        str(PYTHON),
        str(WIFI_MANAGER),
        action,
        "--vm-host",
        args.vm_host,
        "--vm-user",
        args.vm_user,
        "--vm-password",
        args.vm_password,
    ]
    if action in {"start", "stop"}:
        parts.append("--allow-risk")
    if args.board_host:
        parts.extend(["--board-host", args.board_host])
    if args.host_forward_ip:
        parts.extend(["--host-forward-ip", args.host_forward_ip])
    if action == "start":
        parts.extend(["--preview-stride", str(args.preview_stride)])
        parts.extend(["--camera-scale", str(args.camera_scale)])
        parts.extend(["--camera-backend", args.camera_backend])
        parts.extend(["--camera-jpeg-quality", str(args.camera_jpeg_quality)])
        if args.force_restart:
            parts.append("--force-restart")
        if args.publish_camera_raw:
            parts.append("--publish-camera-raw")
    result = run_command(parts, args.manager_timeout)
    if action == "start" and result.returncode != 0 and "VM_PARKING_ROS_ALREADY_RUNNING" in result.stdout:
        return 0
    return result.returncode


def viewer_start_command(args: argparse.Namespace) -> str:
    return f"""bash -lc {shell_quote(f'''
set -e
record_dir=$(cat {shell_quote(REMOTE_WIFI_RECORD_FILE)} 2>/dev/null || true)
if [ -z "$record_dir" ]; then
  echo WIFI_RECORD_DIR_MISSING
  exit 2
fi
echo "$record_dir" > {shell_quote(REMOTE_LIVE_RECORD_FILE)}
if [ -s {shell_quote(REMOTE_VIEWER_PID)} ]; then
  old=$(cat {shell_quote(REMOTE_VIEWER_PID)} 2>/dev/null || true)
  if [ -n "$old" ] && [ -d "/proc/$old" ]; then
    kill "$old" 2>/dev/null || true
    sleep 1
  fi
fi
nohup python3 {shell_quote(REMOTE_VIEWER)} --host 0.0.0.0 --port {args.port} > {shell_quote(REMOTE_VIEWER_LOG)} 2>&1 &
pid=$!
echo "$pid" > {shell_quote(REMOTE_VIEWER_PID)}
sleep 1
echo VM_VIEWER_PID "$pid"
echo VIEWER_URL http://{args.vm_host}:{args.port}/
echo RECORD_DIR "$record_dir"
tail -20 {shell_quote(REMOTE_VIEWER_LOG)} 2>/dev/null || true
''')}"""


def viewer_status_command(args: argparse.Namespace) -> str:
    return f"""bash -lc {shell_quote(f'''
echo VM_VIEWER_URL http://{args.vm_host}:{args.port}/
echo VM_VIEWER_PROCESS
ps -eo pid,cmd | grep -E "[p]arking_live_viewer.py" || true
echo VM_RECORD_DIR
cat {shell_quote(REMOTE_LIVE_RECORD_FILE)} 2>/dev/null || true
echo VM_VIEWER_LOG_TAIL
tail -30 {shell_quote(REMOTE_VIEWER_LOG)} 2>/dev/null || true
echo VM_PREVIEW_COUNTS
python3 - <<'PY'
from pathlib import Path
import json
record_file = Path("{REMOTE_LIVE_RECORD_FILE}")
if not record_file.exists():
    print("record_file_missing")
    raise SystemExit(0)
root = Path(record_file.read_text(errors="replace").strip())
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
''')}"""


def viewer_stop_command() -> str:
    return f"""bash -lc {shell_quote(f'''
if [ -s {shell_quote(REMOTE_VIEWER_PID)} ]; then
  pid=$(cat {shell_quote(REMOTE_VIEWER_PID)} 2>/dev/null || true)
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    kill "$pid" 2>/dev/null || true
  fi
fi
rm -f {shell_quote(REMOTE_VIEWER_PID)}
echo VM_VIEWER_STOPPED
''')}"""


def fetch_latest_preview(args: argparse.Namespace) -> Path | None:
    try:
        import paramiko
    except ImportError:
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.vm_host,
        username=args.vm_user,
        password=args.vm_password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(REMOTE_LIVE_RECORD_FILE, "r") as handle:
                root = handle.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return None
        candidates: list[str] = []
        for subdir, suffixes in [
            ("session_*/preview", (".jpg",)),
            ("session_*/camera_frames", (".jpg",)),
            ("session_*/dtof_preview", (".png",)),
        ]:
            command = f"find {shell_quote(root)}/{subdir} -type f 2>/dev/null | sort | tail -1"
            _stdin, stdout, _stderr = client.exec_command(command, timeout=10)
            path = stdout.read().decode("utf-8", errors="replace").strip()
            if path and path.lower().endswith(suffixes):
                candidates.append(path)
        if not candidates:
            return None
        remote = candidates[0]
        local = LOG_DIR / f"wifi_live_preview_latest{Path(remote).suffix or '.jpg'}"
        sftp.get(remote, str(local))
        return local
    finally:
        try:
            sftp.close()
        except Exception:
            pass
        client.close()


def do_start(args: argparse.Namespace) -> int:
    print("=== Upload VM web viewer ===\n")
    rc = upload_viewer(args)
    if rc != 0:
        return rc
    print("\n=== Start Wi-Fi sensor chain ===\n")
    rc = wifi_manager(args, "start")
    if rc != 0:
        return rc
    print("\n=== Start VM web viewer ===\n")
    rc = vm_run(args, viewer_start_command(args)).returncode
    if rc != 0:
        return rc
    print("\n=== Wait for preview images ===\n")
    time.sleep(args.warmup_sec)
    return do_status(args)


def do_status(args: argparse.Namespace) -> int:
    print("=== Wi-Fi sensor health ===\n")
    wifi_manager(args, "health")
    print("\n=== VM web viewer status ===\n")
    rc = vm_run(args, viewer_status_command(args)).returncode
    preview = fetch_latest_preview(args)
    if preview:
        print(f"\nLOCAL_PREVIEW {preview}")
    else:
        print("\nLOCAL_PREVIEW not_ready")
    print(f"VIEWER_URL http://{args.vm_host}:{args.port}/")
    return rc


def do_stop(args: argparse.Namespace) -> int:
    print("=== Stop VM web viewer ===\n")
    vm_run(args, viewer_stop_command())
    print("\n=== Stop Wi-Fi sensor chain ===\n")
    return wifi_manager(args, "stop")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    parser.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    parser.add_argument("--vm-user", default=DEFAULT_VM_USER)
    parser.add_argument("--vm-password", default=DEFAULT_VM_PASSWORD)
    parser.add_argument("--vm-timeout", type=float, default=120.0)
    parser.add_argument("--manager-timeout", type=float, default=240.0)
    parser.add_argument("--board-host", default="")
    parser.add_argument("--host-forward-ip", default="")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--warmup-sec", type=float, default=15.0)
    parser.add_argument("--preview-stride", type=int, default=1)
    parser.add_argument("--camera-scale", default="0.35")
    parser.add_argument("--camera-backend", default="ffmpeg_mjpeg", choices=["ffmpeg_mjpeg", "opencv"])
    parser.add_argument("--camera-jpeg-quality", type=int, default=85)
    parser.add_argument("--force-restart", action="store_true", help="Restart the board/VM perception chain so a changed host IP is applied.")
    parser.add_argument("--publish-camera-raw", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    actions = {
        "start": do_start,
        "status": do_status,
        "stop": do_stop,
    }
    return actions[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
