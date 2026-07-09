#!/usr/bin/env python3
"""Probe a Foxglove WebSocket v1 endpoint without third-party packages."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlparse


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SUBPROTOCOL = "foxglove.websocket.v1"


def send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytearray(payload)
    for i in range(len(masked)):
        masked[i] ^= mask[i % 4]
    sock.sendall(bytes(header) + mask + bytes(masked))


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data.extend(chunk)
    return bytes(data)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    first = recv_exact(sock, 2)
    opcode = first[0] & 0x0F
    length = first[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    payload = recv_exact(sock, length)
    return opcode, payload


def connect(url: str, timeout: float, subprotocol: str) -> socket.socket:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {subprotocol}\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    text = response.decode("utf-8", errors="replace")
    expected = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
    if "101 Switching Protocols" not in text or expected not in text:
        raise RuntimeError(f"bad websocket handshake: {text}")
    return sock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://192.168.247.129:8765")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--listen-sec", type=float, default=6.0)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--subprotocol", default=SUBPROTOCOL)
    args = parser.parse_args()

    sock = connect(args.url, args.timeout, args.subprotocol)
    channels: dict[int, str] = {}
    advertised = False
    received: dict[int, int] = {}
    deadline = time.time() + args.listen_sec
    while time.time() < deadline:
        opcode, payload = recv_frame(sock)
        if opcode == 0x1:
            msg = json.loads(payload.decode("utf-8"))
            print("TEXT_OP", msg.get("op"))
            if msg.get("op") == "advertise":
                advertised = True
                for channel in msg.get("channels", []):
                    channels[int(channel["id"])] = str(channel["topic"])
                print("CHANNELS", json.dumps(channels, ensure_ascii=False, sort_keys=True))
                send_frame(sock, 0x1, json.dumps({
                    "op": "subscribe",
                    "subscriptions": [
                        {"id": channel_id, "channelId": channel_id}
                        for channel_id in channels
                    ],
                }).encode("utf-8"))
        elif opcode == 0x2 and payload:
            if payload[0] == 1 and len(payload) >= 13:
                sub_id, _log_time = struct.unpack("<IQ", payload[1:13])
                received[sub_id] = received.get(sub_id, 0) + 1
                print("MESSAGE_DATA", sub_id, channels.get(sub_id, "?"), len(payload) - 13)
            elif payload[0] == 2:
                print("TIME")
        required = len(channels) if args.require_all else min(3, len(channels))
        if advertised and len(received) >= required:
            break
    send_frame(sock, 0x8, b"")
    sock.close()
    print("RECEIVED", json.dumps({channels.get(k, str(k)): v for k, v in received.items()}, sort_keys=True))
    if args.require_all and len(received) < len(channels):
        return 1
    return 0 if advertised and received else 1


if __name__ == "__main__":
    raise SystemExit(main())
