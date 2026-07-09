#!/usr/bin/env python3
"""Board-local camera recording pipeline for YOLO training data.

Actions:
- start: start board-local H264 recording.
- stop: stop board recording only; keep board H264 file.
- status: show board recording state and record files.
- process: download H264 files, convert to MP4 on VM, extract strict 3 fps frames locally.
- stop-process: stop board recording, then process matching board H264 files.

This script only operates on the camera/RTSP/VENC recording path. It does not
start or talk to STM32, MCU bridge, CAN, serial actuator, or vehicle controls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import shutil
import socket
import sys
import tarfile
import time

import cv2
import paramiko

from board_training_video_toggle import (
    DEFAULT_BOARD_HOST,
    DEFAULT_VM_HOST,
    REMOTE_RECORD_DIR,
    REMOTE_SCRIPT,
    connect,
    parse_remote_kv,
    run,
    sh_quote,
    upload_control_script,
)


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / "artifacts" / "board_training_video"
COMBINED_PREFIX = "yolo_frames"
DEFAULT_GLOB = "camera_training_*.h264"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def remote_stat(client: paramiko.SSHClient, remote_path: str) -> int:
    rc, out, err = run(client, f"stat -c %s {sh_quote(remote_path)}", timeout=30)
    if rc != 0:
        raise RuntimeError(err or out or f"stat failed: {remote_path}")
    return int(out.strip().splitlines()[-1])


def list_remote_h264(client: paramiko.SSHClient, remote_dir: str, pattern: str) -> list[str]:
    # Keep this board-compatible: some deployed images have a minimal find
    # without -printf, while ls/glob expansion is available.
    command = f"cd {sh_quote(remote_dir)} 2>/dev/null && ls -1t {pattern} 2>/dev/null"
    rc, out, err = run(client, command, timeout=60)
    if rc != 0 and rc != 2:
        raise RuntimeError(err or out)
    files: list[str] = []
    for line in out.splitlines():
        name = line.strip()
        if name and not name.startswith(".") and name.endswith(".h264"):
            files.append(posixpath.join(remote_dir, name))
    return files


def cat_download_exact(client: paramiko.SSHClient, remote_path: str, local_path: Path) -> dict[str, object]:
    expected = remote_stat(client, remote_path)
    ensure_dir(local_path.parent)

    channel = client.get_transport().open_session()
    channel.settimeout(10)
    channel.exec_command(f"cat {sh_quote(remote_path)}")
    total = 0
    start = time.time()
    with local_path.open("wb") as dst:
        while True:
            try:
                data = channel.recv(65536)
            except socket.timeout:
                if channel.exit_status_ready():
                    break
                continue
            if not data:
                break
            dst.write(data)
            total += len(data)
    rc = channel.recv_exit_status()
    actual = local_path.stat().st_size if local_path.exists() else 0
    if rc != 0 or actual != expected:
        raise RuntimeError(f"download mismatch for {remote_path}: rc={rc} got={actual} expected={expected}")
    return {"remote": remote_path, "local": str(local_path), "bytes": actual, "elapsed_sec": time.time() - start}


def local_path_for_remote(remote_path: str) -> Path:
    stem = Path(remote_path).stem
    return LOCAL_ROOT / stem / f"{stem}.h264"


def download_records(args: argparse.Namespace, remote_files: list[str]) -> list[Path]:
    client = connect(args.board_host, args.board_user, args.board_password)
    downloaded: list[Path] = []
    try:
        for remote in remote_files:
            local = local_path_for_remote(remote)
            expected = remote_stat(client, remote)
            if local.exists() and local.stat().st_size == expected and not args.force_download:
                print(f"DOWNLOAD_SKIP size_ok local={local}")
                downloaded.append(local)
                continue
            print(f"DOWNLOAD_BEGIN remote={remote} expected={expected}")
            result = cat_download_exact(client, remote, local)
            print(f"DOWNLOAD_DONE bytes={result['bytes']} elapsed={result['elapsed_sec']:.1f}s local={local}")
            downloaded.append(local)
    finally:
        client.close()
    return downloaded


def vm_convert_one(args: argparse.Namespace, local_h264: Path, batch_remote_root: str) -> Path:
    local_mp4 = local_h264.with_suffix(".mp4")
    if local_mp4.exists() and local_mp4.stat().st_size > 0 and not args.force_convert:
        print(f"CONVERT_SKIP mp4_exists local={local_mp4}")
        return local_mp4

    vm = connect(args.vm_host, args.vm_user, args.vm_password)
    remote_dir = posixpath.join(batch_remote_root, local_h264.stem)
    remote_h264 = posixpath.join(remote_dir, local_h264.name)
    remote_mp4 = posixpath.join(remote_dir, local_mp4.name)
    try:
        rc, out, err = run(vm, f"mkdir -p {sh_quote(remote_dir)}", timeout=30)
        if rc != 0:
            raise RuntimeError(err or out)
        sftp = vm.open_sftp()
        try:
            print(f"UPLOAD_BEGIN vm={remote_h264}")
            sftp.put(str(local_h264), remote_h264)
            print(f"UPLOAD_DONE bytes={local_h264.stat().st_size}")
        finally:
            sftp.close()
        cmd = (
            "ffmpeg -y -hide_banner -loglevel error -fflags +genpts -r 30 "
            f"-i {sh_quote(remote_h264)} -c:v copy -movflags +faststart {sh_quote(remote_mp4)}"
        )
        print(f"CONVERT_BEGIN {local_h264.name}")
        rc, out, err = run(vm, cmd, timeout=args.vm_timeout)
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed for {local_h264}\nSTDOUT:{out}\nSTDERR:{err}")
        sftp = vm.open_sftp()
        try:
            sftp.get(remote_mp4, str(local_mp4))
        finally:
            sftp.close()
        print(f"CONVERT_DONE local={local_mp4} bytes={local_mp4.stat().st_size}")
        return local_mp4
    finally:
        vm.close()


def extract_strict_frames(mp4s: list[Path], output_dir: Path, target_fps: float, jpeg_quality: int) -> dict[str, object]:
    if output_dir.exists():
        backup = output_dir.with_name(f"{output_dir.name}_backup_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.move(str(output_dir), str(backup))
        print(f"BACKUP_OLD_FRAMES {backup}")
    images_dir = output_dir / "images"
    ensure_dir(images_dir)

    records: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "target_fps": target_fps,
        "frame_rule": "strict frame-index extraction: one frame every round(source_fps/target_fps) frames",
        "videos": [],
    }

    for mp4 in mp4s:
        cap = cv2.VideoCapture(str(mp4))
        if not cap.isOpened():
            raise RuntimeError(f"failed to open MP4: {mp4}")
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if source_fps <= 0 or source_fps > 240:
            source_fps = 30.0
        step = max(1, round(source_fps / target_fps))
        meta_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        saved = 0
        read_frames = 0
        start = time.time()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if read_frames % step == 0:
                name = f"{mp4.stem}_{saved + 1:06d}.jpg"
                out_path = images_dir / name
                cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
                records.append({
                    "file": f"images/{name}",
                    "source_video": mp4.name,
                    "source_frame": read_frames,
                    "source_time_sec": read_frames / source_fps,
                })
                saved += 1
            read_frames += 1
        cap.release()
        video_summary = {
            "mp4": str(mp4),
            "fps": source_fps,
            "step": step,
            "metadata_frames": meta_frames,
            "read_frames": read_frames,
            "saved_frames": saved,
            "duration_sec": read_frames / source_fps,
            "elapsed_sec": time.time() - start,
        }
        summary["videos"].append(video_summary)
        print(f"EXTRACT_DONE {mp4.name} read={read_frames} saved={saved} step={step}")

    with (output_dir / "frames.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary["saved_frames"] = len(records)
    summary["finished_unix"] = time.time()
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"EXTRACT_ALL_DONE output={output_dir} frames={len(records)}")
    return summary


def delete_remote_files(args: argparse.Namespace, remote_files: list[str]) -> None:
    if not remote_files:
        return
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        quoted = " ".join(sh_quote(path) for path in remote_files)
        rc, out, err = run(client, f"rm -f {quoted}", timeout=60)
        if rc != 0:
            raise RuntimeError(err or out)
        print(f"BOARD_FILES_DELETED count={len(remote_files)}")
    finally:
        client.close()


def cleanup_vm_temp(args: argparse.Namespace, remote_root: str) -> None:
    vm = connect(args.vm_host, args.vm_user, args.vm_password)
    try:
        rc, out, err = run(vm, f"rm -rf {sh_quote(remote_root)}", timeout=120)
        if rc != 0:
            raise RuntimeError(err or out)
        print(f"VM_TEMP_DELETED {remote_root}")
    finally:
        vm.close()


def action_start(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        upload_control_script(client)
        env = f"RECORD_DIR={sh_quote(args.remote_record_dir)} BOARD_TARGET_IP={sh_quote(args.board_target_ip)}"
        rc, out, err = run(client, f"{env} {sh_quote(REMOTE_SCRIPT)} start", timeout=60)
        print(out, end="")
        if rc != 0:
            print(err, file=sys.stderr, end="")
        return rc
    finally:
        client.close()


def action_stop(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        upload_control_script(client)
        rc, out, err = run(client, f"{sh_quote(REMOTE_SCRIPT)} stop", timeout=90)
        print(out, end="")
        if rc != 0:
            print(err, file=sys.stderr, end="")
        return rc
    finally:
        client.close()


def action_status(args: argparse.Namespace) -> int:
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        upload_control_script(client)
        rc, out, err = run(client, f"{sh_quote(REMOTE_SCRIPT)} status", timeout=30)
        print(out, end="")
        if rc != 0:
            print(err, file=sys.stderr, end="")
            return rc
        files = list_remote_h264(client, args.remote_record_dir, args.pattern)
        print("BOARD_H264_FILES_BEGIN")
        for path in files:
            print(path)
        print("BOARD_H264_FILES_END")
    finally:
        client.close()
    return 0


def resolve_remote_files(args: argparse.Namespace) -> list[str]:
    if args.remote_file:
        return args.remote_file
    client = connect(args.board_host, args.board_user, args.board_password)
    try:
        return list_remote_h264(client, args.remote_record_dir, args.pattern)
    finally:
        client.close()


def action_process(args: argparse.Namespace) -> int:
    remote_files = resolve_remote_files(args)
    if not remote_files:
        print("NO_REMOTE_H264_FILES")
        return 2
    print("PROCESS_FILES_BEGIN")
    for path in remote_files:
        print(path)
    print("PROCESS_FILES_END")

    local_h264s = download_records(args, remote_files)
    remote_batch_root = f"/tmp/parking_board_video_extract/batch_{time.strftime('%Y%m%d_%H%M%S')}"
    mp4s: list[Path] = []
    for local_h264 in local_h264s:
        mp4s.append(vm_convert_one(args, local_h264, remote_batch_root))

    output_name = args.output_name or f"{COMBINED_PREFIX}_{time.strftime('%Y%m%d_%H%M%S')}"
    output_dir = LOCAL_ROOT / output_name
    summary = extract_strict_frames(mp4s, output_dir, args.frame_fps, args.jpeg_quality)
    batch_summary = {
        "remote_files": remote_files,
        "local_h264s": [str(path) for path in local_h264s],
        "mp4s": [str(path) for path in mp4s],
        "frames_output": str(output_dir),
        "remote_batch_root": remote_batch_root,
        "extract_summary": summary,
    }
    (output_dir / "batch_summary.json").write_text(json.dumps(batch_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.cleanup_vm_temp:
        cleanup_vm_temp(args, remote_batch_root)
    else:
        print(f"VM_TEMP_KEPT {remote_batch_root}")
    if args.delete_board_after_success:
        delete_remote_files(args, remote_files)
    else:
        print("BOARD_FILES_KEPT")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "process", "stop-process"])
    parser.add_argument("--board-host", default=DEFAULT_BOARD_HOST)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-target-ip", default="172.20.10.10")
    parser.add_argument("--remote-record-dir", default=REMOTE_RECORD_DIR)
    parser.add_argument("--vm-host", default=DEFAULT_VM_HOST)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=3600.0)
    parser.add_argument("--pattern", default=DEFAULT_GLOB)
    parser.add_argument("--remote-file", action="append", help="Specific board H264 path; can be repeated.")
    parser.add_argument("--frame-fps", type=float, default=3.0)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--output-name", default="")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-convert", action="store_true")
    parser.add_argument("--cleanup-vm-temp", action="store_true")
    parser.add_argument("--delete-board-after-success", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.action == "start":
        return action_start(args)
    if args.action == "stop":
        return action_stop(args)
    if args.action == "status":
        return action_status(args)
    if args.action == "process":
        return action_process(args)
    if args.action == "stop-process":
        rc = action_stop(args)
        if rc != 0:
            return rc
        return action_process(args)
    raise AssertionError(args.action)


if __name__ == "__main__":
    raise SystemExit(main())
