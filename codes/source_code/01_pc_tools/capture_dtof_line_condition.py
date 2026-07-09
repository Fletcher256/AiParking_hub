#!/usr/bin/env python3
"""Capture and download a dToF RAW12+LINE dump for one physical condition.

This wrapper starts the perception-only line-dump sample through
run_dtof_phase1_condition.py, then downloads dtof_line_dump_f*.bin/.meta from the
board into artifacts/. It does not start any actuator path.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
ARTIFACTS = ROOT / "artifacts"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
BOARD_DIR = "/opt/sample/official_dtof"
SAFE_BINARY_RE = re.compile(r"^sample_dtof[A-Za-z0-9_.-]*$")
SAFE_CASE_RE = re.compile(r"^\d+$")
SAFE_VM_IP_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


RemoteState = dict[str, tuple[int, int]]


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def validate_args(args: argparse.Namespace) -> str | None:
    if not SAFE_BINARY_RE.fullmatch(args.binary):
        return "--binary must be a sample_dtof* file name without path or shell characters"
    if not SAFE_CASE_RE.fullmatch(args.case):
        return "--case must be numeric"
    if not SAFE_VM_IP_RE.fullmatch(args.vm_ip):
        return "--vm-ip contains unsupported characters"
    if args.seconds <= 0 or args.seconds > 300:
        return "--seconds must be in range 1..300"
    if args.max_packets <= 0 or args.max_packets > 5000:
        return "--max-packets must be in range 1..5000"
    return None


def run(cmd: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
    return proc.wait()


def run_to_log(cmd: list[str], log_path: Path) -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.wait()


def print_analysis_summary(report: Path, mask_report: Path) -> None:
    line_data = json.loads(report.read_text(encoding="utf-8"))
    mask_data = json.loads(mask_report.read_text(encoding="utf-8"))
    frames = line_data.get("frames", {})
    print(f"LINE_ANALYSIS_JSON={report}")
    print(f"MASK_ANALYSIS_JSON={mask_report}")
    print(f"LINE_FRAME_COUNT={len(frames)}")
    for frame_id, frame in sorted(frames.items(), key=lambda item: item[0])[:6]:
        meta = frame.get("meta", {})
        sha = str(frame.get("sha256", ""))[:16]
        print(
            "LINE_FRAME frame=%s sha16=%s width=%s height=%s stride0=%s pixfmt=%s compress=%s row1_nonzero=%s"
            % (
                frame_id,
                sha,
                meta.get("width", ""),
                meta.get("height", ""),
                meta.get("stride0", ""),
                meta.get("pixel_format", ""),
                meta.get("compress_mode", ""),
                frame.get("row1_nonzero", ""),
            )
        )
    print(f"MASK_FRAME_COUNT={mask_data.get('frame_count', '')}")
    print(f"MASK_BEST_START_WORD_COUNTS={mask_data.get('best_start_word_counts', [])}")
    interpretation = mask_data.get("interpretation", {})
    if interpretation:
        print(f"MASK_MATCH_40X64={interpretation.get('mask_words_match_40x64', '')}")


def is_dump_name(name: str) -> bool:
    return re.fullmatch(r"dtof_line_dump_f\d{3}\.(bin|meta)", name) is not None


def sftp_collect_dump_state() -> RemoteState:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        BOARD_HOST,
        username=BOARD_USER,
        password=BOARD_PASS,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    try:
        sftp = client.open_sftp()
        try:
            state: RemoteState = {}
            for name in sorted(name for name in sftp.listdir(BOARD_DIR) if is_dump_name(name)):
                attrs = sftp.stat(f"{BOARD_DIR}/{name}")
                state[name] = (int(attrs.st_size), int(attrs.st_mtime))
            return state
        finally:
            sftp.close()
    finally:
        client.close()


def ssh_exec(client: paramiko.SSHClient, command: str, timeout: int = 60) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError(f"remote command failed rc={rc}: {command}\n{err}")
    return out


def ssh_collect_dump_state() -> RemoteState:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        BOARD_HOST,
        username=BOARD_USER,
        password=BOARD_PASS,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    try:
        quoted_dir = shlex.quote(BOARD_DIR)
        command = (
            f"cd {quoted_dir} && "
            "for f in dtof_line_dump_f*.bin dtof_line_dump_f*.meta; do "
            "[ -f \"$f\" ] || continue; "
            "set -- $(ls -ln \"$f\"); "
            "printf '%s %s %s\\n' \"$f\" \"$5\" \"$(stat -c %Y \"$f\" 2>/dev/null || echo 0)\"; "
            "done"
        )
        state: RemoteState = {}
        for line in ssh_exec(client, command).splitlines():
            parts = line.split()
            if len(parts) != 3 or not is_dump_name(parts[0]):
                continue
            state[parts[0]] = (int(parts[1]), int(parts[2]))
        return state
    finally:
        client.close()


def collect_dump_state() -> RemoteState:
    try:
        return sftp_collect_dump_state()
    except Exception as exc:
        print(f"SFTP_STATE_FALLBACK=ssh reason={type(exc).__name__}: {exc}")
        return ssh_collect_dump_state()


def sftp_download_dump_files(out_dir: Path, before_state: RemoteState | None) -> list[Path]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        BOARD_HOST,
        username=BOARD_USER,
        password=BOARD_PASS,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    try:
        sftp = client.open_sftp()
        try:
            downloaded: list[Path] = []
            skipped_stale: list[str] = []
            names = sorted(name for name in sftp.listdir(BOARD_DIR) if is_dump_name(name))
            for name in names:
                attrs = sftp.stat(f"{BOARD_DIR}/{name}")
                current = (int(attrs.st_size), int(attrs.st_mtime))
                if before_state is not None and before_state.get(name) == current:
                    skipped_stale.append(name)
                    continue
                local = out_dir / name
                sftp.get(f"{BOARD_DIR}/{name}", str(local))
                downloaded.append(local)
            if skipped_stale:
                print("SKIPPED_UNCHANGED_REMOTE_FILES=" + ",".join(skipped_stale))
            return downloaded
        finally:
            sftp.close()
    finally:
        client.close()


def ssh_download_dump_files(out_dir: Path, before_state: RemoteState | None) -> list[Path]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        BOARD_HOST,
        username=BOARD_USER,
        password=BOARD_PASS,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    try:
        current_state = ssh_collect_dump_state()
        downloaded: list[Path] = []
        skipped_stale: list[str] = []
        for name in sorted(current_state):
            current = current_state[name]
            if before_state is not None and before_state.get(name) == current:
                skipped_stale.append(name)
                continue
            remote_path = f"{BOARD_DIR}/{name}"
            data_b64 = ssh_exec(client, f"base64 {shlex.quote(remote_path)}", timeout=60)
            local = out_dir / name
            local.write_bytes(base64.b64decode("".join(data_b64.split())))
            downloaded.append(local)
        if skipped_stale:
            print("SKIPPED_UNCHANGED_REMOTE_FILES=" + ",".join(skipped_stale))
        return downloaded
    finally:
        client.close()


def download_dump_files(out_dir: Path, before_state: RemoteState | None) -> list[Path]:
    try:
        return sftp_download_dump_files(out_dir, before_state)
    except Exception as exc:
        print(f"SFTP_DOWNLOAD_FALLBACK=ssh_base64 reason={type(exc).__name__}: {exc}")
        return ssh_download_dump_files(out_dir, before_state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True, help="Physical condition label, e.g. clear, near30cm, covered")
    parser.add_argument("--binary", default="sample_dtof_official_line_dump_cp_dbg")
    parser.add_argument("--case", default="2")
    parser.add_argument("--seconds", type=int, default=8)
    parser.add_argument("--max-packets", type=int, default=20)
    parser.add_argument("--vm-ip", default="192.168.137.100")
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Only download current board dump files; do not start the sample.",
    )
    args = parser.parse_args()

    validation_error = validate_args(args)
    if validation_error:
        print(f"Invalid argument: {validation_error}", file=sys.stderr)
        return 2

    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = safe_name(args.condition)
    out_dir = ARTIFACTS / f"dtof_line_dump_{label}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    before_state: RemoteState | None = None
    if not args.skip_run:
        before_state = collect_dump_state()
        print(f"REMOTE_DUMP_FILES_BEFORE={len(before_state)}")
        cmd = [
            str(PYTHON),
            "tools/run_dtof_phase1_condition.py",
            "--condition",
            f"{label}_line_dump_cp_official",
            "--binary",
            args.binary,
            "--case",
            args.case,
            "--seconds",
            str(args.seconds),
            "--max-packets",
            str(args.max_packets),
            "--vm-ip",
            args.vm_ip,
        ]
        print("Running perception-only dToF line dump capture...")
        print(" ".join(cmd))
        rc = run(cmd)
        if rc != 0:
            print(f"capture command failed with rc={rc}", file=sys.stderr)
            return rc

    downloaded = download_dump_files(out_dir, before_state)
    manifest = out_dir / "capture_manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                f"condition={args.condition}",
                f"binary={args.binary}",
                f"case={args.case}",
                f"seconds={args.seconds}",
                f"max_packets={args.max_packets}",
                f"board_dir={BOARD_DIR}",
                f"remote_files_before={len(before_state) if before_state is not None else 'skip-run'}",
                "files=",
                *[path.name for path in downloaded],
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"ARTIFACT_DIR={out_dir}")
    print(f"DOWNLOADED_FILES={len(downloaded)}")
    if len(downloaded) == 0:
        print("No dump files were downloaded; check board log for DTOF_LINE_DUMP entries.", file=sys.stderr)
        return 1

    report = out_dir / "line_dump_analysis.json"
    report_stdout = out_dir / "line_dump_analysis.stdout.log"
    analyze_cmd = [
        str(PYTHON),
        "tools/analyze_dtof_line_dump.py",
        str(out_dir),
        "--out",
        str(report),
    ]
    print("Running single-condition analysis...")
    rc = run_to_log(analyze_cmd, report_stdout)
    print(f"LINE_ANALYSIS_STDOUT={report_stdout}")
    if rc != 0:
        return rc

    mask_report = out_dir / "line_mask_hypothesis_analysis.json"
    mask_stdout = out_dir / "line_mask_hypothesis_analysis.stdout.log"
    mask_cmd = [
        str(PYTHON),
        "tools/analyze_dtof_line_mask_hypothesis.py",
        str(out_dir),
        "--out",
        str(mask_report),
    ]
    print("Running mask-hypothesis analysis...")
    rc = run_to_log(mask_cmd, mask_stdout)
    print(f"MASK_ANALYSIS_STDOUT={mask_stdout}")
    if rc != 0:
        return rc
    print_analysis_summary(report, mask_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
