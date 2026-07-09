#!/usr/bin/env python3
"""Probe VM ROS/Python components relevant to visualization."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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

    command = r'''bash -lc 'source /opt/ros/humble/setup.bash
echo ROS_PKGS
for p in foxglove_bridge rosbridge_server web_video_server image_transport compressed_image_transport mcap_vendor; do
  if ros2 pkg prefix "$p" >/dev/null 2>&1; then
    printf "HAS %s " "$p"
    ros2 pkg prefix "$p"
  else
    echo "MISSING $p"
  fi
done
echo PY_PKGS
python3 - <<'"'"'PY'"'"'
import importlib.util
mods = ["websockets", "aiohttp", "fastapi", "flask", "cv2", "numpy"]
for mod in mods:
    print(("HAS" if importlib.util.find_spec(mod) else "MISSING"), mod)
PY
echo BINARIES
for b in ffmpeg ffprobe ros2 rviz2 rqt_image_view; do
  if command -v "$b" >/dev/null 2>&1; then
    printf "HAS %s " "$b"
    command -v "$b"
  else
    echo "MISSING $b"
  fi
done
'
'''

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
        _stdin, stdout, stderr = client.exec_command(command, timeout=args.timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        print(out, end="")
        if err:
            print("--- stderr ---")
            print(err, end="")
        print(f"VM_COMPONENT_PROBE_EXIT_CODE {rc}")
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
