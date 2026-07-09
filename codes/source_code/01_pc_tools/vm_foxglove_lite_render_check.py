#!/usr/bin/env python3
"""Render one Foxglove-lite WebSocket snapshot into a PNG dashboard on the VM."""

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

import cv2
import numpy as np


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
    data = bytearray(payload)
    for i in range(len(data)):
        data[i] ^= mask[i % 4]
    sock.sendall(bytes(header) + mask + bytes(data))


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data.extend(chunk)
    return bytes(data)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    head = recv_exact(sock, 2)
    opcode = head[0] & 0x0F
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    return opcode, recv_exact(sock, length)


def connect(url: str, timeout: float) -> socket.socket:
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
        f"Sec-WebSocket-Protocol: {SUBPROTOCOL}\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    text = response.decode("utf-8", errors="replace")
    expected = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
    if "101 Switching Protocols" not in text or expected not in text:
        raise RuntimeError(text)
    return sock


def decode_image(message: dict) -> np.ndarray | None:
    try:
        raw = base64.b64decode(message["data"])
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def fit(image: np.ndarray, width: int, height: int) -> np.ndarray:
    out = np.zeros((height, width, 3), dtype=np.uint8)
    ih, iw = image.shape[:2]
    scale = min(width / max(iw, 1), height / max(ih, 1))
    nw = max(1, int(iw * scale))
    nh = max(1, int(ih * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
    y = (height - nh) // 2
    x = (width - nw) // 2
    out[y:y + nh, x:x + nw] = resized
    return out


def panel(canvas: np.ndarray, x: int, y: int, w: int, h: int, title: str, image: np.ndarray | None) -> None:
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (43, 50, 59), 1)
    cv2.rectangle(canvas, (x, y), (x + w, y + 32), (22, 27, 33), -1)
    cv2.putText(canvas, title, (x + 10, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 237, 242), 1, cv2.LINE_AA)
    if image is not None:
        canvas[y + 33:y + h - 1, x + 1:x + w - 1] = fit(image, w - 2, h - 34)


def text_panel(canvas: np.ndarray, x: int, y: int, w: int, h: int, title: str, lines: list[str]) -> None:
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (43, 50, 59), 1)
    cv2.rectangle(canvas, (x, y), (x + w, y + 32), (22, 27, 33), -1)
    cv2.putText(canvas, title, (x + 10, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 237, 242), 1, cv2.LINE_AA)
    yy = y + 58
    for line in lines[:18]:
        cv2.putText(canvas, line[:80], (x + 12, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 221, 230), 1, cv2.LINE_AA)
        yy += 24


def render(messages: dict[str, dict], output: str) -> None:
    camera = decode_image(messages.get("/parking/camera/image", {}))
    dtof = decode_image(messages.get("/parking/dtof/preview", {}))
    composite = decode_image(messages.get("/parking/preview/composite", {}))
    health = messages.get("/parking/sensors/health_lite", {})
    meta = messages.get("/parking/dtof/metadata_lite", {})

    canvas = np.zeros((800, 1280, 3), dtype=np.uint8)
    canvas[:] = (17, 20, 24)
    cv2.putText(canvas, "Parking Perception Dashboard", (22, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 240, 245), 2, cv2.LINE_AA)
    cv2.putText(canvas, time.strftime("%Y-%m-%d %H:%M:%S"), (1000, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 176, 190), 1, cv2.LINE_AA)

    panel(canvas, 20, 60, 610, 335, "OS08A20 Camera", camera)
    panel(canvas, 650, 60, 610, 335, "SS-LD-AS01 dToF Preview", dtof)
    panel(canvas, 20, 420, 610, 350, "Composite Preview", composite)

    lines = [
        f"camera_ok: {health.get('camera_ok')}",
        f"camera_fps: {health.get('camera_fps')}",
        f"camera_age_sec: {health.get('camera_age_sec')}",
        f"dtof_ok: {health.get('dtof_ok')}",
        f"dtof_transport_ok: {health.get('dtof_transport_ok')}",
        f"dtof_depth_ok: {health.get('dtof_depth_ok')}",
        f"dtof_fps: {health.get('dtof_fps')}",
        f"packet_size: {meta.get('packet_size')}",
        f"shape: {meta.get('width')}x{meta.get('height')}",
        f"depth_valid_pixels: {meta.get('depth_valid_pixels')}",
        f"depth_unique_count: {meta.get('depth_unique_count')}",
        f"depth_min_mm: {meta.get('depth_min_mm')}",
        f"depth_max_mm: {meta.get('depth_max_mm')}",
        f"depth_mean_mm: {meta.get('depth_mean_mm')}",
        "source: ws://127.0.0.1:8765",
        "mode: perception-only, no chassis control",
    ]
    text_panel(canvas, 650, 420, 610, 350, "Health / dToF Metadata", lines)
    cv2.imwrite(output, canvas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--output", default="/tmp/parking_foxglove_lite_render.png")
    parser.add_argument("--listen-sec", type=float, default=10.0)
    args = parser.parse_args()

    sock = connect(args.url, args.listen_sec)
    channels: dict[int, str] = {}
    messages: dict[str, dict] = {}
    deadline = time.time() + args.listen_sec
    while time.time() < deadline:
        opcode, payload = recv_frame(sock)
        if opcode == 1:
            msg = json.loads(payload.decode("utf-8"))
            if msg.get("op") == "advertise":
                subs = []
                for channel in msg.get("channels", []):
                    channel_id = int(channel["id"])
                    channels[channel_id] = str(channel["topic"])
                    subs.append({"id": channel_id, "channelId": channel_id})
                send_frame(sock, 1, json.dumps({"op": "subscribe", "subscriptions": subs}).encode("utf-8"))
        elif opcode == 2 and payload and payload[0] == 1:
            sub_id = struct.unpack("<I", payload[1:5])[0]
            topic = channels.get(sub_id)
            if topic:
                try:
                    messages[topic] = json.loads(payload[13:].decode("utf-8"))
                except Exception:
                    pass
        required = {
            "/parking/camera/image",
            "/parking/dtof/preview",
            "/parking/preview/composite",
            "/parking/sensors/health_lite",
            "/parking/dtof/metadata_lite",
        }
        if required.issubset(messages):
            break
    send_frame(sock, 8, b"")
    sock.close()
    render(messages, args.output)
    print("FOXGLOVE_LITE_RENDER_OUTPUT", args.output)
    print("FOXGLOVE_LITE_RENDER_TOPICS", sorted(messages))
    missing = sorted({
        "/parking/camera/image",
        "/parking/dtof/preview",
        "/parking/preview/composite",
        "/parking/sensors/health_lite",
        "/parking/dtof/metadata_lite",
    } - set(messages))
    print("FOXGLOVE_LITE_RENDER_MISSING", missing)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
