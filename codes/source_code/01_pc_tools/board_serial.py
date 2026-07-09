#!/usr/bin/env python3
"""Serial control helper for the Euler Pi / SS928 board."""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import textwrap
import time
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_PORT = os.environ.get("BOARD_SERIAL_PORT", "COM11")
DEFAULT_BAUD = int(os.environ.get("BOARD_SERIAL_BAUD", "115200"))
DEFAULT_LOGIN_USER = os.environ.get("BOARD_SERIAL_LOGIN_USER", "root")
DEFAULT_LOGIN_PASSWORD = os.environ.get("BOARD_SERIAL_LOGIN_PASSWORD", "")
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SAFE_READONLY_COMMANDS = {
    "findmnt -n -o SOURCE,FSTYPE,SIZE,AVAIL /",
    "readlink -f /dev/root || true",
    "cat /proc/partitions",
    "blkid || true",
    "lsblk -f || true",
    "mount | grep ' on / '",
}

RISK_PATTERNS = [
    r"\bsudo\b",
    r"\b(?:apt|apt-get|dnf|yum|opkg)\b",
    r"\b(?:pip|pip3|npm)\b",
    r"\b(?:systemctl|service)\b",
    r"\b(?:reboot|shutdown|poweroff)\b",
    r"\b(?:modprobe|insmod|rmmod)\b",
    r"\bdd\b",
    r"\b(?:mkfs|fdisk|parted)\b",
    r"\b(?:mount|umount)\b",
    r"\bresize2fs\b",
    r"\bgrowpart\b",
    r"\b(?:ip|ifconfig)\b",
    r"\b(?:candump|cansend)\b",
    r"\bros2\s+launch\b",
    r"\bros2\s+run\s+parking_mcu_bridge\b",
    r"/dev/ttyUSB\S*",
    r"/dev/ttyACM\S*",
    r"/dev/ttyS\S*",
    r"\bcan0\b",
    r"\bgpio\b",
    r"\bi2c\b",
    r"\bspi\b",
    r"\bmotor\b",
    r"\bsteering\b",
    r"\bbrake\b",
    r"\bthrottle\b",
    r"\bactuator\b",
    r"\brm\b",
    r"\bmv\b",
    r"\bchmod\b",
    r"\bchown\b",
]


class SerialSession:
    def __init__(
        self,
        port: str,
        baud: int,
        timeout: float = 0.2,
        login_user: str = DEFAULT_LOGIN_USER,
        login_password: str = DEFAULT_LOGIN_PASSWORD,
    ):
        try:
            import serial
        except ImportError:
            print(
                "pyserial is not installed. Run: .venv\\Scripts\\python -m pip install pyserial",
                file=sys.stderr,
            )
            raise SystemExit(2)

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"serial_{stamp}_{uuid.uuid4().hex[:8]}.log"
        self.log_file = self.log_path.open("ab")
        try:
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        except serial.SerialException as exc:
            print(f"Failed to open serial port {port} at {baud}: {exc}", file=sys.stderr)
            print(
                "If MobaXterm has an active COM11 session, close it first. "
                "Also verify the COM port, baud rate, and board power.",
                file=sys.stderr,
            )
            self.log_file.close()
            raise SystemExit(3)
        self.login_user = login_user
        self.login_password = login_password

    def close(self) -> None:
        self.ser.close()
        self.log_file.close()

    def write(self, text: str, log_text: str | None = None) -> None:
        data = text.encode("utf-8", errors="replace")
        if log_text is None:
            log_data = data
        else:
            log_data = log_text.encode("utf-8", errors="replace")
        self.log_file.write(log_data)
        self.log_file.flush()
        self.ser.write(data)
        self.ser.flush()

    def read_available(self, duration: float = 0.0) -> str:
        end = time.monotonic() + duration
        chunks: list[bytes] = []
        while True:
            waiting = self.ser.in_waiting
            if waiting:
                chunk = self.ser.read(waiting)
                chunks.append(chunk)
                self.log_file.write(chunk)
                self.log_file.flush()
            if time.monotonic() >= end:
                break
            time.sleep(0.03)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def wake_shell(self) -> None:
        self.write("\r\n")
        self.read_available(0.8)

    def ensure_shell(self) -> None:
        for _ in range(4):
            self.write("\r\n")
            transcript = self.read_available(0.8)
            lower = transcript.lower()
            if "login:" in lower:
                self.write(self.login_user + "\r\n")
                transcript = self.read_available(0.8)
                lower = transcript.lower()
            if "password:" in lower:
                self.write(self.login_password + "\r\n", "<password redacted>\r\n")
                transcript = self.read_available(1.2)
                lower = transcript.lower()
            if "account is locked" in lower:
                print(
                    "Board account is temporarily locked after failed logins. "
                    "Wait for the unlock timer, then retry.",
                    file=sys.stderr,
                )
                raise SystemExit(6)
            if re.search(r"(^|\n|\r)[^\r\n]*[#>$]\s*$", transcript):
                return
            if "login incorrect" in lower:
                print(
                    "Board login failed. Set BOARD_SERIAL_LOGIN_USER and "
                    "BOARD_SERIAL_LOGIN_PASSWORD, then retry.",
                    file=sys.stderr,
                )
                raise SystemExit(5)

    def run(self, command: str, timeout: float = 30.0) -> tuple[int | None, str]:
        sentinel = f"__CODEX_DONE_{uuid.uuid4().hex}__"
        wrapped = f"{command}\nprintf '{sentinel}%s\\n' \"$?\"\n"
        self.ensure_shell()
        self.write(wrapped.replace("\n", "\r\n"))

        output_parts: list[str] = []
        deadline = time.monotonic() + timeout
        rc: int | None = None
        marker_re = re.compile(re.escape(sentinel) + r"(-?\d+)")

        while time.monotonic() < deadline:
            text = self.read_available(0.2)
            if text:
                output_parts.append(text)
                match = marker_re.search("".join(output_parts))
                if match:
                    rc = int(match.group(1))
                    break
            else:
                time.sleep(0.05)

        output = "".join(output_parts)
        if rc is None:
            print(f"Timed out waiting for sentinel after {timeout:.1f}s.", file=sys.stderr)
        cleaned = marker_re.sub("", output).strip()
        return rc, cleaned


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
        print("Refusing to send a potentially important or dangerous board command.")
        print(f"Matched risk rule: {pattern}")
        print("Show the full command to the user, explain purpose and risk,")
        print("then rerun with --allow-risk only after explicit approval.")
        raise SystemExit(4)


