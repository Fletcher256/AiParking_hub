#!/usr/bin/env python3
"""Run the VM Foxglove-lite render check and download the dashboard PNG."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER_SCRIPT = ROOT / "tools" / "vm_foxglove_lite_render_check.py"
LOCAL_OUTPUT = ROOT / "logs" / "foxglove_lite_render_latest.png"
REMOTE_SCRIPT = "/tmp/vm_foxglove_lite_render_check.py"
REMOTE_OUTPUT = "/tmp/parking_foxglove_lite_render.png"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.247.129")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("LOCAL_MISSING paramiko")
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        sftp = client.open_sftp()
        sftp.put(str(RENDER_SCRIPT), REMOTE_SCRIPT)
        sftp.close()
        command = f"python3 {REMOTE_SCRIPT} --url ws://127.0.0.1:8765 --output {REMOTE_OUTPUT}"
        _stdin, stdout, stderr = client.exec_command(command, timeout=args.timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        print(out, end="")
        if err:
            print("--- stderr ---")
            print(err, end="")
        if rc != 0:
            print(f"FOXGLOVE_LITE_VISUAL_CHECK_EXIT_CODE {rc}")
            return rc
        LOCAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        sftp = client.open_sftp()
        sftp.get(REMOTE_OUTPUT, str(LOCAL_OUTPUT))
        sftp.close()
        print(f"LOCAL_RENDER {LOCAL_OUTPUT}")
        print("FOXGLOVE_LITE_VISUAL_CHECK_EXIT_CODE 0")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
