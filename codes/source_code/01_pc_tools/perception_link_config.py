#!/usr/bin/env python3
"""Discover the current perception network link and write a reusable config.

This tool is intentionally perception-only. It reads board networking through
COM11, reads Windows adapter state locally, probes the Ubuntu VM over SSH, and
emits the concrete IPs/URLs that the camera+dToF toolchain should use.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
BOARD_SERIAL = ROOT / "tools" / "board_serial.py"
BOARD_AUTO_SSH = ROOT / "tools" / "board_auto_ssh.py"
VM_SSH = ROOT / "tools" / "vm_ssh_run.py"
DEFAULT_OUTPUT = ROOT / "artifacts" / "current_link_config.json"
LAST_GOOD_OUTPUT = ROOT / "artifacts" / "last_good_link_config.json"
VMWARE_LEASES = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "VMware" / "vmnetdhcp.leases"


@dataclass
class IPv4Address:
    address: str
    prefix_length: int
    interface: str = ""
    network: str = ""


@dataclass
class Candidate:
    host: str
    source: str
    score: int = 0


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_command(parts: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        parts,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def powershell_json(script: str, timeout: float = 15.0) -> Any:
    wrapped = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); " + script
    result = run_command(["powershell", "-NoProfile", "-Command", wrapped], timeout=timeout)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def socket_open(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def local_ip_for_remote(host: str, port: int = 22, timeout: float = 2.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            return str(sock.getsockname()[0])
    except OSError:
        return ""


def parse_cidr(address: str, fallback_interface: str = "") -> IPv4Address | None:
    try:
        iface = ipaddress.ip_interface(address)
    except ValueError:
        return None
    if iface.version != 4:
        return None
    return IPv4Address(
        address=str(iface.ip),
        prefix_length=iface.network.prefixlen,
        interface=fallback_interface,
        network=str(iface.network),
    )


def same_network(left: IPv4Address, right_addr: str) -> bool:
    try:
        return ipaddress.ip_address(right_addr) in ipaddress.ip_network(left.network, strict=False)
    except ValueError:
        return False


def discover_board(args: argparse.Namespace) -> dict[str, Any]:
    command = (
        "printf 'BOARD_UNAME_BEGIN\\n'; uname -a; printf 'BOARD_UNAME_END\\n'; "
        "printf 'BOARD_ADDR_BEGIN\\n'; ip -4 addr; printf 'BOARD_ADDR_END\\n'; "
        "printf 'BOARD_ROUTE_BEGIN\\n'; ip route; printf 'BOARD_ROUTE_END\\n'; "
        "printf 'BOARD_HOSTNAME_BEGIN\\n'; hostname 2>/dev/null || true; printf 'BOARD_HOSTNAME_END\\n'"
    )
    result = run_command(
        [
            str(PYTHON),
            str(BOARD_SERIAL),
            "--port",
            args.board_port,
            "--baud",
            str(args.board_baud),
            "--login-user",
            args.board_user,
            "--login-password",
            args.board_password,
            "--timeout",
            str(args.board_timeout),
            "--allow-risk",
            "run",
            command,
        ],
        timeout=args.board_timeout + 20,
    )
    text = result.stdout
    board = {
        "online": result.returncode == 0,
        "serial_port": args.board_port,
        "serial_baud": args.board_baud,
        "returncode": result.returncode,
        "uname": extract_block(text, "BOARD_UNAME").strip(),
        "hostname": extract_block(text, "BOARD_HOSTNAME").strip(),
        "addresses": [],
        "routes": [],
        "raw_excerpt": text[-4000:],
    }
    if result.returncode != 0:
        return board
    addr_text = extract_block(text, "BOARD_ADDR")
    route_text = extract_block(text, "BOARD_ROUTE")
    board["addresses"] = [asdict(item) for item in parse_linux_ip_addr(addr_text)]
    board["routes"] = [line.strip() for line in route_text.splitlines() if line.strip()]
    return board


def discover_board_ssh(args: argparse.Namespace) -> dict[str, Any]:
    """Fallback board network discovery over SSH.

    The serial console can be temporarily flooded by kernel/Wi-Fi scan logs.
    This read-only SSH fallback keeps health/adapt from destroying the last
    valid Ethernet route when COM11 is noisy but the board is still reachable.
    """
    command = (
        "printf 'BOARD_UNAME_BEGIN\\n'; uname -a; printf 'BOARD_UNAME_END\\n'; "
        "printf 'BOARD_ADDR_BEGIN\\n'; ip -4 addr; printf 'BOARD_ADDR_END\\n'; "
        "printf 'BOARD_ROUTE_BEGIN\\n'; ip route; printf 'BOARD_ROUTE_END\\n'; "
        "printf 'BOARD_HOSTNAME_BEGIN\\n'; hostname 2>/dev/null || true; printf 'BOARD_HOSTNAME_END\\n'"
    )
    result = run_command(
        [
            str(PYTHON),
            str(BOARD_AUTO_SSH),
            "run",
            "--user",
            args.board_user,
            "--password",
            args.board_password,
            "--socket-timeout",
            str(args.tcp_timeout),
            "--ssh-timeout",
            str(min(6.0, max(2.0, args.board_timeout / 10.0))),
            "--command-timeout",
            str(args.board_timeout),
            "--allow-risk",
            command,
        ],
        timeout=args.board_timeout + 40,
    )
    text = result.stdout
    board = {
        "online": result.returncode == 0,
        "source": "ssh_fallback",
        "serial_port": args.board_port,
        "serial_baud": args.board_baud,
        "returncode": result.returncode,
        "uname": extract_block(text, "BOARD_UNAME").strip(),
        "hostname": extract_block(text, "BOARD_HOSTNAME").strip(),
        "addresses": [],
        "routes": [],
        "raw_excerpt": text[-4000:],
    }
    if result.returncode != 0:
        return board
    addr_text = extract_block(text, "BOARD_ADDR")
    route_text = extract_block(text, "BOARD_ROUTE")
    board["addresses"] = [asdict(item) for item in parse_linux_ip_addr(addr_text)]
    board["routes"] = [line.strip() for line in route_text.splitlines() if line.strip()]
    return board


def extract_block(text: str, name: str) -> str:
    matches = re.findall(rf"{name}_BEGIN\s*(.*?)\s*{name}_END", text, flags=re.S)
    return matches[-1] if matches else ""


def parse_linux_ip_addr(text: str) -> list[IPv4Address]:
    current = ""
    items: list[IPv4Address] = []
    iface_re = re.compile(r"^\d+:\s+([^:]+):")
    inet_re = re.compile(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)")
    for raw in text.splitlines():
        line = raw.rstrip()
        iface_match = iface_re.match(line)
        if iface_match:
            current = iface_match.group(1).split("@", 1)[0]
            continue
        inet_match = inet_re.search(line)
        if not inet_match:
            continue
        addr, prefix = inet_match.groups()
        parsed = parse_cidr(f"{addr}/{prefix}", current)
        if parsed:
            items.append(parsed)
    return items


def discover_windows() -> dict[str, Any]:
    script = r"""
