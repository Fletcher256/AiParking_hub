#!/usr/bin/env python3
"""Keyboard trainer for the on-board parking policy learner.

Windows keys:
  right arrow: positive feedback (+)
  left arrow : negative feedback (-)
  space      : start a new rollout (r)
  0          : neutral feedback
  q          : quit learner

The car only moves when --allow-motion is supplied. Without it, the remote
learner runs in --dry-run mode and still accepts keyboard feedback.
"""

from __future__ import annotations

import argparse
import sys
import time


def ssh_connect(host: str, user: str, password: str, port: int, timeout: float):
    try:
        import paramiko
    except ImportError:
        print("paramiko is not installed. Use .venv\\Scripts\\python in this workspace.", file=sys.stderr)
        raise SystemExit(2)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=user,
        password=password,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def send_feedback(client, feedback_file: str, token: str) -> None:
    cmd = "printf %s > %s" % (q(token), q(feedback_file))
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=5.0)
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        err = stderr.read().decode("utf-8", errors="replace").strip()
        print("\n[feedback write failed] %s" % err, file=sys.stderr)


def read_key():
    try:
        import msvcrt
    except ImportError:
        ch = sys.stdin.read(1)
        return {"+": "+", "-": "-", " ": "r", "0": "0", "q": "q"}.get(ch)

    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        code = msvcrt.getch()
        if code == b"M":  # right arrow
            return "+"
        if code == b"K":  # left arrow
            return "-"
        return None
    if ch == b" ":
        return "r"
    try:
        text = ch.decode("ascii").lower()
    except UnicodeDecodeError:
        return None
    if text in ["+", "-", "0", "q"]:
        return text
    return None


def build_remote_command(args) -> str:
    parts = [
        "/usr/local/bin/python3",
        q(args.remote_controller),
        "--learn-policy",
        "--feedback-manual",
        "--feedback-auto",
        "--feedback-file",
        q(args.feedback_file),
        "--feedback-timeout-sec",
        str(args.feedback_timeout_sec),
        "--learn-episodes",
        str(args.episodes),
        "--learn-policy-file",
        q(args.policy_file),
        "--learn-epsilon",
        str(args.epsilon),
        "--learn-alpha",
        str(args.alpha),
        "--learn-max-total-cm",
        str(args.max_total_cm),
        "--learn-max-command-abs-d-cm",
        str(args.max_abs_d_cm),
        "--target-wait-sec",
        str(args.target_wait_sec),
        "--feedback-vision-timeout-sec",
        str(args.vision_timeout_sec),
        "--feedback-post-settle-sec",
        str(args.post_settle_sec),
        "--log-jsonl",
        q(args.remote_log_jsonl),
    ]
    if args.allow_motion:
        parts.append("--arm")
    else:
        parts.append("--dry-run")
    prefix = "mkdir -p %s; : > %s; " % (q(args.remote_work_dir), q(args.feedback_file))
    if args.allow_motion and args.create_arm_file:
        prefix += "trap 'rm -f /tmp/parking_armed' EXIT INT TERM; touch /tmp/parking_armed; "
    return prefix + " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.137.2")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="ebaina")
    ap.add_argument("--connect-timeout", type=float, default=8.0)
    ap.add_argument("--allow-motion", action="store_true",
                    help="allow real car movement; otherwise remote learner uses --dry-run")
    ap.add_argument("--create-arm-file", action="store_true",
                    help="create /tmp/parking_armed before starting real-motion training")
    ap.add_argument("--episodes", type=int, default=0,
                    help="0 = keep running until q; positive value is for bounded tests")
    ap.add_argument("--epsilon", type=float, default=0.25)
    ap.add_argument("--alpha", type=float, default=0.35)
    ap.add_argument("--max-total-cm", type=float, default=70.0)
    ap.add_argument("--max-abs-d-cm", type=float, default=7.0)
    ap.add_argument("--target-wait-sec", type=float, default=1.0)
    ap.add_argument("--vision-timeout-sec", type=float, default=5.0)
    ap.add_argument("--post-settle-sec", type=float, default=0.8)
    ap.add_argument("--feedback-timeout-sec", type=float, default=3600.0)
    ap.add_argument("--remote-controller", default="/opt/parking/autopark/board_parking_controller.py")
    ap.add_argument("--remote-work-dir", default="/opt/parking/autopark")
    ap.add_argument("--policy-file", default="/opt/parking/autopark/parking_policy.json")
    ap.add_argument("--feedback-file", default="/tmp/parking_feedback")
    ap.add_argument("--remote-log-jsonl", default="/tmp/parking_policy_keyboard_train.jsonl")
    args = ap.parse_args()

    if args.allow_motion and not args.create_arm_file:
        print("Refusing real motion without --create-arm-file.", file=sys.stderr)
        print("Use --allow-motion --create-arm-file only after confirming the car area is safe.", file=sys.stderr)
        return 4

    client = ssh_connect(args.host, args.user, args.password, args.port, args.connect_timeout)
    command = build_remote_command(args)
    print("Remote command:\n%s\n" % command)
    print("Keys: RIGHT=+  LEFT=-  SPACE=new rollout  0=neutral  q=quit")
    print("Mode: %s\n" % ("REAL MOTION" if args.allow_motion else "DRY RUN"))

    transport = client.get_transport()
    if transport is None:
        print("SSH transport not available.", file=sys.stderr)
        return 2
    channel = transport.open_session()
    channel.get_pty()
    channel.exec_command(command)

    try:
        while True:
            if channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                print(data, end="", flush=True)
            if channel.recv_stderr_ready():
                data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                print(data, end="", file=sys.stderr, flush=True)

            token = read_key()
            if token:
                send_feedback(client, args.feedback_file, token)
                labels = {"+": "positive", "-": "negative", "0": "neutral", "r": "restart", "q": "quit"}
                print("\n[feedback] %s (%s)\n" % (token, labels.get(token, token)), flush=True)
                if token == "q":
                    time.sleep(0.5)

            if channel.exit_status_ready():
                while channel.recv_ready():
                    print(channel.recv(4096).decode("utf-8", errors="replace"), end="", flush=True)
                rc = channel.recv_exit_status()
                print("\n[remote exited rc=%d]" % rc)
                return rc
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt: sending q and stopping learner...")
        send_feedback(client, args.feedback_file, "q")
        return 130
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
