#!/usr/bin/env python3
"""Start/status/stop the no-install Foxglove-lite visualization server on VM."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
LITE_SERVER = ROOT / "tools" / "vm_foxglove_lite_server.py"

REMOTE_SERVER = "/home/ebaina/parking_foxglove_lite_server.py"
REMOTE_PID = "/tmp/parking_foxglove_lite.pid"
REMOTE_LOG = "/tmp/parking_foxglove_lite.log"


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
    return run_command(vm_base(args) + ["run", "--allow-risk", command], timeout or args.vm_timeout)


def upload(args: argparse.Namespace) -> int:
    return run_command(
        vm_base(args) + ["put-text", "--allow-risk", str(LITE_SERVER), REMOTE_SERVER],
        args.vm_timeout,
    ).returncode


def start_command(args: argparse.Namespace) -> str:
    return f"""bash -lc {shell_quote(f'''
set -e
if [ -s {shell_quote(REMOTE_PID)} ]; then
  old=$(cat {shell_quote(REMOTE_PID)} 2>/dev/null || true)
  if [ -n "$old" ] && [ -d "/proc/$old" ]; then
    echo FOXGLOVE_LITE_ALREADY_RUNNING "$old"
    echo WS_URL ws://{args.vm_host}:{args.port}
    exit 0
  fi
fi
nohup python3 {shell_quote(REMOTE_SERVER)} --host 0.0.0.0 --port {args.port} --rate-hz {args.rate_hz} > {shell_quote(REMOTE_LOG)} 2>&1 &
pid=$!
echo "$pid" > {shell_quote(REMOTE_PID)}
sleep 1
echo FOXGLOVE_LITE_PID "$pid"
echo WS_URL ws://{args.vm_host}:{args.port}
tail -20 {shell_quote(REMOTE_LOG)} 2>/dev/null || true
''')}"""


def status_command(args: argparse.Namespace) -> str:
    return f"""bash -lc {shell_quote(f'''
echo WS_URL ws://{args.vm_host}:{args.port}
echo FOXGLOVE_LITE_PROCESS
ps -eo pid,cmd | grep -E "[p]arking_foxglove_lite_server.py" || true
echo FOXGLOVE_LITE_LOG_TAIL
tail -30 {shell_quote(REMOTE_LOG)} 2>/dev/null || true
echo FOXGLOVE_LITE_RECORD_DIR
cat /tmp/parking_sensor_link/parking_record_dir 2>/dev/null || true
''')}"""


def stop_command() -> str:
    return f"""bash -lc {shell_quote(f'''
if [ -s {shell_quote(REMOTE_PID)} ]; then
  pid=$(cat {shell_quote(REMOTE_PID)} 2>/dev/null || true)
  if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
    kill "$pid" 2>/dev/null || true
  fi
fi
orphans=$(ps -eo pid,args | awk '/parking_foxglove_lite_server.py/ && !/awk/ {{print $1}}')
for pid in $orphans; do kill "$pid" 2>/dev/null || true; done
rm -f {shell_quote(REMOTE_PID)}
echo FOXGLOVE_LITE_STOPPED
''')}"""


def do_start(args: argparse.Namespace) -> int:
    print("=== Upload Foxglove-lite server ===\n")
    rc = upload(args)
    if rc != 0:
        return rc
    print("\n=== Start Foxglove-lite server ===\n")
    return vm_run(args, start_command(args)).returncode


def do_status(args: argparse.Namespace) -> int:
    print("=== Foxglove-lite status ===\n")
    return vm_run(args, status_command(args)).returncode


def do_stop(args: argparse.Namespace) -> int:
    print("=== Stop Foxglove-lite server ===\n")
    return vm_run(args, stop_command()).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    parser.add_argument("--vm-host", default="192.168.247.129")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--rate-hz", type=float, default=5.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return {
        "start": do_start,
        "status": do_status,
        "stop": do_stop,
    }[args.action](args)


if __name__ == "__main__":
    raise SystemExit(main())
