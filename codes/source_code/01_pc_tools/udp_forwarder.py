#!/usr/bin/env python3
"""Small UDP forwarder for host-side board-to-VM sensor relay."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Rule:
    listen_port: int
    target_host: str
    target_port: int


@dataclass
class RuleStats:
    listen_port: int
    target: str
    packets: int = 0
    bytes: int = 0
    last_source: str = ""
    last_rx_time: float = 0.0
    errors: int = 0
    last_error: str = ""


def parse_rule(text: str) -> Rule:
    parts = text.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("forward rule must be listen_port:target_host:target_port")
    return Rule(int(parts[0]), parts[1], int(parts[2]))


def write_stats(path: Path | None, stats: dict[int, RuleStats], stop: threading.Event) -> None:
    while not stop.wait(1.0):
        if not path:
            continue
        payload = {
            "time_sec": time.time(),
            "rules": [asdict(item) for item in stats.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def forward_loop(rule: Rule, bind_ip: str, stats: RuleStats, stop: threading.Event) -> None:
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind((bind_ip, rule.listen_port))
    recv_sock.settimeout(0.5)
    target = (rule.target_host, rule.target_port)
    try:
        while not stop.is_set():
            try:
                data, src = recv_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                stats.errors += 1
                stats.last_error = repr(exc)
                continue
            try:
                send_sock.sendto(data, target)
                stats.packets += 1
                stats.bytes += len(data)
                stats.last_source = f"{src[0]}:{src[1]}"
                stats.last_rx_time = time.time()
            except OSError as exc:
                stats.errors += 1
                stats.last_error = repr(exc)
    finally:
        recv_sock.close()
        send_sock.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-ip", default="0.0.0.0")
    parser.add_argument("--forward", action="append", type=parse_rule, required=True)
    parser.add_argument("--stats-json", default="")
    parser.add_argument("--duration-sec", type=float, default=0.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stop = threading.Event()

    def on_signal(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    stats = {
        rule.listen_port: RuleStats(
            listen_port=rule.listen_port,
            target=f"{rule.target_host}:{rule.target_port}",
        )
        for rule in args.forward
    }
    threads = [
        threading.Thread(target=forward_loop, args=(rule, args.listen_ip, stats[rule.listen_port], stop), daemon=True)
        for rule in args.forward
    ]
    for thread in threads:
        thread.start()
    stats_path = Path(args.stats_json) if args.stats_json else None
    stats_thread = threading.Thread(target=write_stats, args=(stats_path, stats, stop), daemon=True)
    stats_thread.start()
    print(
        "UDP_FORWARDER_STARTED "
        + " ".join(f"{rule.listen_port}->{rule.target_host}:{rule.target_port}" for rule in args.forward),
        flush=True,
    )

    deadline = time.monotonic() + args.duration_sec if args.duration_sec > 0 else None
    try:
        while not stop.wait(0.5):
            if deadline is not None and time.monotonic() >= deadline:
                stop.set()
    finally:
        if stats_path:
            payload = {
                "time_sec": time.time(),
                "rules": [asdict(item) for item in stats.values()],
                "final": True,
            }
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            stats_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
