#!/usr/bin/env python3
"""Toggle 3 fps training-frame capture from the VM ROS2 camera stream."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import posixpath
import sys
import time

import paramiko


ROOT = Path(__file__).resolve().parents[1]
LOCAL_STATE_DIR = ROOT / "artifacts" / "training_capture"
LOCAL_STATE = LOCAL_STATE_DIR / "state.json"
LOCAL_OUTPUT_ROOT = ROOT / "artifacts" / "training_frames"
REMOTE_SCRIPT = "/tmp/vm_training_frame_recorder.py"
REMOTE_STATE_DIR = "/tmp/parking_training_capture"
REMOTE_PID = f"{REMOTE_STATE_DIR}/recorder.pid"
REMOTE_SESSION = f"{REMOTE_STATE_DIR}/session_dir"
REMOTE_LOG = f"{REMOTE_STATE_DIR}/recorder.log"
REMOTE_OUTPUT_ROOT = "/home/ebaina/parking_training_frames"
DEFAULT_TOPIC = "/parking/camera/yolo_input_jpeg"


def connect(args: argparse.Namespace) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.vm_host,
        port=args.vm_port,
        username=args.vm_user,
        password=args.vm_password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: float = 60.0) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def upload_script(client: paramiko.SSHClient) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(ROOT / "tools" / "vm_training_frame_recorder.py"), REMOTE_SCRIPT)
    finally:
        sftp.close()


def remote_pid_status(client: paramiko.SSHClient) -> tuple[bool, str, str]:
    command = (
        f"mkdir -p {sh_quote(REMOTE_STATE_DIR)}; "
        f"pid=$(cat {sh_quote(REMOTE_PID)} 2>/dev/null || true); "
        "session=$(cat " + sh_quote(REMOTE_SESSION) + " 2>/dev/null || true); "
        'if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then '
        'echo "RUNNING $pid $session"; '
        "else "
        'echo "STOPPED ${pid:-none} $session"; '
        "fi"
    )
    rc, out, err = run(client, command)
    if rc != 0:
        raise RuntimeError(err or out)
    line = out.strip().splitlines()[-1] if out.strip() else "STOPPED none"
    parts = line.split(maxsplit=2)
    running = parts[0] == "RUNNING"
    pid = parts[1] if len(parts) > 1 else ""
    session = parts[2] if len(parts) > 2 else ""
    return running, pid, session


def write_local_state(payload: dict[str, object]) -> None:
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_local_state() -> dict[str, object]:
    if not LOCAL_STATE.exists():
        return {}
    try:
        return json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def start_capture(args: argparse.Namespace) -> int:
    client = connect(args)
    try:
        running, pid, session = remote_pid_status(client)
        if running:
            print(f"CAPTURE_ALREADY_RUNNING pid={pid}")
            print(f"REMOTE_SESSION {session}")
            return 0
        upload_script(client)
        session_name = time.strftime("capture_%Y%m%d_%H%M%S")
        remote_session = posixpath.join(args.remote_output_root, session_name)
        command = f"""
