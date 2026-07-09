#!/usr/bin/env python3
"""Toggle board-local OS08A20 H264 recording and extract 3 fps training frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import sys
import time
from typing import BinaryIO

import cv2
import paramiko


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "artifacts" / "board_training_video"
LOCAL_STATE = STATE_DIR / "state.json"
REMOTE_STATE_DIR = "/tmp/parking_board_video_record"
REMOTE_RECORD_DIR = "/opt/sample/camera_only/records"
REMOTE_SCRIPT = f"{REMOTE_STATE_DIR}/record_control.sh"
DEFAULT_BOARD_HOST = "172.20.10.2"
DEFAULT_VM_HOST = "192.168.247.129"


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def connect(host: str, user: str, password: str, port: int = 22) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=10, banner_timeout=10, auth_timeout=10)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: float = 120.0) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def read_state() -> dict[str, object]:
    if not LOCAL_STATE.exists():
        return {}
    try:
        return json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_state(payload: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upload_control_script(client: paramiko.SSHClient) -> None:
    script = r"""#!/bin/sh
set -eu

STATE_DIR="/tmp/parking_board_video_record"
RECORD_DIR="${RECORD_DIR:-/opt/sample/camera_only/records}"
BOARD_TARGET_IP="${BOARD_TARGET_IP:-172.20.10.10}"
ACTION="${1:-status}"

mkdir -p "$STATE_DIR" "$RECORD_DIR"

status() {
  pid="$(cat "$STATE_DIR/pid" 2>/dev/null || true)"
  out="$(cat "$STATE_DIR/out" 2>/dev/null || true)"
  log="$(cat "$STATE_DIR/log" 2>/dev/null || true)"
  stamp="$(cat "$STATE_DIR/stamp" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    echo "BOARD_RECORDING_RUNNING true"
    echo "BOARD_RECORDING_PID $pid"
  else
    echo "BOARD_RECORDING_RUNNING false"
    echo "BOARD_RECORDING_PID ${pid:-}"
  fi
  echo "BOARD_RECORD_FILE $out"
  echo "BOARD_LOG $log"
  echo "BOARD_STAMP $stamp"
}

stop_existing_camera() {
  for p in $(ps w | awk '/[s]ample_camera_rtsp/ {print $1}'); do
    kill -INT "$p" 2>/dev/null || true
  done
  sleep 1
  for p in $(ps w | awk '/[s]ample_camera_rtsp/ {print $1}'); do
    kill -TERM "$p" 2>/dev/null || true
  done
}

start_recording() {
  pid="$(cat "$STATE_DIR/pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    echo "BOARD_RECORDING_ALREADY_RUNNING $pid"
    status
    exit 0
  fi

  if [ ! -x /opt/sample/camera_only/sample_camera_rtsp ]; then
    echo "BOARD_CAMERA_BINARY_MISSING /opt/sample/camera_only/sample_camera_rtsp" >&2
    exit 3
  fi
  if ! strings /opt/sample/camera_only/sample_camera_rtsp 2>/dev/null | grep -q PARKING_RECORD_PATH; then
    echo "BOARD_CAMERA_BINARY_HAS_NO_RECORD_SWITCH" >&2
    exit 4
  fi

  stop_existing_camera

  stamp="$(date +%Y%m%d_%H%M%S)"
  out="$RECORD_DIR/camera_training_${stamp}.h264"
  log="$STATE_DIR/camera_training_${stamp}.log"

  nohup setsid sh -c "
    cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20 >/dev/null 2>&1 || true
    cd /opt/sample/camera_only
    tail -f /dev/null | env PARKING_RECORD_PATH='$out' ./sample_camera_rtsp 8 '$BOARD_TARGET_IP'
  " > "$log" 2>&1 &
  pid="$!"

  echo "$pid" > "$STATE_DIR/pid"
  echo "$out" > "$STATE_DIR/out"
  echo "$log" > "$STATE_DIR/log"
  echo "$stamp" > "$STATE_DIR/stamp"
  sleep 3
  if [ ! -d "/proc/$pid" ]; then
    echo "BOARD_RECORDING_START_FAILED $pid" >&2
    tail -80 "$log" 2>/dev/null || true
    exit 5
  fi

  echo "BOARD_RECORDING_STARTED $pid"
  status
}

