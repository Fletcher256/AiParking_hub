#!/usr/bin/env python3
"""Stream live slot lateral from the board YOLO UDP feed.

Unlike monitor_board_lateral.py, this does not wait for a parking run/log.
It starts a read-only Python snippet on the board that listens to the YOLO UDP
feed and prints the current homography-derived slot pose continuously.

No motion commands are sent and no board files are modified.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import time

import paramiko


REMOTE_SNIPPET = r'''
import json, os, socket, sys, time, types

sys.path.insert(0, "/opt/parking/autopark")
import board_parking_controller as b

class Args(types.SimpleNamespace):
    pass

args = Args()
args.ground_homography_json = "/opt/parking/autopark/ground_homography.json"
args.camera_undistort_mask_polygon = False
args.camera_calibration_json = "/opt/parking/autopark/camera_intrinsics.json"
args.camera_undistort_iterations = 5
args.slot_class_names = getattr(b, "DEFAULT_SLOT_CLASS_NAMES", ["Parking", "parking", "parking_slot", "slot"])

# Keep all optional completeness/topology parameters at module defaults.
b.load_ground_homography_config(args)
b.normalize_camera_undistort_domain_for_homography(args)

listen_host = os.environ.get("MONITOR_LISTEN_HOST", "127.0.0.1")
listen_port = int(os.environ.get("MONITOR_LISTEN_PORT", "24580"))
interval = float(os.environ.get("MONITOR_INTERVAL", "0.25"))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
if hasattr(socket, "SO_REUSEPORT"):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
        pass
sock.bind((listen_host, listen_port))
sock.setblocking(False)

print("LIVE_LATERAL_MONITOR_READY host=%s port=%d H_version=%s domain=%s" % (
    listen_host,
    listen_port,
    (getattr(args, "_ground_homography_review", {}) or {}).get("version"),
    (getattr(args, "_ground_homography_review", {}) or {}).get("input_pixel_domain"),
), flush=True)

last = None
last_frame_time = None
last_print = 0.0
frame_count = 0

while True:
    raw = b.recv_latest(sock)
    now = time.time()
    if raw is not None:
        frame_count += 1
        try:
            infos = b.slot_infos_from_udp(raw, args.slot_class_names, completeness_args=args)
            if infos:
                info = max(infos, key=lambda item: float(item.get("confidence", 0.0)))
                last = {
                    "status": "ok",
                    "confidence": float(info.get("confidence", 0.0)),
                    "detection_count": int(raw.get("detection_count", len(raw.get("detections") or [])) or 0),
                    "mask_points": int(info.get("mask_polygon_point_count", 0) or 0),
                    "y_dist_cm": float(info.get("slot_y_dist_cm")),
                    "lateral_cm": float(info.get("slot_lateral_cm")),
                    "heading_deg": float(info.get("slot_heading_err_deg")),
                    "solver_status": info.get("solver_status"),
                    "quad_fit_status": info.get("quad_fit_status"),
                    "slot_completeness_status": info.get("slot_completeness_status"),
                    "line_risk": bool(info.get("line_risk", False)),
                    "frame_count": frame_count,
                }
                last_frame_time = now
            else:
                last = {
                    "status": "no_slot_info",
                    "detection_count": int(raw.get("detection_count", len(raw.get("detections") or [])) or 0),
                    "frame_count": frame_count,
                }
                last_frame_time = now
        except Exception as exc:
            last = {"status": "parse_error", "error": repr(exc), "frame_count": frame_count}
            last_frame_time = now

    if now - last_print >= interval:
        last_print = now
        if last is None:
            print("LIVE_LATERAL no_yolo_frame lateral=n/a y=n/a heading=n/a age=n/a", flush=True)
        else:
            age = None if last_frame_time is None else now - last_frame_time
            lat = last.get("lateral_cm")
            side = "n/a"
            if isinstance(lat, (int, float)):
                side = "left(<0)" if lat < 0 else ("right(>0)" if lat > 0 else "center")
            print(
                "LIVE_LATERAL status={status} lateral_cm={lat} side={side} y_dist_cm={y} heading_deg={head} "
                "conf={conf} det={det} mask_pts={mask} line_risk={risk} solver={solver} quad={quad} age_sec={age:.2f} frames={frames}".format(
                    status=last.get("status"),
                    lat=("%.3f" % lat) if isinstance(lat, (int, float)) else "n/a",
                    side=side,
                    y=("%.3f" % last.get("y_dist_cm")) if isinstance(last.get("y_dist_cm"), (int, float)) else "n/a",
                    head=("%.3f" % last.get("heading_deg")) if isinstance(last.get("heading_deg"), (int, float)) else "n/a",
                    conf=("%.4f" % last.get("confidence")) if isinstance(last.get("confidence"), (int, float)) else "n/a",
                    det=last.get("detection_count", "n/a"),
                    mask=last.get("mask_points", "n/a"),
                    risk=last.get("line_risk", "n/a"),
                    solver=last.get("solver_status", "n/a"),
                    quad=last.get("quad_fit_status", "n/a"),
                    age=age if age is not None else -1.0,
                    frames=last.get("frame_count", frame_count),
                ),
                flush=True,
            )
    time.sleep(0.02)
'''


def shell_quote_single(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_command(listen_host: str, listen_port: int, interval: float) -> str:
    env = (
        f"MONITOR_LISTEN_HOST={shell_quote_single(listen_host)} "
        f"MONITOR_LISTEN_PORT={int(listen_port)} "
        f"MONITOR_INTERVAL={float(interval)} "
    )
    return (
        "cd /opt/parking/autopark && "
        + env
        + "/usr/local/bin/python3 -u - <<'PY'\n"
        + REMOTE_SNIPPET
        + "\nPY"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Live board YOLO lateral monitor, no parking log required.")
    ap.add_argument("--host", default=os.environ.get("BOARD_HOST", "192.168.137.2"))
    ap.add_argument("--user", default=os.environ.get("BOARD_SSH_USER", "root"))
    ap.add_argument("--password", default=os.environ.get("BOARD_SSH_PASSWORD", "ebaina"))
    ap.add_argument("--listen-host", default="127.0.0.1")
    ap.add_argument("--listen-port", type=int, default=24580)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--ssh-timeout", type=float, default=5.0)
    args = ap.parse_args()

    print("BOARD YOLO LATERAL LIVE UDP MONITOR")
    print("read-only: no motion commands, no board file writes")
    print(f"board={args.user}@{args.host} udp={args.listen_host}:{args.listen_port}")
    print("Ctrl-C closes this terminal monitor.\n", flush=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=args.ssh_timeout)
    try:
        transport = client.get_transport()
        if transport is None:
            raise RuntimeError("missing SSH transport")
        chan = transport.open_session()
        chan.get_pty(term="xterm", width=160, height=40)
        chan.exec_command(remote_command(args.listen_host, args.listen_port, args.interval))
        while True:
            if chan.recv_ready():
                data = chan.recv(4096).decode("utf-8", errors="replace")
                print(data, end="", flush=True)
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(4096).decode("utf-8", errors="replace")
                print(data, end="", file=sys.stderr, flush=True)
            if chan.exit_status_ready():
                while chan.recv_ready():
                    print(chan.recv(4096).decode("utf-8", errors="replace"), end="", flush=True)
                rc = chan.recv_exit_status()
                print(f"\nREMOTE_MONITOR_EXIT rc={rc}", flush=True)
                return rc
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nclosing live lateral monitor...", flush=True)
        return 0
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
