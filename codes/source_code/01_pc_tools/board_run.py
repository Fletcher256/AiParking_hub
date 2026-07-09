#!/usr/bin/env python3
"""Run a shell command on the board via SSH and print output."""
from __future__ import annotations

import argparse
import os
import re
import sys

import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("BOARD_HOST", "172.20.10.2")
USER = "root"
PASS = "ebaina"
TIMEOUT = 120

RISK_PATTERNS = [
    r"\bsudo\b",
    r"\b(?:opkg|rpm|apt|apt-get|dnf|yum|snap)\b",
    r"\b(?:systemctl|service)\b",
    r"\b(?:reboot|shutdown|poweroff|halt)\b",
    r"\bdd\b",
    r"\b(?:mkfs|fdisk|parted)\b",
    r"\b(?:mount|umount)\b",
    r"\bresize2fs\b",
    r"\bgrowpart\b",
    r"\b(?:ip\s+(?:link|addr|route|rule)|ifconfig)\b",
    r"\b(?:iptables|nftables|ufw)\b",
    r"\b(?:docker|podman)\b",
    r"\brm\b",
    r"\bmv\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bpkill\b",
]

FORBIDDEN_CONTROL_PATTERNS = [
    r"\bcansend\b",
    r"\bcandump\b",
    r"\bcan_actuator\b",
    r"\bserial_actuator\b",
    r"\bmcu_bridge\b",
    r"\b(?:motor|steer|steering|brake|throttle)_?(?:ctrl|control|cmd|driver|actuator)\b",
]


def is_risky(command: str) -> tuple[bool, str | None]:
    for pattern in RISK_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return True, pattern
    return False, None


def forbidden_control_match(command: str) -> str | None:
    for pattern in FORBIDDEN_CONTROL_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return pattern
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one shell command on the Euler Pi / SS928 board over SSH.")
    parser.add_argument("--host", default=HOST, help="Board SSH host/IP. Defaults to BOARD_HOST or current Wi-Fi IP.")
    parser.add_argument(
        "--allow-risk",
        action="store_true",
        help="Allow important/dangerous board commands after explicit user approval.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Board shell command.")
    return parser

def main():
    args = build_parser().parse_args()
    cmd = " ".join(args.command).strip()
    if not cmd:
        print('usage: board_run.py [--allow-risk] "<board shell command>"', file=sys.stderr)
        return 2

    forbidden = forbidden_control_match(cmd)
    if forbidden:
        print("Refusing to send a board command that appears to target a vehicle control path.", file=sys.stderr)
        print(f"Matched forbidden control rule: {forbidden}", file=sys.stderr)
        return 5

    risky, pattern = is_risky(cmd)
    if risky and not args.allow_risk:
        print("Refusing to send a potentially important or dangerous board command.", file=sys.stderr)
        print(f"Matched risk rule: {pattern}", file=sys.stderr)
        print("Show the full command to the user, explain purpose and risk,", file=sys.stderr)
        print("then rerun with --allow-risk only after explicit approval.", file=sys.stderr)
        return 4

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(args.host, username=USER, password=PASS,
                       timeout=30, banner_timeout=30, auth_timeout=30)
        _, stdout, stderr = client.exec_command(cmd, timeout=TIMEOUT)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        return rc
    finally:
        client.close()

if __name__ == "__main__":
    raise SystemExit(main())
