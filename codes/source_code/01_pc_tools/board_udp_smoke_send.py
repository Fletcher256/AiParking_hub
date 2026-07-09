#!/usr/bin/env python3
"""Send one UDP smoke-test datagram from the board."""

from __future__ import annotations

import argparse
import socket


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--message", default="codex_udp_smoke_from_board")
    args = parser.parse_args()

    payload = args.message.encode("utf-8", errors="replace")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = sock.sendto(payload, (args.host, args.port))
    print(f"BOARD_UDP_SENT host={args.host} port={args.port} bytes={sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