def make_session(args: argparse.Namespace) -> SerialSession:
    return SerialSession(
        args.port,
        args.baud,
        login_user=args.login_user,
        login_password=args.login_password,
    )


def cmd_run(args: argparse.Namespace) -> int:
    require_safe(args.command, args.allow_risk)
    session = make_session(args)
    try:
        rc, output = session.run(args.command, timeout=args.timeout)
        if output:
            print(output)
        print(f"\n[board_serial] exit_code={rc} log={session.log_path}")
        return 124 if rc is None else rc
    finally:
        session.close()


def cmd_put_text(args: argparse.Namespace) -> int:
    remote = args.remote_file
    require_safe(f"cat > {remote}", args.allow_risk)
    local_path = Path(args.local_file)
    data = local_path.read_bytes()
    encoded = "\n".join(textwrap.wrap(base64.b64encode(data).decode("ascii"), 76))
    command = (
        f"mkdir -p \"$(dirname {shell_quote(remote)})\" && "
        "stty -echo 2>/dev/null || true\n"
        f"base64 -d > {shell_quote(remote)} <<'__CODEX_B64__'\n"
        f"{encoded}\n"
        "__CODEX_B64__\n"
        "stty echo 2>/dev/null || true"
    )
    session = make_session(args)
    try:
        rc, output = session.run(command, timeout=args.timeout)
        if output:
            print(output)
        print(f"\n[board_serial] exit_code={rc} log={session.log_path}")
        return 124 if rc is None else rc
    finally:
        session.close()


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def cmd_interactive(args: argparse.Namespace) -> int:
    print("Interactive serial mode. Press Ctrl+C to exit.")
    session = make_session(args)
    try:
        session.wake_shell()
        while True:
            pending = session.read_available(0.1)
            if pending:
                print(pending, end="", flush=True)
            line = input()
            if line.strip():
                risky, pattern = is_risky(line)
                if risky and not args.allow_risk:
                    print(f"Refused by risk rule {pattern}; restart with --allow-risk after approval.")
                    continue
            session.write(line + "\r\n")
    except KeyboardInterrupt:
        print("\nLeaving interactive mode.")
        return 0
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control board shell over Windows serial.")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", default=DEFAULT_BAUD, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--login-user", default=DEFAULT_LOGIN_USER)
    parser.add_argument("--login-password", default=DEFAULT_LOGIN_PASSWORD)
    parser.add_argument("--allow-risk", action="store_true")
    sub = parser.add_subparsers(dest="command_name", required=True)

    run_p = sub.add_parser("run", help="Run one shell command on the board.")
    run_p.add_argument("--allow-risk", action="store_true", default=argparse.SUPPRESS)
    run_p.add_argument("command")
    run_p.set_defaults(func=cmd_run)

    put_p = sub.add_parser("put-text", help="Upload a text file to the board.")
    put_p.add_argument("--allow-risk", action="store_true", default=argparse.SUPPRESS)
    put_p.add_argument("local_file")
    put_p.add_argument("remote_file")
    put_p.set_defaults(func=cmd_put_text)

    interactive_p = sub.add_parser("interactive", help="Open interactive serial shell.")
    interactive_p.add_argument("--allow-risk", action="store_true", default=argparse.SUPPRESS)
    interactive_p.set_defaults(func=cmd_interactive)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
