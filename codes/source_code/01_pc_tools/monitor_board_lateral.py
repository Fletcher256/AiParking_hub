#!/usr/bin/env python3
"""Live monitor for the board-side parking lateral estimate.

This is intentionally read-only: it SSHes to the board, tails the newest
`/tmp/parking*.jsonl` control log, and prints the newest pose containing
`lateral_cm`.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import paramiko


ROOT = Path(__file__).resolve().parents[1]


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _connect(host: str, user: str, password: str, timeout: float) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=timeout)
    return client


def _ssh_text(client: paramiko.SSHClient, command: str, timeout: float) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    del stdin
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def latest_log_path(client: paramiko.SSHClient, timeout: float) -> str:
    cmd = (
        "python3 - <<'PY'\n"
        "import glob, os\n"
        "paths=[]\n"
        "for pat in ('/tmp/parking*.jsonl','/opt/parking/autopark/logs/*parking*.jsonl'):\n"
        "    paths += [p for p in glob.glob(pat) if os.path.isfile(p)]\n"
        "paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)\n"
        "print(paths[0] if paths else '')\n"
        "PY"
    )
    rc, out, _err = _ssh_text(client, cmd, timeout)
    if rc != 0:
        return ""
    return out.strip().splitlines()[-1].strip() if out.strip() else ""


def tail_log(client: paramiko.SSHClient, path: str, lines: int, timeout: float) -> str:
    if not path:
        return ""
    # path comes from the board-side glob above; still quote minimally.
    quoted = "'" + path.replace("'", "'\"'\"'") + "'"
    rc, out, _err = _ssh_text(client, f"tail -n {int(lines)} {quoted}", timeout)
    if rc != 0:
        return ""
    return out


def extract_latest_pose(text: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        name = event.get("event")
        pose = None
        source = name
        step = event.get("steps")
        if name == "diy_path_initial_lock":
            pose = event.get("locked_initial_pose")
            step = 0
        elif name == "diy_path_step":
            pose = (
                event.get("estimated_pose_after_correction")
                or event.get("estimated_pose_after_odom")
                or event.get("estimated_pose_before")
            )
            step = event.get("steps") or event.get("step_index")
        elif name in ("diy_path_visual_correction", "diy_path_lateral_only_visual_correction"):
            pose = event.get("pose_after")
        elif name == "diy_path_stop":
            state = event.get("state") or {}
            pose = state.get("pose")
            source = f"{name}:{event.get('reason')}"
            step = state.get("steps")
        if not isinstance(pose, dict):
            continue
        lat = _float(pose.get("lateral_cm"))
        if lat is None:
            continue
        latest = {
            "event": name,
            "source": source,
            "step": step,
            "time_unix": event.get("time_unix"),
            "y_dist_cm": _float(pose.get("y_dist_cm")),
            "lateral_cm": lat,
            "heading_deg": _float(pose.get("heading_deg")),
            "raw_event": event,
        }
    return latest


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only live lateral monitor for board parking logs.")
    ap.add_argument("--host", default=os.environ.get("BOARD_HOST", "192.168.137.2"))
    ap.add_argument("--user", default=os.environ.get("BOARD_SSH_USER", "root"))
    ap.add_argument("--password", default=os.environ.get("BOARD_SSH_PASSWORD", "ebaina"))
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--tail-lines", type=int, default=600)
    ap.add_argument("--ssh-timeout", type=float, default=5.0)
    ap.add_argument("--no-clear", action="store_true")
    args = ap.parse_args()

    client: paramiko.SSHClient | None = None
    last_error = ""
    while True:
        try:
            if client is None:
                client = _connect(args.host, args.user, args.password, args.ssh_timeout)
            path = latest_log_path(client, args.ssh_timeout)
            text = tail_log(client, path, args.tail_lines, args.ssh_timeout) if path else ""
            pose = extract_latest_pose(text)
            if not args.no_clear:
                clear_screen()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print("BOARD LATERAL LIVE MONITOR  (read-only)")
            print(f"local_time: {now}")
            print(f"board: {args.user}@{args.host}")
            print(f"log: {path or '(no /tmp/parking*.jsonl found)'}")
            print("-" * 64)
            if pose:
                lat = pose["lateral_cm"]
                side = "left(<0)" if lat < 0 else ("right(>0)" if lat > 0 else "center")
                print(f"lateral_cm : {lat:8.3f}   {side}")
                print(f"y_dist_cm  : {pose['y_dist_cm'] if pose['y_dist_cm'] is not None else 'n/a'}")
                print(f"heading_deg: {pose['heading_deg'] if pose['heading_deg'] is not None else 'n/a'}")
                print(f"step       : {pose.get('step')}")
                print(f"source     : {pose.get('source')}")
                if pose.get("time_unix"):
                    age = time.time() - float(pose["time_unix"])
                    print(f"log_age_sec: {age:.1f}")
            else:
                print("lateral_cm : n/a")
                print("reason     : no pose with lateral_cm in latest log tail")
            if last_error:
                print("-" * 64)
                print(f"last_error : {last_error}")
                last_error = ""
            print("\nCtrl-C closes this monitor. It does not send motion commands.")
        except KeyboardInterrupt:
            break
        except Exception as exc:
            last_error = repr(exc)
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass
            client = None
            if not args.no_clear:
                clear_screen()
            print("BOARD LATERAL LIVE MONITOR  (read-only)")
            print(f"reconnecting after error: {last_error}")
        time.sleep(max(0.1, float(args.interval)))

    if client is not None:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
