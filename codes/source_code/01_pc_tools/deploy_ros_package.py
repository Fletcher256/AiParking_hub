#!/usr/bin/env python3
"""Upload the local parking_bridge ROS2 package to the VM and build it."""

from __future__ import annotations

import os
import sys
import argparse

import paramiko


WS_SRC = "/home/ebaina/parking_ws/src"


def connect(host: str, user: str, password: str):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=user,
        password=password,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    return client


def run_raw(client, cmd, timeout=180):
    print(f"$ {cmd}")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    return rc


def upload_tree(client, local_root, remote_root):
    sftp = client.open_sftp()

    def ensure_dir(path):
        try:
            sftp.stat(path)
        except FileNotFoundError:
            parent = os.path.dirname(path)
            if parent and parent != path:
                ensure_dir(parent)
            sftp.mkdir(path)

    for dirpath, dirnames, filenames in os.walk(local_root):
        dirnames[:] = [
            d for d in dirnames
            if d not in {"__pycache__", ".git", "build", "install", "log"}
        ]
        rel = os.path.relpath(dirpath, local_root)
        remote_dir = remote_root if rel == "." else remote_root + "/" + rel.replace("\\", "/")
        ensure_dir(remote_dir)
        for fname in filenames:
            if fname.endswith((".pyc", ".pyo")):
                continue
            local_file = os.path.join(dirpath, fname)
            remote_file = remote_dir + "/" + fname
            print(f"  upload {local_file} -> {remote_file}")
            sftp.put(local_file, remote_file)

    sftp.close()


def approval_text(args: argparse.Namespace) -> str:
    return f"""This action needs explicit approval before execution.

Command:
.venv\\Scripts\\python tools\\deploy_ros_package.py --host {args.host} --user {args.user} --password {args.password} --allow-risk

Purpose:
- Upload the local ROS2 package ros/parking_bridge to the Ubuntu VM {args.user}@{args.host}.
- Build parking_bridge inside ~/parking_ws with colcon.
- Make the new STM32 UDP receiver node available to ros2 launch.

Risk:
- Writes files under /home/ebaina/parking_ws/src/parking_bridge on the VM.
- Writes colcon build/install/log output under /home/ebaina/parking_ws.
- Does not touch board serial, STM32, CAN, motor, steering, brake, throttle, or actuator commands.

Rerun with --allow-risk only after approval."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.100")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--allow-risk", action="store_true")
    args = parser.parse_args()
    if not args.allow_risk:
        print(approval_text(args))
        return 4

    local_pkg = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "ros", "parking_bridge")
    )
    remote_pkg = WS_SRC + "/parking_bridge"

    print(f"=== Uploading {local_pkg} -> {args.user}@{args.host}:{remote_pkg} ===")
    client = connect(args.host, args.user, args.password)
    try:
        upload_tree(client, local_pkg, remote_pkg)

        print("\n=== Building ROS2 package ===")
        rc = run_raw(
            client,
            "bash -lc 'cd ~/parking_ws && source /opt/ros/humble/setup.bash "
            "&& colcon build --packages-select parking_bridge 2>&1'",
            timeout=240,
        )
        if rc == 0:
            print("\nBuild successful")
            print("Run with: source ~/parking_ws/install/setup.bash && "
                  "ros2 launch parking_bridge parking.launch.py")
        else:
            print(f"\nBuild failed (rc={rc})")
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
