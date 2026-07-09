#!/usr/bin/env python3
"""Auto-discover and control the Euler Pi / SS928 board over SSH.

The intended use is same-LAN Wi-Fi operation: when the Windows host and the
board are on the same hotspot/Wi-Fi network, this tool finds the board IP and
runs receive/control-safe SSH commands without relying on COM11 or a fixed
192.168.137.2 address.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
CACHE_DIR = ROOT / "artifacts" / "board_auto_ssh"
CACHE_FILE = CACHE_DIR / "last_board.json"

DEFAULT_USER = os.environ.get("BOARD_SSH_USER", "root")
DEFAULT_PASSWORD = os.environ.get("BOARD_SSH_PASSWORD", "ebaina")
DEFAULT_PORT = int(os.environ.get("BOARD_SSH_PORT", "22"))
DEFAULT_KNOWN_HOSTS = [
    "172.20.10.2",      # iPhone hotspot common first client
    "192.168.100.101",  # MIFI route observed in this workspace
    "10.20.46.15",      # campus route observed in this workspace
    "192.168.137.2",    # wired fallback
]

BOARD_MACS = {
    "38-7a-cc-e9-db-1a": "board_wlan0",
    "38:7a:cc:e9:db:1a": "board_wlan0",
    "e2-f7-09-46-db-ac": "board_eth0",
    "e2:f7:09:46:db:ac": "board_eth0",
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
    r"\b(?:iptables|nftables|ufw)\b",
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
    r"\bkill\b",
    r"\bpkill\b",
]

SAFE_READONLY_COMMANDS = {
    "whoami",
    "hostname",
    "uname -a",
    "uptime",
    "pwd",
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class Candidate:
    host: str
    source: str
    mac: str = ""
    interface: str = ""
    priority: int = 0


@dataclass
class BoardMatch:
    host: str
    port: int
    user: str
    source: str
    mac: str
    interface: str
    whoami: str
    uname: str
    wifi_ssid: str
    wifi_ip: str
    score: int


def run_text(parts: list[str], timeout: float = 10.0) -> str:
    proc = subprocess.run(
        parts,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )
    return proc.stdout


def powershell_json(script: str) -> Any:
    out = run_text(["powershell", "-NoProfile", "-Command", script], timeout=15)
    if not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def get_interfaces() -> list[dict[str, Any]]:
    script = r"""
