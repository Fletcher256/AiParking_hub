#!/usr/bin/env python3
"""Listen for one UDP smoke-test datagram on the VM."""

from __future__ import annotations

import argparse
import socket
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=24999)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(args.timeout_sec)
    print(f"VM_UDP_LISTEN host={args.host} port={args.port}", flush=True)
    started = time.time()
    try:
        data, addr = sock.recvfrom(4096)
    except TimeoutError:
        print(f"VM_UDP_TIMEOUT elapsed={time.time() - started:.2f}", flush=True)
        return 1
    text = data.decode("utf-8", errors="replace")
    print(f"VM_UDP_GOT addr={addr[0]}:{addr[1]} bytes={len(data)} text={text}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
