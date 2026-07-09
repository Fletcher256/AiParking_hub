#!/usr/bin/env python3
"""Approval-gated STM32 ROS2 receiver check on the Ubuntu VM."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"


def cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def vm_tool_base(args: argparse.Namespace) -> list[str]:
    return [
        str(ROOT / ".venv" / "Scripts" / "python"),
        str(VM_TOOL),
        "--host",
        args.host,
        "--user",
        args.user,
        "--password",
        args.password,
        "--timeout",
        str(args.timeout),
    ]


def vm_check_command(args: argparse.Namespace) -> str:
    return f"""bash -lc '
set -e
source /opt/ros/humble/setup.bash
source ~/parking_ws/install/setup.bash
RUN_ID=$(date +%Y%m%d_%H%M%S)
RECORD_ROOT={args.record_dir}
RECORD_DIR="$RECORD_ROOT/run_$RUN_ID"
RUN_LOG=/tmp/parking_stm32_ros_check.log
rm -f "$RUN_LOG"
mkdir -p "$RECORD_DIR"
timeout {args.duration_sec} ros2 launch parking_bridge stm32.launch.py \\
  stm32_udp_port:={args.udp_port} \\
  record_dir:="$RECORD_DIR" \\
  enable_recording:=true > "$RUN_LOG" 2>&1 || true
echo STM32_ROS_LOG_BEGIN
tail -120 "$RUN_LOG" || true
echo STM32_ROS_LOG_END
RECORD_DIR_FOR_PY="$RECORD_DIR" python3 - <<\"PY\"
from pathlib import Path
import json
import os
import sys
root = Path(os.environ["RECORD_DIR_FOR_PY"])
sessions = sorted(root.glob("stm32_session_*"))
print("STM32_RECORD_ROOT", root)
print("STM32_SESSIONS", len(sessions))
if not sessions:
    print("STM32_ROS_CHECK FAIL no_session")
    raise SystemExit(2)
s = sessions[-1]
print("STM32_SESSION", s)
raw = s / "stm32_serial_raw.bin"
chunks = s / "stm32_serial_chunks.jsonl"
health = s / "stm32_health.jsonl"
raw_bytes = raw.stat().st_size if raw.exists() else 0
chunk_lines = chunks.read_text(errors="replace").splitlines() if chunks.exists() else []
health_lines = health.read_text(errors="replace").splitlines() if health.exists() else []
print("STM32_RAW_BYTES", raw_bytes)
print("STM32_CHUNK_LINES", len(chunk_lines))
print("STM32_HEALTH_LINES", len(health_lines))
last_health = None
for line in health_lines:
    if line.strip():
        try:
            last_health = json.loads(line)
        except Exception:
            pass
if last_health:
    print("STM32_LAST_OK", last_health.get("ok"))
    print("STM32_LAST_CHUNKS", last_health.get("chunks"))
    print("STM32_LAST_BYTES", last_health.get("bytes"))
last_chunk = None
for line in reversed(chunk_lines):
    if line.strip():
        try:
            last_chunk = json.loads(line)
        except Exception:
            pass
        break
last_board_meta = None
for candidate in (last_chunk, last_health.get("last") if last_health else None):
    if isinstance(candidate, dict) and candidate.get("serial_driver_mode"):
        last_board_meta = candidate
        break
if last_board_meta:
    print("STM32_SERIAL_DRIVER", last_board_meta.get("serial_driver"))
    print("STM32_SERIAL_DRIVER_MODE", last_board_meta.get("serial_driver_mode"))
    print("STM32_DRIVER_STATUS", last_board_meta.get("driver_status"))
sys.path.insert(0, str(Path.home() / "parking_ws" / "src" / "parking_bridge"))
try:
    from parking_bridge.stm32_protocol import analyze_bytes
except Exception as exc:
    print("STM32_PROTOCOL_ANALYSIS_IMPORT_ERROR", repr(exc))
else:
    analysis_path = s / "stm32_protocol_analysis.json"
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(errors="replace"))
    else:
        analysis = analyze_bytes(raw.read_bytes() if raw.exists() else b"")
        analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    print("STM32_PROTOCOL_ANALYSIS", analysis_path)
    print("STM32_PROTOCOL_CLASSIFICATION", analysis.get("classification"))
    print("STM32_PROTOCOL_FAMILY", analysis.get("protocol_family"))
    print("STM32_PRINTABLE_ASCII_RATIO", analysis.get("printable_ascii_ratio"))
    print("STM32_ENTROPY_BITS_PER_BYTE", analysis.get("entropy_bits_per_byte"))
ok = raw_bytes > 0 and len(chunk_lines) > 0
print("STM32_ROS_CHECK", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 3)
PY
'"""


def approval_text(args: argparse.Namespace) -> str:
    run = vm_tool_base(args) + ["--allow-risk", "run", "--allow-risk", vm_check_command(args)]
    return f"""This action needs explicit approval before execution.

Command:
{cmdline(run)}

Purpose:
- Start only the VM-side ROS2 STM32 UDP receiver for {args.duration_sec} seconds.
- Listen on UDP port {args.udp_port}.
- Record raw bytes, chunk metadata, and health under a fresh run directory below {args.record_dir}.
- Summarize whether STM32 raw bytes arrived through ROS2.

Risk:
- Writes /tmp/parking_stm32_ros_check.log on the VM.
- Writes STM32 session data under a fresh run directory below {args.record_dir} on the VM.
- Does not touch board serial, STM32, CAN, motor, steering, brake, throttle, or actuator commands.

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.100")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--udp-port", type=int, default=24680)
    parser.add_argument("--duration-sec", type=int, default=35)
    parser.add_argument("--record-dir", default="/home/ebaina/parking_sensor_records/stm32_ros_check")
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()

    if not args.allow_risk:
        print(approval_text(args))
        return 4

    result = run_command(
        vm_tool_base(args) + ["--allow-risk", "run", "--allow-risk", vm_check_command(args)],
        max(args.timeout, args.duration_sec + 60),
    )
    print(result.stdout, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