stop_recording() {
  pid="$(cat "$STATE_DIR/pid" 2>/dev/null || true)"
  out="$(cat "$STATE_DIR/out" 2>/dev/null || true)"
  log="$(cat "$STATE_DIR/log" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    kill -INT "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
    sleep 4
    if [ -d "/proc/$pid" ]; then
      kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
      sleep 2
    fi
  fi
  echo "BOARD_RECORDING_STOPPED ${pid:-}"
  echo "BOARD_RECORD_FILE $out"
  echo "BOARD_LOG $log"
}

case "$ACTION" in
  start)
    start_recording
    ;;
  stop)
    stop_recording
    ;;
  status)
    status
    ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
"""
    rc, _out, err = run(client, f"mkdir -p {sh_quote(REMOTE_STATE_DIR)} && cat > {sh_quote(REMOTE_SCRIPT)} <<'EOF'\n{script}\nEOF\nchmod +x {sh_quote(REMOTE_SCRIPT)}", timeout=30)
    if rc != 0:
        raise RuntimeError(err)


def parse_remote_kv(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        if key.startswith("BOARD_"):
            result[key] = value.strip()
    return result


def remote_status(client: paramiko.SSHClient) -> dict[str, str]:
    upload_control_script(client)
    rc, out, err = run(client, f"{sh_quote(REMOTE_SCRIPT)} status", timeout=30)
    if rc != 0:
        raise RuntimeError(err or out)
    return parse_remote_kv(out)


def start(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        upload_control_script(client)
        env = f"RECORD_DIR={sh_quote(args.remote_record_dir)} BOARD_TARGET_IP={sh_quote(args.board_target_ip)}"
        rc, out, err = run(client, f"{env} {sh_quote(REMOTE_SCRIPT)} start", timeout=60)
        if rc != 0:
            print(err or out, file=sys.stderr)
            return rc
        info = parse_remote_kv(out)
        write_state({
            "status": "running",
            "board_host": args.board_host,
            "remote_file": info.get("BOARD_RECORD_FILE", ""),
            "remote_log": info.get("BOARD_LOG", ""),
            "pid": info.get("BOARD_RECORDING_PID", ""),
            "started_unix": time.time(),
        })
        print(out, end="")
        return 0
    finally:
        client.close()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_file(sftp: paramiko.SFTPClient, remote_path: str, local_path: Path) -> bool:
    if not remote_path:
        return False
    try:
        sftp.stat(remote_path)
    except OSError:
        return False
    ensure_dir(local_path.parent)
    sftp.get(remote_path, str(local_path))
    return True


def remote_file_exists(client: paramiko.SSHClient, remote_path: str) -> bool:
    if not remote_path:
        return False
    rc, _out, _err = run(client, f"test -f {sh_quote(remote_path)}", timeout=30)
    return rc == 0


def stream_cat_to_file(client: paramiko.SSHClient, remote_path: str, local_path: Path) -> bool:
    if not remote_file_exists(client, remote_path):
        return False
    ensure_dir(local_path.parent)
    channel = client.get_transport().open_session()
    channel.exec_command(f"cat {sh_quote(remote_path)}")
    with local_path.open("wb") as dst:
        while True:
            if channel.recv_ready():
                dst.write(channel.recv(1024 * 1024))
                continue
            if channel.recv_stderr_ready():
                _ = channel.recv_stderr(4096)
            if channel.exit_status_ready():
                while channel.recv_ready():
                    dst.write(channel.recv(1024 * 1024))
                break
            time.sleep(0.05)
    return channel.recv_exit_status() == 0


def download_remote_file(client: paramiko.SSHClient, remote_path: str, local_path: Path) -> bool:
    if not remote_path:
        return False
    try:
        sftp = client.open_sftp()
    except Exception:
        return stream_cat_to_file(client, remote_path, local_path)
    try:
        return download_file(sftp, remote_path, local_path)
    finally:
        sftp.close()


def local_cv2_extract(video_path: Path, frames_dir: Path, fps: float) -> dict[str, object]:
    ensure_dir(frames_dir)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"ok": False, "reason": "cv2_open_failed", "saved_frames": 0}
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not source_fps or source_fps <= 0 or source_fps > 240:
        source_fps = 30.0
    interval = max(1.0 / fps, 0.001)
    next_t = 0.0
    frame_idx = 0
    saved = 0
    frames_json = frames_dir.parent / "frames.jsonl"
    with frames_json.open("w", encoding="utf-8") as fh:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / source_fps
            if t + 1e-9 >= next_t:
                name = f"frame_{saved + 1:06d}.jpg"
                out = frames_dir / name
                cv2.imwrite(str(out), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                fh.write(json.dumps({"file": f"images/{name}", "time_sec": t, "source_frame": frame_idx}) + "\n")
                saved += 1
                next_t += interval
            frame_idx += 1
    cap.release()
    return {"ok": saved > 0, "source_fps": source_fps, "read_frames": frame_idx, "saved_frames": saved}


def vm_ffmpeg_extract(args: argparse.Namespace, local_h264: Path, local_dir: Path, fps: float) -> dict[str, object]:
    vm = connect(args.vm_host, args.vm_user, args.vm_password)
    session = local_dir.name
    remote_root = f"/tmp/parking_board_video_extract/{session}"
    remote_in = f"{remote_root}/{local_h264.name}"
    remote_mp4 = f"{remote_root}/{local_h264.stem}.mp4"
    remote_frames = f"{remote_root}/images"
    try:
        rc, out, err = run(vm, f"rm -rf {sh_quote(remote_root)} && mkdir -p {sh_quote(remote_frames)}", timeout=30)
        if rc != 0:
            return {"ok": False, "reason": err or out}
        sftp = vm.open_sftp()
        try:
            sftp.put(str(local_h264), remote_in)
        finally:
            sftp.close()
        command = (
            f"ffmpeg -hide_banner -loglevel error -fflags +genpts -r 30 -i {sh_quote(remote_in)} "
            f"-c:v copy -movflags +faststart {sh_quote(remote_mp4)} && "
            f"ffmpeg -hide_banner -loglevel error -fflags +genpts -r 30 -i {sh_quote(remote_in)} "
            f"-vf fps={fps:g} -q:v 2 {sh_quote(remote_frames + '/frame_%06d.jpg')}"
        )
        rc, out, err = run(vm, command, timeout=600)
        if rc != 0:
            return {"ok": False, "reason": err or out}
        sftp = vm.open_sftp()
        count = 0
        try:
            mp4_local = local_dir / f"{local_h264.stem}.mp4"
            sftp.get(remote_mp4, str(mp4_local))
            frames_dir = local_dir / "images"
            ensure_dir(frames_dir)
            for name in sftp.listdir(remote_frames):
                if name.lower().endswith(".jpg"):
                    sftp.get(posixpath.join(remote_frames, name), str(frames_dir / name))
                    count += 1
        finally:
            sftp.close()
        run(vm, f"rm -rf {sh_quote(remote_root)}", timeout=30)
        frames_json = local_dir / "frames.jsonl"
        with frames_json.open("w", encoding="utf-8") as fh:
            for idx in range(1, count + 1):
                fh.write(json.dumps({"file": f"images/frame_{idx:06d}.jpg", "index": idx}) + "\n")
        return {"ok": count > 0, "method": "vm_ffmpeg", "saved_frames": count, "mp4": str(mp4_local)}
    finally:
        vm.close()


def remove_remote_files(client: paramiko.SSHClient, paths: list[str]) -> None:
    quoted = " ".join(sh_quote(path) for path in paths if path)
    if not quoted:
        return
    run(client, f"rm -f {quoted}", timeout=30)


def stop(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        upload_control_script(client)
        rc, out, err = run(client, f"{sh_quote(REMOTE_SCRIPT)} stop", timeout=90)
        if rc != 0:
            print(err or out, file=sys.stderr)
            return rc
        print(out, end="")
        info = parse_remote_kv(out)
        remote_file = info.get("BOARD_RECORD_FILE", "")
        remote_log = info.get("BOARD_LOG", "")
        if not remote_file:
            state = read_state()
            remote_file = str(state.get("remote_file", ""))
            remote_log = str(state.get("remote_log", ""))
        session_name = Path(remote_file).stem if remote_file else time.strftime("camera_training_%Y%m%d_%H%M%S")
        local_dir = STATE_DIR / session_name
        ensure_dir(local_dir)
        local_h264 = local_dir / f"{session_name}.h264"
        local_log = local_dir / "board_record.log"
        got_video = download_remote_file(client, remote_file, local_h264)
        got_log = download_remote_file(client, remote_log, local_log)
        if not got_video:
            print(f"BOARD_RECORD_FILE_MISSING {remote_file}", file=sys.stderr)
            return 6
        extract: dict[str, object] = {}
        if args.use_vm_ffmpeg:
            extract = vm_ffmpeg_extract(args, local_h264, local_dir, args.frame_fps)
        if not extract.get("ok"):
            extract = local_cv2_extract(local_h264, local_dir / "images", args.frame_fps)
        summary = {
            "remote_file": remote_file,
            "remote_log": remote_log,
            "local_h264": str(local_h264),
            "local_log": str(local_log) if got_log else "",
            "frame_fps": args.frame_fps,
            "extract": extract,
            "stopped_unix": time.time(),
        }
        (local_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.delete_remote:
            remove_remote_files(client, [remote_file, remote_log])
        write_state({"status": "stopped", "local_dir": str(local_dir), **summary})
        print(f"LOCAL_DIR {local_dir.resolve()}")
        print(f"LOCAL_H264 {local_h264.resolve()}")
        if extract.get("mp4"):
            print(f"LOCAL_MP4 {Path(str(extract['mp4'])).resolve()}")
        print(f"EXTRACT_METHOD {extract.get('method', 'local_cv2')}")
        print(f"SAVED_FRAMES {extract.get('saved_frames', 0)}")
        print(f"REMOTE_DELETED {str(args.delete_remote).lower()}")
        return 0
    finally:
        client.close()


def status(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        info = remote_status(client)
    finally:
        client.close()
    for key in ["BOARD_RECORDING_RUNNING", "BOARD_RECORDING_PID", "BOARD_RECORD_FILE", "BOARD_LOG", "BOARD_STAMP"]:
        print(f"{key} {info.get(key, '')}")
    local = read_state()
    if local:
        print("LOCAL_STATE", json.dumps(local, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="toggle", choices=["toggle", "start", "stop", "status"])
    parser.add_argument("--board-host", default=DEFAULT_BOARD_HOST)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-target-ip", default="172.20.10.10")
    parser.add_argument("--remote-record-dir", default=REMOTE_RECORD_DIR)
    parser.add_argument("--frame-fps", type=float, default=3.0)
    parser.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--use-vm-ffmpeg", action="store_true", default=True)
    parser.add_argument("--no-vm-ffmpeg", dest="use_vm_ffmpeg", action="store_false")
    parser.add_argument("--delete-remote", action="store_true", default=True)
    parser.add_argument("--keep-remote", dest="delete_remote", action="store_false")
    args = parser.parse_args()

    if args.action == "start":
        return start(args)
    if args.action == "stop":
        return stop(args)
    if args.action == "status":
        return status(args)

    board = connect(args.board_host, args.board_user, args.board_password)
    try:
        info = remote_status(board)
    finally:
        board.close()
    if info.get("BOARD_RECORDING_RUNNING") == "true":
        return stop(args)
    return start(args)


if __name__ == "__main__":
    raise SystemExit(main())
