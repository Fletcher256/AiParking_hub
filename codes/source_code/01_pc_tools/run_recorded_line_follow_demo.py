#!/usr/bin/env python3
"""One-command recorded rollout_optimizer reverse-parking run.

This wrapper performs the same manually validated sequence:

1. Restart the existing board YOLO closed-loop process with RTSP/VENC enabled
   and PARKING_RECORD_PATH pointing at a unique H264 file.
2. Verify the H264 file is being written and YOLO detections are present.
3. Run the rollout_optimizer real-motion parking controller with --log-jsonl.
4. Stop recording and restore the normal non-recording YOLO process.
5. Download only the raw H264, controller JSONL, console log, and metadata.

It deliberately does not start the camera_only sample, does not create overlays,
does not transcode, and does not modify the controller configuration.

Real motion requires --allow-risk.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Iterable

import paramiko


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = os.environ.get("BOARD_SSH_HOST", "192.168.137.2")
DEFAULT_USER = os.environ.get("BOARD_SSH_USER", "root")
DEFAULT_PASSWORD = os.environ.get("BOARD_SSH_PASSWORD", "ebaina")
DEFAULT_AUTOPARK_DIR = "/opt/parking/autopark"
DEFAULT_PC_HOST = os.environ.get("PARKING_DEMO_PC_HOST", "192.168.137.1")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def now_stem() -> str:
    return time.strftime("demo_rollout_optimizer_%Y%m%d_%H%M%S")


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def connect(args: argparse.Namespace) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=args.ssh_timeout,
        banner_timeout=args.ssh_timeout,
        auth_timeout=args.ssh_timeout,
    )
    return client


def run_ssh(
    client: paramiko.SSHClient,
    command: str,
    *,
    timeout: float,
    label: str,
    stream: bool = True,
) -> tuple[int, str, str]:
    """Run a board command, optionally streaming output while capturing it."""
    print(f"\n===== {label} =====", flush=True)
    print(command, flush=True)
    chan = client.get_transport().open_session()
    chan.exec_command(command)
    start = time.time()
    out_parts: list[bytes] = []
    err_parts: list[bytes] = []
    while True:
        if chan.recv_ready():
            data = chan.recv(65536)
            if data:
                out_parts.append(data)
                if stream:
                    print(data.decode("utf-8", errors="replace"), end="", flush=True)
        if chan.recv_stderr_ready():
            data = chan.recv_stderr(65536)
            if data:
                err_parts.append(data)
                if stream:
                    print(data.decode("utf-8", errors="replace"), end="", file=sys.stderr, flush=True)
        if chan.exit_status_ready():
            while chan.recv_ready():
                data = chan.recv(65536)
                if data:
                    out_parts.append(data)
                    if stream:
                        print(data.decode("utf-8", errors="replace"), end="", flush=True)
            while chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if data:
                    err_parts.append(data)
                    if stream:
                        print(data.decode("utf-8", errors="replace"), end="", file=sys.stderr, flush=True)
            rc = chan.recv_exit_status()
            break
        if timeout > 0 and time.time() - start > timeout:
            chan.close()
            raise TimeoutError(f"{label} timed out after {timeout:.1f}s")
        time.sleep(0.05)
    out = b"".join(out_parts).decode("utf-8", errors="replace")
    err = b"".join(err_parts).decode("utf-8", errors="replace")
    print(f"\n[{label}] exit_code={rc}", flush=True)
    return rc, out, err


def read_remote_bytes(client: paramiko.SSHClient, command: str, timeout: float) -> bytes:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    data = stdout.read()
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError(f"remote command failed rc={rc}: {command}\n{err}")
    return data


def start_recording_cmd(args: argparse.Namespace) -> str:
    remote_h264 = f"{args.autopark_dir}/demo_records/{args.stem}.h264"
    remote_jsonl = f"{args.autopark_dir}/logs/{args.stem}.jsonl"
    return (
        f"mkdir -p {sh_quote(args.autopark_dir + '/demo_records')} "
        f"{sh_quote(args.autopark_dir + '/logs')} && "
        f"cd {sh_quote(args.autopark_dir)} && "
        # Remove only this run's target files so a retry cannot pass readiness
        # against stale data or append a new run onto an old artifact.
        f"rm -f {sh_quote(remote_h264)} {sh_quote(remote_jsonl)} && "
        "env "
        f"VM_HOST={sh_quote(args.pc_host)} "
        "LOCAL_CONTROLLER_HOST=127.0.0.1 "
        "LOCAL_CONTROLLER_PORT=24580 "
        "VM_DET_PORT=24580 "
        "VM_IMAGE_PORT=24581 "
        f"PARKING_YOLO_IMAGE_STRIDE={int(args.image_stride)} "
        "PARKING_YOLO_RUN_FOREVER=1 "
        "PARKING_YOLO_RTSP=1 "
        f"PARKING_RECORD_PATH={sh_quote(remote_h264)} "
        "ACTION=start "
        f"sh {sh_quote(args.autopark_dir + '/board_start_yolo_closed_loop_monitor.sh')}"
    )


def controller_cmd(args: argparse.Namespace) -> str:
    remote_jsonl = f"{args.autopark_dir}/logs/{args.stem}.jsonl"
    parts = [
        f"cd {sh_quote(args.autopark_dir)}",
        "&&",
        "python3 board_parking_controller.py",
        "--arm",
        "--strategy diy_first_frame_path_parking",
        "--diy-path-profile h1_structured_phase_parking",
        "--diy-path-structured-decision rollout_optimizer",
        f"--diy-path-max-total-cm {float(args.max_total_cm):g}",
        "--diy-path-rollout-optimizer-config-json /opt/parking/autopark/parking_rollout_optimizer_h1.json",
        "--diy-path-effective-target-y-cm 1.5",
        "--diy-path-success-lateral-tol-cm 2.0",
        "--diy-path-success-heading-tol-deg 3.0",
        "--diy-path-side-clearance-target-cm 3.0",
        "--diy-path-side-clearance-min-cm 2.0",
        "--diy-path-side-clearance-hard-block-cm 1.0",
        "--diy-path-side-clearance-weight 16.0",
        "--diy-path-near-side-min-clearance-cm 3.0",
        "--diy-path-near-side-clearance-weight 22.0",
        "--diy-path-bottom-depth-success-y-cm 2.0",
        "--diy-path-terminal-shuffle-heading-trigger-deg 3.0",
        "--diy-path-bottom-depth-success-heading-relax-cap-deg 3.0",
        f"--log-jsonl {sh_quote(remote_jsonl)}",
    ]
    if args.controller_extra:
        parts.append(args.controller_extra)
    return " ".join(parts)


def stop_recording_cmd(args: argparse.Namespace) -> str:
    remote_h264 = f"{args.autopark_dir}/demo_records/{args.stem}.h264"
    remote_jsonl = f"{args.autopark_dir}/logs/{args.stem}.jsonl"
    return (
        f"cd {sh_quote(args.autopark_dir)} && "
        f"ACTION=stop sh {sh_quote(args.autopark_dir + '/board_start_yolo_closed_loop_monitor.sh')}; "
        f"ls -lh {sh_quote(remote_h264)} {sh_quote(remote_jsonl)} 2>/dev/null || true"
    )


def restore_yolo_cmd(args: argparse.Namespace) -> str:
    return (
        f"cd {sh_quote(args.autopark_dir)} && "
        "env "
        f"VM_HOST={sh_quote(args.pc_host)} "
        "LOCAL_CONTROLLER_HOST=127.0.0.1 "
        "LOCAL_CONTROLLER_PORT=24580 "
        "VM_DET_PORT=24580 "
        "VM_IMAGE_PORT=24581 "
        f"PARKING_YOLO_IMAGE_STRIDE={int(args.image_stride)} "
        "PARKING_YOLO_RUN_FOREVER=1 "
        "ACTION=start "
        f"sh {sh_quote(args.autopark_dir + '/board_start_yolo_closed_loop_monitor.sh')}"
    )


def readiness_cmd(args: argparse.Namespace) -> str:
    remote_h264 = f"{args.autopark_dir}/demo_records/{args.stem}.h264"
    return f"""
