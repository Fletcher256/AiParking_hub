#!/usr/bin/env python3
"""SSH control helper for the Ubuntu VM (ebaina-virtual-machine)."""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_HOST = os.environ.get("VM_SSH_HOST", "192.168.247.129")
DEFAULT_USER = os.environ.get("VM_SSH_USER", "ebaina")
DEFAULT_PASSWORD = os.environ.get("VM_SSH_PASSWORD", "ebaina")
DEFAULT_PORT = int(os.environ.get("VM_SSH_PORT", "22"))
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RISK_PATTERNS = [
    r"\bsudo\b",
    r"\b(?:apt|apt-get|dnf|yum|snap)\b",
    r"\b(?:pip|pip3|npm|cargo)\b",
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
    r"\bcrontab\b",
    r"\bpasswd\b",
    r"\buserdel\b",
    r"\bkill\b",
    r"\bpkill\b",
]

SAFE_READONLY_COMMANDS = {
    "whoami",
    "hostname",
    "uname -a",
    "df -h",
    "free -h",
    "uptime",
    "pwd",
    "ls",
}


def _connect(host: str, port: int, user: str, password: str):
    try:
        import paramiko
    except ImportError:
        print(
            "paramiko is not installed. Run: .venv\\Scripts\\python -m pip install paramiko",
            file=sys.stderr,
        )
        raise SystemExit(2)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            port=port,
            username=user,
            password=password,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )
    except Exception as exc:
        print(f"Failed to connect to {user}@{host}:{port}: {exc}", file=sys.stderr)
        raise SystemExit(3)
    return client


def is_risky(command: str) -> tuple[bool, str | None]:
    if command.strip() in SAFE_READONLY_COMMANDS:
        return False, None
    for pattern in RISK_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return True, pattern
    return False, None


def require_safe(command: str, allow_risk: bool) -> None:
    risky, pattern = is_risky(command)
    if risky and not allow_risk:
        print("Refusing to send a potentially important or dangerous VM command.")
        print(f"Matched risk rule: {pattern}")
        print("Show the full command to the user, explain purpose and risk,")
        print("then rerun with --allow-risk only after explicit approval.")
        raise SystemExit(4)


def _log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"vm_ssh_{stamp}_{uuid.uuid4().hex[:8]}.log"


def cmd_run(args: argparse.Namespace) -> int:
    require_safe(args.command, args.allow_risk)
    log_path = _log_path()
    client = _connect(args.host, args.port, args.user, args.password)
    try:
        _stdin, stdout, stderr = client.exec_command(args.command, timeout=args.timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        log_path.write_text(
            f"CMD: {args.command}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n",
            encoding="utf-8",
        )
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        print(f"\n[vm_ssh_run] exit_code={rc} log={log_path}")
        return rc
    finally:
        client.close()


def cmd_put_text(args: argparse.Namespace) -> int:
    local_path = Path(args.local_file)
    remote = args.remote_file
    require_safe(f"cat > {remote}", args.allow_risk)
    log_path = _log_path()
    client = _connect(args.host, args.port, args.user, args.password)
    try:
        import paramiko
        sftp = client.open_sftp()
        sftp.put(str(local_path), remote)
        sftp.close()
        log_path.write_text(
            f"PUT: {local_path} -> {remote}\n",
            encoding="utf-8",
        )
        print(f"Uploaded {local_path} -> {remote}")
        print(f"\n[vm_ssh_run] exit_code=0 log={log_path}")
        return 0
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Ubuntu VM over SSH.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--timeout", default=60.0, type=float)
    parser.add_argument("--allow-risk", action="store_true")
    sub = parser.add_subparsers(dest="command_name", required=True)

    run_p = sub.add_parser("run", help="Run one shell command on the VM.")
    run_p.add_argument("--allow-risk", action="store_true", default=argparse.SUPPRESS)
    run_p.add_argument("command")
    run_p.set_defaults(func=cmd_run)

    put_p = sub.add_parser("put-text", help="Upload a local file to the VM via SFTP.")
    put_p.add_argument("--allow-risk", action="store_true", default=argparse.SUPPRESS)
    put_p.add_argument("local_file")
    put_p.add_argument("remote_file")
    put_p.set_defaults(func=cmd_put_text)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
