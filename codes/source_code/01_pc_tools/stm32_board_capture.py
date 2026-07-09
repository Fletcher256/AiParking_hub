#!/usr/bin/env python3
"""Upload, run, fetch, and analyze a receive-only STM32 USB serial capture."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD_TOOL = ROOT / "tools" / "board_serial.py"
BOARD_CAPTURE_SCRIPT = ROOT / "tools" / "board_stm32_usb_serial_capture.sh"
ANALYZER_DIR = ROOT / "tools"
REMOTE_SCRIPT = "/tmp/board_stm32_usb_serial_capture.sh"
REMOTE_OUT_DIR = "/tmp/stm32_serial_records"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def board_tool_base(args: argparse.Namespace) -> list[str]:
    return [
        str(ROOT / ".venv" / "Scripts" / "python"),
        str(BOARD_TOOL),
        "--port",
        args.port,
        "--baud",
        str(args.board_baud),
        "--login-user",
        args.login_user,
        "--login-password",
        args.login_password,
        "--timeout",
        str(args.timeout),
    ]


def board_run_command(args: argparse.Namespace) -> str:
    parts = [
        "sh",
        REMOTE_SCRIPT,
        "--vid",
        args.vid,
        "--pid",
        args.pid,
        "--baud",
        str(args.stm32_baud),
        "--seconds",
        str(args.seconds),
        "--bytes",
        str(args.byte_limit),
        "--out-dir",
        REMOTE_OUT_DIR,
    ]
    if args.bind_mode == "generic":
        parts.append("--bind-generic")
    elif args.bind_mode == "no-bind":
        parts.append("--no-bind")
    return " ".join(shell_quote(part) for part in parts)


def approval_text(args: argparse.Namespace) -> str:
    upload = board_tool_base(args) + [
        "--allow-risk",
        "put-text",
        "--allow-risk",
        str(BOARD_CAPTURE_SCRIPT),
        REMOTE_SCRIPT,
    ]
    run = board_tool_base(args) + [
        "--allow-risk",
        "run",
        "--allow-risk",
        board_run_command(args),
    ]
    return f"""This action needs explicit approval before execution.

Command 1, upload board helper:
{cmdline(upload)}

Command 2, receive-only capture:
{cmdline(run)}

Purpose:
- Copy the receive-only board helper to /tmp.
- Configure the detected USB serial adapter for {args.stm32_baud} 8N1.
- Capture up to {args.byte_limit} bytes for {args.seconds} seconds.
- Save raw bytes, metadata, stty state, dmesg evidence, and hex preview.
- Fetch the raw capture back to this Windows workspace for analysis.

Risk:
- Writes one helper file under /tmp on the board.
- May write VID:PID {args.vid}:{args.pid} to usbserial_generic new_id if no serial device exists and bind mode allows it.
- Opens the USB serial device and changes its terminal settings.
- Some STM32 boards reset when a serial device is opened because of DTR/RTS wiring.
- Sends no bytes to STM32 and does not start MCU/CAN/motor/steering/brake/throttle control.

Rerun this tool with --allow-risk only after approval."""


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


def run_board(args: argparse.Namespace, command: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    parts = board_tool_base(args) + ["--allow-risk", "run", "--allow-risk", command]
    return run_command(parts, timeout or args.timeout)


def parse_meta(output: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in output.splitlines():
        if line == "HEX_PREVIEW":
            break
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            meta[key] = value.strip()
    return meta


def fetch_remote_file_b64(args: argparse.Namespace, remote_path: str) -> bytes:
    begin = "__STM32_CAPTURE_B64_BEGIN__"
    end = "__STM32_CAPTURE_B64_END__"
    command = (
        f"B=__STM32_CAPTURE_B64_BEGIN__; "
        f"E=__STM32_CAPTURE_B64_END__; "
        f"printf '%s\\n' \"$B\"; "
        f"base64 {shell_quote(remote_path)}; "
        f"printf '\\n%s\\n' \"$E\""
    )
    result = run_board(args, command, timeout=args.timeout)
    if result.returncode != 0:
        raise RuntimeError(f"failed to fetch {remote_path}:\n{result.stdout}")
    text = result.stdout
    start = text.rfind(begin)
    stop = text.rfind(end)
    if start < 0 or stop < 0 or stop <= start:
        raise RuntimeError(f"base64 markers not found while fetching {remote_path}")
    payload = text[start + len(begin):stop]
    payload = "".join(re.findall(r"[A-Za-z0-9+/=]+", payload))
    return base64.b64decode(payload)


def analyze_capture(raw_path: Path, seconds: int) -> dict[str, object]:
    sys.path.insert(0, str(ANALYZER_DIR))
    import stm32_serial_analyze

    data = raw_path.read_bytes()
    analysis = stm32_serial_analyze.analyze(data)
    analysis["capture_seconds"] = seconds
    analysis["byte_rate_Bps_estimate"] = (len(data) / seconds) if seconds else 0.0
    analysis["health"] = "ok_receiving" if len(data) else "no_bytes"
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--login-user", default="root")
    parser.add_argument("--login-password", default="ebaina")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--vid", default="1a86")
    parser.add_argument("--pid", default="7523")
    parser.add_argument("--stm32-baud", type=int, default=9600)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--byte-limit", type=int, default=4096)
    parser.add_argument("--bind-mode", choices=["auto", "generic", "no-bind"], default="auto")
    parser.add_argument("--local-dir", type=Path, default=ROOT / "artifacts" / "stm32_serial")
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()

    if not args.allow_risk:
        print(approval_text(args))
        return 4

    args.local_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.local_dir / f"capture_{stamp}"
    run_dir.mkdir()

    upload_parts = board_tool_base(args) + [
        "--allow-risk",
        "put-text",
        "--allow-risk",
        str(BOARD_CAPTURE_SCRIPT),
        REMOTE_SCRIPT,
    ]
    upload = run_command(upload_parts, args.timeout)
    (run_dir / "upload.log").write_text(upload.stdout, encoding="utf-8", errors="replace")
    if upload.returncode != 0:
        print(upload.stdout, end="")
        return upload.returncode

    capture = run_board(args, board_run_command(args), timeout=args.timeout)
    (run_dir / "capture.log").write_text(capture.stdout, encoding="utf-8", errors="replace")
    print(capture.stdout, end="")
    if capture.returncode != 0:
        return capture.returncode

    meta = parse_meta(capture.stdout)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    raw_remote = meta.get("raw")
    if not raw_remote:
        print("SERIAL_CAPTURE_CHECK=FAIL reason=missing_raw_path")
        return 2

    raw_bytes = fetch_remote_file_b64(args, raw_remote)
    raw_local = run_dir / Path(raw_remote).name
    raw_local.write_bytes(raw_bytes)

    analysis = analyze_capture(raw_local, args.seconds)
    (run_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("LOCAL_CAPTURE_DIR", run_dir)
    print("LOCAL_RAW", raw_local)
    print("ANALYSIS_JSON", run_dir / "analysis.json")
    print("BYTES", analysis["bytes"])
    print("CLASSIFICATION", analysis["classification"])
    print("HEALTH", analysis["health"])
    print("SERIAL_CAPTURE_CHECK", "PASS" if analysis["bytes"] else "FAIL")
    return 0 if analysis["bytes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