Get-NetIPConfiguration | ForEach-Object {
  [pscustomobject]@{
    InterfaceAlias = $_.InterfaceAlias
    InterfaceDescription = $_.InterfaceDescription
    IPv4Address = @($_.IPv4Address | ForEach-Object { $_.IPAddress + "/" + $_.PrefixLength })
    IPv4DefaultGateway = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
  }
} | ConvertTo-Json -Depth 4
"""
    data = powershell_json(script)
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def parse_arp() -> dict[str, tuple[str, str]]:
    out = run_text(["arp", "-a"], timeout=8)
    current_iface = ""
    entries: dict[str, tuple[str, str]] = {}
    iface_re = re.compile(r"Interface:\s+(\d+\.\d+\.\d+\.\d+)")
    arp_re = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]{17})\s+\w+")
    for line in out.splitlines():
        iface_match = iface_re.search(line)
        if iface_match:
            current_iface = iface_match.group(1)
            continue
        arp_match = arp_re.search(line)
        if arp_match:
            ip, mac = arp_match.groups()
            entries[ip] = (mac.lower(), current_iface)
    return entries


def add_candidate(candidates: dict[str, Candidate], candidate: Candidate) -> None:
    existing = candidates.get(candidate.host)
    if existing is None or candidate.priority > existing.priority:
        candidates[candidate.host] = candidate


def candidate_hosts(max_hosts_per_net: int) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}
    arp = parse_arp()

    env_hosts = os.environ.get("BOARD_AUTO_HOSTS", "")
    for host in [h.strip() for h in env_hosts.split(",") if h.strip()] + DEFAULT_KNOWN_HOSTS:
        add_candidate(candidates, Candidate(host=host, source="known", priority=80))

    for ip, (mac, iface) in arp.items():
        priority = 70
        source = "arp"
        if mac in BOARD_MACS:
            priority = 120
            source = BOARD_MACS[mac]
        add_candidate(candidates, Candidate(host=ip, source=source, mac=mac, interface=iface, priority=priority))

    for item in get_interfaces():
        alias = str(item.get("InterfaceAlias") or "")
        addrs = item.get("IPv4Address") or []
        if isinstance(addrs, str):
            addrs = [addrs]
        for addr in addrs:
            try:
                iface = ipaddress.ip_interface(addr)
                net = iface.network
            except ValueError:
                continue
            if iface.ip.is_loopback or iface.ip.is_link_local:
                continue
            if not iface.ip.is_private:
                continue
            if net.num_addresses > max_hosts_per_net:
                continue
            for host in net.hosts():
                host_s = str(host)
                if host == iface.ip:
                    continue
                add_candidate(candidates, Candidate(host=host_s, source="subnet_scan", interface=alias, priority=20))

    return sorted(candidates.values(), key=lambda c: (-c.priority, c.host))


def socket_open(host: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def ssh_connect(host: str, port: int, user: str, password: str, timeout: float):
    try:
        import paramiko
    except ImportError:
        print("paramiko is not installed. Run: .venv\\Scripts\\python -m pip install paramiko", file=sys.stderr)
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


def exec_ssh(client: Any, command: str, timeout: float) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def parse_identity(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def verify_candidate(candidate: Candidate, args: argparse.Namespace) -> BoardMatch | None:
    if not socket_open(candidate.host, args.port, args.socket_timeout):
        return None
    try:
        client = ssh_connect(candidate.host, args.port, args.user, args.password, args.ssh_timeout)
    except Exception:
        return None
    try:
        identity_cmd = (
            "printf 'WHOAMI='; whoami; "
            "printf 'UNAME='; uname -a; "
            "printf 'WIFI_SSID='; wpa_cli -i wlan0 status 2>/dev/null | sed -n 's/^ssid=//p' | head -1; "
            "printf 'WIFI_IP='; wpa_cli -i wlan0 status 2>/dev/null | sed -n 's/^ip_address=//p' | head -1"
        )
        rc, out, _err = exec_ssh(client, identity_cmd, timeout=args.command_timeout)
        if rc != 0:
            return None
        identity = parse_identity(out)
        uname = identity.get("UNAME", "")
        whoami = identity.get("WHOAMI", "")
        score = candidate.priority
        if whoami == "root":
            score += 20
        if "4.19.90" in uname or "SS928" in uname or "aarch64" in uname:
            score += 20
        if candidate.mac.lower() in BOARD_MACS:
            score += 50
        if score < 40:
            return None
        return BoardMatch(
            host=candidate.host,
            port=args.port,
            user=args.user,
            source=candidate.source,
            mac=candidate.mac,
            interface=candidate.interface,
            whoami=whoami,
            uname=uname,
            wifi_ssid=identity.get("WIFI_SSID", ""),
            wifi_ip=identity.get("WIFI_IP", ""),
            score=score,
        )
    finally:
        client.close()


def discover(args: argparse.Namespace) -> list[BoardMatch]:
    if args.host:
        candidates = [Candidate(host=args.host, source="explicit", priority=200)]
    else:
        candidates = candidate_hosts(args.max_hosts_per_net)
        if not args.scan_subnets:
            candidates = [c for c in candidates if c.source != "subnet_scan"]

    matches: list[BoardMatch] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(verify_candidate, candidate, args) for candidate in candidates]
        for future in concurrent.futures.as_completed(futures):
            match = future.result()
            if match:
                matches.append(match)
                if args.first:
                    break

    matches.sort(key=lambda m: (-m.score, m.host))
    if matches:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(asdict(matches[0]), ensure_ascii=False, indent=2), encoding="utf-8")
    return matches


def load_cache() -> BoardMatch | None:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return BoardMatch(**data)
    except Exception:
        return None


def choose_board(args: argparse.Namespace) -> BoardMatch:
    if args.use_cache:
        cached = load_cache()
        if cached and socket_open(cached.host, cached.port, args.socket_timeout):
            return cached
    matches = discover(args)
    if not matches:
        print("No board found over SSH on current local networks.", file=sys.stderr)
        print("Check that the host and board are on the same Wi-Fi/hotspot, or pass --host.", file=sys.stderr)
        raise SystemExit(3)
    return matches[0]


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
        print("Refusing to send a potentially important or dangerous board SSH command.")
        print(f"Matched risk rule: {pattern}")
        print("Show the full command to the user, explain purpose and risk, then rerun with --allow-risk.")
        raise SystemExit(4)


def log_path(prefix: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}.log"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def cmd_discover(args: argparse.Namespace) -> int:
    matches = discover(args)
    if args.json:
        print(json.dumps([asdict(match) for match in matches], ensure_ascii=False, indent=2))
    else:
        if not matches:
            print("BOARD_AUTO_DISCOVER no_board_found")
            return 3
        for i, match in enumerate(matches, 1):
            print(
                f"{i}. host={match.host} user={match.user} source={match.source} "
                f"mac={match.mac or '-'} ssid={match.wifi_ssid or '-'} score={match.score}"
            )
        print(f"BOARD_AUTO_HOST {matches[0].host}")
        print(f"BOARD_AUTO_CACHE {CACHE_FILE}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    require_safe(args.remote_command, args.allow_risk)
    match = choose_board(args)
    path = log_path("board_auto_ssh")
    client = ssh_connect(match.host, match.port, args.user, args.password, args.ssh_timeout)
    try:
        rc, out, err = exec_ssh(client, args.remote_command, args.command_timeout)
        path.write_text(
            f"HOST: {match.host}\nUSER: {args.user}\nCMD: {args.remote_command}\n"
            f"--- stdout ---\n{out}\n--- stderr ---\n{err}\n",
            encoding="utf-8",
        )
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        print(f"\n[board_auto_ssh] host={match.host} exit_code={rc} log={path}")
        return rc
    finally:
        client.close()


def cmd_put_text(args: argparse.Namespace) -> int:
    require_safe(f"cat > {args.remote_file}", args.allow_risk)
    match = choose_board(args)
    path = log_path("board_auto_ssh_put")
    client = ssh_connect(match.host, match.port, args.user, args.password, args.ssh_timeout)
    try:
        local_bytes = Path(args.local_file).read_bytes()
        method = "sftp"
        try:
            sftp = client.open_sftp()
            sftp.put(str(Path(args.local_file)), args.remote_file)
            sftp.close()
        except Exception as exc:
            method = "ssh_base64"
            remote_cmd = (
                "python3 -c "
                + shell_quote(
                    "import base64,pathlib,sys; "
                    "p=pathlib.Path(sys.argv[1]); "
                    "p.parent.mkdir(parents=True, exist_ok=True); "
                    "data=base64.b64decode(sys.stdin.buffer.read()); "
                    "p.write_bytes(data); "
                    "print('WROTE_BYTES', len(data))"
                )
                + " "
                + shell_quote(args.remote_file)
            )
            stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=args.command_timeout)
            stdin.write(base64.b64encode(local_bytes).decode("ascii"))
            stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
            if rc != 0:
                raise RuntimeError(f"SFTP failed with {exc!r}; SSH/base64 fallback failed rc={rc}\n{out}\n{err}")
        path.write_text(
            f"HOST: {match.host}\nPUT: {args.local_file} -> {args.remote_file}\nMETHOD: {method}\n",
            encoding="utf-8",
        )
        print(f"Uploaded {args.local_file} -> {match.host}:{args.remote_file}")
        print(f"\n[board_auto_ssh] host={match.host} exit_code=0 log={path}")
        return 0
    finally:
        client.close()


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="", help="Optional explicit board IP.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--socket-timeout", type=float, default=0.35)
    parser.add_argument("--ssh-timeout", type=float, default=3.0)
    parser.add_argument("--command-timeout", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=96)
    parser.add_argument("--max-hosts-per-net", type=int, default=4096)
    parser.add_argument("--scan-subnets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--first", action="store_true", help="Stop discovery after the first verified board.")
    parser.add_argument("--use-cache", action=argparse.BooleanOptionalAction, default=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-discover and control the board over same-LAN SSH.")
    sub = parser.add_subparsers(dest="command", required=True)

    discover_p = sub.add_parser("discover", help="Find board candidates on current local networks.")
    add_common(discover_p)
    discover_p.add_argument("--json", action="store_true")
    discover_p.set_defaults(func=cmd_discover)

    run_p = sub.add_parser("run", help="Discover the board and run one SSH command.")
    add_common(run_p)
    run_p.add_argument("--allow-risk", action="store_true")
    run_p.add_argument("remote_command")
    run_p.set_defaults(func=cmd_run)

    put_p = sub.add_parser("put-text", help="Discover the board and upload a file by SFTP or SSH/base64 fallback.")
    add_common(put_p)
    put_p.add_argument("--allow-risk", action="store_true")
    put_p.add_argument("local_file")
    put_p.add_argument("remote_file")
    put_p.set_defaults(func=cmd_put_text)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