sleep {int(args.readiness_warmup_sec)}
f={sh_quote(remote_h264)}
ps w | grep -E 'sample_parking_yolo|board_yolo_udp_tee' | grep -v grep
printf '\\nENV\\n'
ypid=$(ps w | awk '/[s]ample_parking_yolo/ {{print $1; exit}}')
tr '\\0' '\\n' < /proc/$ypid/environ 2>/dev/null | grep -E 'PARKING_RECORD_PATH|PARKING_YOLO_RTSP|PARKING_YOLO_(UDP|IMAGE|RUN|CONFIDENCE)' || true
printf '\\nLOG_RECORD\\n'
grep -i -E 'parking record enabled|open parking record|rtsp|venc|failed|fail|error' /tmp/parking_yolo_closed_loop_monitor.log 2>/dev/null | tail -80 || true
ready_wait=0
while [ "$ready_wait" -lt {int(args.readiness_wait_sec)} ]; do
  if [ -s "$f" ] && \
     grep -q 'parking record enabled' /tmp/parking_yolo_closed_loop_monitor.log 2>/dev/null && \
     grep -q 'parking_yolo_live_infer' /tmp/parking_yolo_closed_loop_monitor.log 2>/dev/null; then
    break
  fi
  sleep 1
  ready_wait=$((ready_wait + 1))