Get-NetIPConfiguration | ForEach-Object {
  [pscustomobject]@{
    InterfaceAlias = $_.InterfaceAlias
    InterfaceDescription = $_.InterfaceDescription
    IPv4Address = @($_.IPv4Address | ForEach-Object {
      [pscustomobject]@{ IPAddress = $_.IPAddress; PrefixLength = $_.PrefixLength }
    })
    IPv4DefaultGateway = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
  }
} | ConvertTo-Json -Depth 5
"""
    data = powershell_json(script)
    if isinstance(data, dict):
        data = [data]
    adapters = data if isinstance(data, list) else []
    addresses: list[IPv4Address] = []
    for adapter in adapters:
        alias = str(adapter.get("InterfaceAlias") or "")
        values = adapter.get("IPv4Address") or []
        if isinstance(values, dict):
            values = [values]
        for value in values:
            try:
                ip = str(value.get("IPAddress") or "")
                prefix = int(value.get("PrefixLength"))
            except Exception:
                continue
            parsed = parse_cidr(f"{ip}/{prefix}", alias)
            if parsed and not ipaddress.ip_address(parsed.address).is_link_local:
                addresses.append(parsed)
    return {
        "adapters": adapters,
        "addresses": [asdict(item) for item in addresses],
    }


def vmware_lease_candidates() -> list[Candidate]:
    if not VMWARE_LEASES.exists():
        return []
    text = VMWARE_LEASES.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"lease\s+(\d+\.\d+\.\d+\.\d+)\s+\{(.*?)\n\}", text, flags=re.S)
    candidates: list[Candidate] = []
    for host, body in blocks:
        score = 70
        source = "vmware_lease"
        if "ebaina-virtual-machine" in body:
            score = 100
            source = "vmware_lease_ebaina"
        candidates.append(Candidate(host=host, source=source, score=score))
    return candidates


def prior_config_candidates() -> list[Candidate]:
    paths = [
        ROOT / "artifacts" / "current_link_config.json",
        ROOT / "artifacts" / "wifi_sensor_link" / "link_state.json",
    ]
    candidates: list[Candidate] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        for key in ("vm_ip", "vm_host"):
            value = data.get(key)
            if isinstance(value, str) and value:
                candidates.append(Candidate(value, f"prior:{path.name}", 60))
        vm = data.get("vm")
        if isinstance(vm, dict):
            value = vm.get("host") or vm.get("ip")
            if isinstance(value, str) and value:
                candidates.append(Candidate(value, f"prior:{path.name}", 60))
    return candidates


def vm_candidates(args: argparse.Namespace) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}

    def add(candidate: Candidate) -> None:
        if not candidate.host:
            return
        try:
            ipaddress.ip_address(candidate.host)
        except ValueError:
            pass
        existing = candidates.get(candidate.host)
        if existing is None or candidate.score > existing.score:
            candidates[candidate.host] = candidate

    add(Candidate(args.vm_host, "arg", 120))
    add(Candidate(os.environ.get("VM_SSH_HOST", ""), "env", 110))
    for candidate in vmware_lease_candidates():
        add(candidate)
    for candidate in prior_config_candidates():
        add(candidate)
    for host in ("192.168.247.129", "192.168.247.128", "192.168.137.100"):
        add(Candidate(host, "known", 50))
    return sorted(candidates.values(), key=lambda item: (-item.score, item.host))


def probe_vm(args: argparse.Namespace, candidates: list[Candidate]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        attempt = asdict(candidate)
        attempt["tcp_22"] = socket_open(candidate.host, args.vm_port, args.tcp_timeout)
        if not attempt["tcp_22"]:
            attempts.append(attempt)
            continue
        result = run_command(
            [
                str(PYTHON),
                str(VM_SSH),
                "--host",
                candidate.host,
                "--port",
                str(args.vm_port),
                "--user",
                args.vm_user,
                "--password",
                args.vm_password,
                "--timeout",
                str(args.vm_timeout),
                "run",
                "printf 'VM_WHOAMI='; whoami; printf '\\nVM_HOSTNAMEI='; hostname -I; printf '\\nVM_HOSTNAME='; hostname",
            ],
            timeout=args.vm_timeout + 10,
        )
        attempt["ssh_returncode"] = result.returncode
        attempt["ssh_excerpt"] = result.stdout[-2000:]
        attempts.append(attempt)
        if result.returncode == 0:
            hostname_i = ""
            match = re.search(r"VM_HOSTNAMEI=(.*)", result.stdout)
            if match:
                hostname_i = match.group(1).strip()
            ips = [item for item in hostname_i.split() if is_ipv4(item)]
            return {
                "online": True,
                "host": candidate.host,
                "source": candidate.source,
                "addresses": ips,
                "hostname_i": hostname_i,
                "raw_excerpt": result.stdout[-3000:],
                "attempts": attempts,
            }
    return {
        "online": False,
        "host": "",
        "addresses": [],
        "attempts": attempts,
    }


def is_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def select_board_ip(board: dict[str, Any], windows: dict[str, Any]) -> dict[str, Any]:
    board_addrs = [IPv4Address(**item) for item in board.get("addresses", [])]
    win_addrs = [IPv4Address(**item) for item in windows.get("addresses", [])]
    ranked: list[dict[str, Any]] = []
    for board_addr in board_addrs:
        if board_addr.address.startswith("127.") or ipaddress.ip_address(board_addr.address).is_link_local:
            continue
        local_socket_ip = local_ip_for_remote(board_addr.address)
        tcp_22 = bool(local_socket_ip)
        for win_addr in win_addrs:
            if not same_network(win_addr, board_addr.address):
                continue
            alias_l = win_addr.interface.lower()
            score = 50
            if tcp_22 and local_socket_ip == win_addr.address:
                score += 100
            if "以太网" in win_addr.interface or "ethernet" in alias_l or "realtek" in alias_l:
                score += 30
            if "vmware" in alias_l or "tailscale" in alias_l or "radmin" in alias_l:
                score -= 40
            ranked.append(
                {
                    "board_ip": board_addr.address,
                    "board_interface": board_addr.interface,
                    "board_network": board_addr.network,
                    "host_ip": win_addr.address,
                    "host_interface": win_addr.interface,
                    "host_network": win_addr.network,
                    "tcp_22": tcp_22,
                    "score": score,
                }
            )
        if not ranked and tcp_22:
            ranked.append(
                {
                    "board_ip": board_addr.address,
                    "board_interface": board_addr.interface,
                    "board_network": board_addr.network,
                    "host_ip": local_socket_ip,
                    "host_interface": "",
                    "host_network": "",
                    "tcp_22": True,
                    "score": 80,
                }
            )
    ranked.sort(key=lambda item: (-int(item["score"]), item["board_ip"]))
    return ranked[0] if ranked else {}


def select_dtof_route(board_choice: dict[str, Any], vm: dict[str, Any]) -> dict[str, Any]:
    vm_host = vm.get("host") or ""
    if not vm.get("online") or not vm_host:
        return {
            "mode": "unavailable",
            "reason": "VM SSH is not reachable, so no UDP receiver target can be verified.",
        }
    board_network = board_choice.get("board_network") or ""
    vm_address_candidates = [vm_host]
    vm_address_candidates.extend(str(item) for item in vm.get("addresses", []) if item)
    seen_vm_addresses: set[str] = set()
    try:
        board_net = ipaddress.ip_network(board_network, strict=False)
    except ValueError:
        board_net = None
    if board_net is not None:
        for candidate in vm_address_candidates:
            if candidate in seen_vm_addresses:
                continue
            seen_vm_addresses.add(candidate)
            try:
                direct = ipaddress.ip_address(candidate) in board_net
            except ValueError:
                continue
            if direct:
                return {
                    "mode": "direct_to_vm",
                    "board_udp_target_ip": candidate,
                    "receiver_ip": candidate,
                    "vm_ssh_host": vm_host,
                    "listen_port": 2368,
                    "target": f"{candidate}:2368",
                    "reason": "VM has an address on the selected board subnet, so board dToF UDP can be sent directly to the VM.",
                }
    host_ip = board_choice.get("host_ip") or ""
    return {
        "mode": "host_forwarder",
        "board_udp_target_ip": host_ip,
        "receiver_ip": vm_host,
        "listen_port": 2368,
        "forward_target": f"{vm_host}:2368",
        "target": f"{host_ip}:2368 -> {vm_host}:2368",
        "reason": "VM is not on the selected board subnet; board should send UDP to the Windows-facing host IP.",
    }


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    board = discover_board(args)
    warnings: list[str] = []
    if not board.get("online") or not board.get("addresses"):
        serial_returncode = board.get("returncode")
        ssh_board = discover_board_ssh(args)
        if ssh_board.get("online") and ssh_board.get("addresses"):
            board = ssh_board
            warnings.append(f"board_serial_unavailable_used_ssh_fallback:{serial_returncode}")
    windows = discover_windows()
    vm = probe_vm(args, vm_candidates(args))
    board_choice = select_board_ip(board, windows)
    board_ip = board_choice.get("board_ip") or ""
    vm_ip = vm.get("host") or ""
    dtof_route = select_dtof_route(board_choice, vm)
    rtsp_url = f"rtsp://{board_ip}:554/live0" if board_ip else ""
    foxglove_ws_url = f"ws://{vm_ip}:8765" if vm_ip else ""
    issues: list[str] = []
    if not board.get("online"):
        issues.append("board_serial_offline")
    if not board_ip:
        issues.append("board_ip_unselected")
    if not vm.get("online"):
        issues.append("vm_ssh_unreachable")
    if not dtof_route.get("board_udp_target_ip"):
        issues.append("dtof_udp_target_unavailable")
    return {
        "schema_version": 1,
        "generated_at_unix": time.time(),
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "safety": {
            "perception_only": True,
            "actuator_control_allowed": False,
            "notes": "No MCU/CAN/motor/steering/brake/throttle command is generated by this tool.",
        },
        "board": board,
        "windows": windows,
        "vm": vm,
        "selection": board_choice,
        "board_ip": board_ip,
        "vm_ip": vm_ip,
        "host_forward_ip": board_choice.get("host_ip", ""),
        "rtsp_url": rtsp_url,
        "dtof_udp_route": dtof_route,
        "foxglove_ws_url": foxglove_ws_url,
        "commands": command_hints(args, board_ip, vm_ip, board_choice, dtof_route, rtsp_url),
        "issues": issues,
        "warnings": warnings,
    }


def command_hints(
    args: argparse.Namespace,
    board_ip: str,
    vm_ip: str,
    board_choice: dict[str, Any],
    dtof_route: dict[str, Any],
    rtsp_url: str,
) -> dict[str, str]:
    if not board_ip or not vm_ip:
        return {}
    start = [
        str(PYTHON),
        str(ROOT / "tools" / "wifi_sensor_suite_manager.py"),
        "adapt",
        "--allow-risk",
        "--board-host",
        board_ip,
        "--vm-host",
        vm_ip,
        "--host-forward-ip",
        board_choice.get("host_ip", ""),
        "--board-dtof-target-ip",
        str(dtof_route.get("board_udp_target_ip", "")),
        "--rtsp-url",
        rtsp_url,
        "--no-camera-ffmpeg-low-delay",
        "--camera-drop-flat-frames",
        "--camera-flat-reconnect-threshold",
        "90",
        "--camera-scale",
        "0.5",
        "--camera-jpeg-quality",
        "85",
        "--dtof-visual-publish-stride",
        "2",
    ]
    if dtof_route.get("mode") == "direct_to_vm":
        start.append("--skip-host-forwarder")
        start_note = "direct VM UDP route"
    else:
        start_note = "host relay route"
    health = [
        str(PYTHON),
        str(ROOT / "tools" / "wifi_sensor_suite_manager.py"),
        "health",
        "--board-host",
        board_ip,
        "--vm-host",
        vm_ip,
        "--host-forward-ip",
        board_choice.get("host_ip", ""),
    ]
    if dtof_route.get("mode") == "direct_to_vm":
        health.append("--skip-host-forwarder")
    return {
        "start_or_adapt": subprocess.list2cmdline(start),
        "health": subprocess.list2cmdline(health),
        "foxglove": f"Open Foxglove Studio with {f'ws://{vm_ip}:8765'}",
        "note": start_note,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def has_complete_link(config: dict[str, Any]) -> bool:
    route = config.get("dtof_udp_route", {})
    return all(
        [
            config.get("board_ip"),
            config.get("vm_ip"),
            config.get("host_forward_ip"),
            config.get("rtsp_url"),
            isinstance(route, dict) and route.get("board_udp_target_ip"),
        ]
    )


def recover_from_last_good(config: dict[str, Any], output: Path) -> dict[str, Any]:
    if has_complete_link(config):
        return config
    for path in (LAST_GOOD_OUTPUT, output):
        prior = load_json(path)
        if not has_complete_link(prior):
            continue
        board_ip = str(prior.get("board_ip", ""))
        vm_ip = str(config.get("vm_ip") or prior.get("vm_ip", ""))
        if not board_ip or not socket_open(board_ip, 22, timeout=1.0):
            continue
        if not vm_ip:
            continue
        recovered = dict(prior)
        recovered["generated_at_unix"] = time.time()
        recovered["generated_at_local"] = time.strftime("%Y-%m-%d %H:%M:%S")
        recovered["windows"] = config.get("windows", prior.get("windows", {}))
        recovered["vm"] = config.get("vm") if config.get("vm", {}).get("online") else prior.get("vm", {})
        recovered["vm_ip"] = vm_ip
        recovered["foxglove_ws_url"] = f"ws://{vm_ip}:8765"
        recovered["dtof_udp_route"] = select_dtof_route(recovered.get("selection", {}), recovered.get("vm", {}))
        recovered["commands"] = command_hints(
            argparse.Namespace(),
            str(recovered.get("board_ip", "")),
            str(recovered.get("vm_ip", "")),
            recovered.get("selection", {}),
            recovered.get("dtof_udp_route", {}),
            str(recovered.get("rtsp_url", "")),
        )
        recovered["issues"] = []
        warnings = list(recovered.get("warnings", []))
        warnings.append("recovered_from_last_good_after_incomplete_discovery")
        warnings.extend([f"incomplete_discovery_issue:{item}" for item in config.get("issues", [])])
        recovered["warnings"] = warnings
        recovered["recovery"] = {
            "source": str(path),
            "reason": "current discovery was incomplete, but the last known board IP still accepts SSH",
            "incomplete_discovery": {
                "board_ip": config.get("board_ip", ""),
                "vm_ip": config.get("vm_ip", ""),
                "host_forward_ip": config.get("host_forward_ip", ""),
                "issues": config.get("issues", []),
            },
        }
        return recovered
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-port", default="COM11")
    parser.add_argument("--board-baud", type=int, default=115200)
    parser.add_argument("--board-user", default="root")
    parser.add_argument("--board-password", default="ebaina")
    parser.add_argument("--board-timeout", type=float, default=60.0)
    parser.add_argument("--vm-host", default=os.environ.get("VM_SSH_HOST", ""))
    parser.add_argument("--vm-port", type=int, default=22)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--vm-timeout", type=float, default=8.0)
    parser.add_argument("--tcp-timeout", type=float, default=1.2)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true", help="Print the full JSON config.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = build_config(args)
    output = Path(args.output)
    config = recover_from_last_good(config, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if not config.get("issues") and has_complete_link(config):
        LAST_GOOD_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        LAST_GOOD_OUTPUT.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(config, indent=2))
    else:
        print(f"LINK_CONFIG_WRITTEN {output}")
        print(f"BOARD_IP {config.get('board_ip') or 'unavailable'}")
        print(f"HOST_FORWARD_IP {config.get('host_forward_ip') or 'unavailable'}")
        print(f"VM_IP {config.get('vm_ip') or 'unavailable'}")
        print(f"RTSP_URL {config.get('rtsp_url') or 'unavailable'}")
        print(f"DTOF_ROUTE {config.get('dtof_udp_route', {}).get('target') or config.get('dtof_udp_route', {}).get('mode')}")
        print(f"FOXGLOVE_WS_URL {config.get('foxglove_ws_url') or 'unavailable'}")
        if config.get("issues"):
            print("ISSUES " + ",".join(config["issues"]))
        if config.get("warnings"):
            print("WARNINGS " + ",".join(config["warnings"]))
    return 0 if not config.get("issues") else 2


if __name__ == "__main__":
    raise SystemExit(main())