set -e
mkdir -p {sh_quote(REMOTE_STATE_DIR)} {sh_quote(remote_session)}
TOPIC={sh_quote(args.topic)} OUTPUT_DIR={sh_quote(remote_session)} FPS={sh_quote(str(args.fps))} nohup setsid bash -lc 'source /opt/ros/humble/setup.bash && source ~/parking_ws/install/setup.bash && exec python3 /tmp/vm_training_frame_recorder.py --topic "$TOPIC" --output-dir "$OUTPUT_DIR" --fps "$FPS"' > {sh_quote(REMOTE_LOG)} 2>&1 &
pid=$!
echo "$pid" > {sh_quote(REMOTE_PID)}
echo {sh_quote(remote_session)} > {sh_quote(REMOTE_SESSION)}
echo CAPTURE_STARTED "$pid"
echo REMOTE_SESSION {sh_quote(remote_session)}
echo REMOTE_LOG {sh_quote(REMOTE_LOG)}
"""
        rc, out, err = run(client, command, timeout=30)
        if rc != 0:
            print(err or out, file=sys.stderr)
            return rc
        write_local_state({
            "status": "running",
            "pid": out,
            "remote_session": remote_session,
            "topic": args.topic,
            "fps": args.fps,
            "started_unix": time.time(),
        })
        print(out, end="")
        print(f"LOCAL_TARGET {LOCAL_OUTPUT_ROOT / session_name}")
        return 0
    finally:
        client.close()


def ensure_local_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sftp_exists(sftp, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def download_tree(sftp, remote_dir: str, local_dir: Path) -> int:
    ensure_local_dir(local_dir)
    count = 0
    for item in sftp.listdir_attr(remote_dir):
        remote_path = posixpath.join(remote_dir, item.filename)
        local_path = local_dir / item.filename
        if item.st_mode & 0o040000:
            count += download_tree(sftp, remote_path, local_path)
        else:
            ensure_local_dir(local_path.parent)
            sftp.get(remote_path, str(local_path))
            count += 1
    return count


def stop_capture(args: argparse.Namespace) -> int:
    client = connect(args)
    try:
        running, pid, session = remote_pid_status(client)
        if not running and not session:
            print("CAPTURE_NOT_RUNNING")
            write_local_state({"status": "stopped", "stopped_unix": time.time()})
            return 0
        if running:
            command = f"""
pid={sh_quote(pid)}
kill -INT -$pid 2>/dev/null || kill -INT $pid 2>/dev/null || true
sleep 2
if [ -d "/proc/$pid" ]; then kill -TERM -$pid 2>/dev/null || kill -TERM $pid 2>/dev/null || true; fi
echo CAPTURE_STOPPED "$pid"
"""
            rc, out, err = run(client, command, timeout=20)
            if rc != 0:
                print(err or out, file=sys.stderr)
                return rc
            print(out, end="")
        sftp = client.open_sftp()
        try:
            if not session or not sftp_exists(sftp, session):
                print(f"REMOTE_SESSION_MISSING {session}")
                return 2
            session_name = posixpath.basename(session.rstrip("/"))
            local_dir = LOCAL_OUTPUT_ROOT / session_name
            count = download_tree(sftp, session, local_dir)
        finally:
            sftp.close()
        write_local_state({
            "status": "stopped",
            "remote_session": session,
            "local_dir": str(local_dir),
            "downloaded_files": count,
            "stopped_unix": time.time(),
        })
        print(f"REMOTE_SESSION {session}")
        print(f"LOCAL_DIR {local_dir.resolve()}")
        print(f"DOWNLOADED_FILES {count}")
        return 0
    finally:
        client.close()


def status_capture(args: argparse.Namespace) -> int:
    client = connect(args)
    try:
        running, pid, session = remote_pid_status(client)
    finally:
        client.close()
    print(f"REMOTE_RUNNING {str(running).lower()}")
    print(f"REMOTE_PID {pid}")
    print(f"REMOTE_SESSION {session}")
    local = read_local_state()
    if local:
        print("LOCAL_STATE", json.dumps(local, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="toggle", choices=["toggle", "start", "stop", "status"])
    parser.add_argument("--vm-host", default="192.168.247.129")
    parser.add_argument("--vm-port", type=int, default=22)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--fps", type=float, default=3.0)
    parser.add_argument("--remote-output-root", default=REMOTE_OUTPUT_ROOT)
    args = parser.parse_args()

    if args.action == "start":
        return start_capture(args)
    if args.action == "stop":
        return stop_capture(args)
    if args.action == "status":
        return status_capture(args)

    client = connect(args)
    try:
        running, _pid, _session = remote_pid_status(client)
    finally:
        client.close()
    if running:
        return stop_capture(args)
    return start_capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