done
printf '\\nLAST_INFER\\n'
grep 'parking_yolo_live_infer' /tmp/parking_yolo_closed_loop_monitor.log 2>/dev/null | tail -12 || true
printf '\\nREC1\\n'
ls -lh "$f" 2>/dev/null || true
s1=$(stat -c %s "$f" 2>/dev/null || echo 0)
sleep {int(args.readiness_growth_sec)}
printf '\\nREC2\\n'
ls -lh "$f" 2>/dev/null || true
s2=$(stat -c %s "$f" 2>/dev/null || echo 0)
grew=no
if [ "$s2" -gt "$s1" ]; then grew=yes; fi
detect=no
if grep 'parking_yolo_live_infer' /tmp/parking_yolo_closed_loop_monitor.log 2>/dev/null | tail -12 | grep -q 'count=[1-9]'; then detect=yes; fi
printf '\\nREADY_CHECK h264_s1=%s h264_s2=%s grew=%s\\n' "$s1" "$s2" "$grew"
echo "READY_CHECK yolo_detect=$detect"
if [ "$grew" = "yes" ] && [ "$detect" = "yes" ]; then
  exit 0
fi
exit 12
""".strip()


def print_plan(args: argparse.Namespace) -> None:
    print("将执行以下板端命令（真实运动需 --allow-risk）：\n")
    print("1) 启动 YOLO + H264 录制：")
    print(start_recording_cmd(args))
    print("\n2) 准备检查：H264 文件增长 + YOLO count>=1")
    print(readiness_cmd(args))
    print("\n3) 实车 rollout_optimizer 倒车并写 JSONL：")
    print(controller_cmd(args))
    print("\n4) 停止录制并确认文件：")
    print(stop_recording_cmd(args))
    print("\n5) 恢复普通 YOLO：")
    print(restore_yolo_cmd(args))
    print("\n输出本地目录：")
    print(str((Path(args.local_root) / args.stem).resolve()))


def download_exact(
    client: paramiko.SSHClient,
    remote_path: str,
    local_path: Path,
    *,
    chunk_bytes: int,
) -> int:
    expected = int(
        read_remote_bytes(client, f"stat -c %s {sh_quote(remote_path)}", 20)
        .decode("utf-8", errors="replace")
        .strip()
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"DOWNLOAD_BEGIN {remote_path} bytes={expected} -> {local_path}", flush=True)
    with local_path.open("wb") as fh:
        got = 0
        chunks = (expected + chunk_bytes - 1) // chunk_bytes
        for idx in range(chunks):
            data = read_remote_bytes(
                client,
                f"dd if={sh_quote(remote_path)} bs={chunk_bytes} skip={idx} count=1 2>/dev/null",
                30,
            )
            fh.write(data)
            got += len(data)
            if (idx + 1) % 32 == 0 or idx + 1 == chunks:
                print(f"  chunk {idx + 1}/{chunks} got={got}", flush=True)
    actual = local_path.stat().st_size
    if actual != expected:
        raise RuntimeError(f"download size mismatch for {remote_path}: local={actual} expected={expected}")
    print(f"DOWNLOAD_DONE {local_path} bytes={actual}", flush=True)
    return actual


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_flow(args: argparse.Namespace) -> int:
    if not args.allow_risk:
        print_plan(args)
        print("\n未执行。确认实车安全后，加 --allow-risk 才会真正启动录制和倒车。", file=sys.stderr)
        return 4

    local_dir = Path(args.local_root) / args.stem
    local_dir.mkdir(parents=True, exist_ok=True)
    client = connect(args)
    console_out = ""
    console_err = ""
    controller_rc: int | None = None
    readiness_ok = False

    try:
        rc, out, err = run_ssh(
            client,
            start_recording_cmd(args),
            timeout=args.start_timeout,
            label="START_RECORDING",
        )
        if rc != 0:
            write_text(local_dir / f"{args.stem}.start.stdout.txt", out)
            write_text(local_dir / f"{args.stem}.start.stderr.txt", err)
            return rc

        rc, out, err = run_ssh(
            client,
            readiness_cmd(args),
            timeout=args.readiness_timeout,
            label="READINESS_CHECK",
        )
        write_text(local_dir / f"{args.stem}.readiness.txt", out + ("\n--- stderr ---\n" + err if err else ""))
        readiness_ok = rc == 0
        if not readiness_ok:
            print("READINESS_FAILED: 不执行实车倒车；将停止录制并恢复普通 YOLO。", file=sys.stderr, flush=True)
            return rc

        controller_rc, console_out, console_err = run_ssh(
            client,
            controller_cmd(args),
            timeout=args.controller_timeout,
            label="REAL_LINE_FOLLOW",
        )
        return controller_rc
    finally:
        # Always try to stop recording and restore the normal non-recording YOLO.
        try:
            rc, out, err = run_ssh(
                client,
                stop_recording_cmd(args),
                timeout=args.stop_timeout,
                label="STOP_RECORDING",
            )
            write_text(local_dir / f"{args.stem}.stop_recording.txt", out + ("\n--- stderr ---\n" + err if err else ""))
        except Exception as exc:  # noqa: BLE001 - best effort cleanup
            print(f"STOP_RECORDING_ERROR {exc}", file=sys.stderr, flush=True)
        try:
            rc, out, err = run_ssh(
                client,
                restore_yolo_cmd(args),
                timeout=args.restore_timeout,
                label="RESTORE_YOLO",
            )
            write_text(local_dir / f"{args.stem}.restore_yolo.txt", out + ("\n--- stderr ---\n" + err if err else ""))
        except Exception as exc:  # noqa: BLE001 - best effort cleanup
            print(f"RESTORE_YOLO_ERROR {exc}", file=sys.stderr, flush=True)

        # Save console output even if download later fails.
        if console_out or console_err:
            write_text(local_dir / f"{args.stem}.console.txt", console_out + ("\n--- stderr ---\n" + console_err if console_err else ""))

        if readiness_ok and not args.no_download:
            try:
                remote_h264 = f"{args.autopark_dir}/demo_records/{args.stem}.h264"
                remote_jsonl = f"{args.autopark_dir}/logs/{args.stem}.jsonl"
                h264_size = download_exact(
                    client,
                    remote_h264,
                    local_dir / f"{args.stem}.original.h264",
                    chunk_bytes=args.download_chunk_bytes,
                )
                jsonl_size = download_exact(
                    client,
                    remote_jsonl,
                    local_dir / f"{args.stem}.controller.jsonl",
                    chunk_bytes=args.download_chunk_bytes,
                )
                meta = {
                    "schema": "recorded_rollout_optimizer_demo.v1",
                    "stem": args.stem,
                    "board_host": args.host,
                    "remote_h264": remote_h264,
                    "remote_jsonl": remote_jsonl,
                    "local_dir": str(local_dir.resolve()),
                    "h264_size": h264_size,
                    "jsonl_size": jsonl_size,
                    "controller_exit_code": controller_rc,
                    "processed": False,
                    "note": "raw H264 and controller JSONL only; no overlay/transcode",
                }
                write_text(local_dir / "download_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception as exc:  # noqa: BLE001
                print(f"DOWNLOAD_ERROR {exc}", file=sys.stderr, flush=True)
        client.close()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASSWORD)
    ap.add_argument("--pc-host", default=DEFAULT_PC_HOST, help="Windows host IP receiving YOLO UDP side-channel.")
    ap.add_argument("--autopark-dir", default=DEFAULT_AUTOPARK_DIR)
    ap.add_argument("--stem", default=now_stem(), help="record/log basename without extension")
    ap.add_argument("--local-root", default=str(ROOT / "artifacts" / "raw_video_control_logs"))
    ap.add_argument("--image-stride", type=int, default=30)
    ap.add_argument("--max-total-cm", type=float, default=150.0)
    ap.add_argument("--controller-extra", default="", help="extra raw args appended to board_parking_controller.py")
    ap.add_argument("--allow-risk", action="store_true", help="actually run YOLO restart and real vehicle motion")
    ap.add_argument("--no-download", action="store_true", help="leave files on board only")
    ap.add_argument("--ssh-timeout", type=float, default=15.0)
    ap.add_argument("--start-timeout", type=float, default=90.0)
    ap.add_argument("--readiness-timeout", type=float, default=70.0)
    ap.add_argument("--readiness-warmup-sec", type=int, default=8)
    ap.add_argument("--readiness-wait-sec", type=int, default=20)
    ap.add_argument("--readiness-growth-sec", type=int, default=2)
    ap.add_argument("--controller-timeout", type=float, default=240.0)
    ap.add_argument("--stop-timeout", type=float, default=90.0)
    ap.add_argument("--restore-timeout", type=float, default=90.0)
    ap.add_argument("--download-chunk-bytes", type=int, default=1024 * 1024)
    return ap


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(run_flow(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

