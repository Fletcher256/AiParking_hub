#!/usr/bin/env python3
"""Minimal no-install Foxglove WebSocket v1 server for the live parking sensors.

This is a perception-only visualization adapter. It reads the files continuously
written by parking_bridge and exposes Foxglove JSON-schema channels over a raw
WebSocket implementation, avoiding extra Python or ROS package installs.
"""

from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time
from typing import Any

import numpy as np


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SUBPROTOCOL = "foxglove.websocket.v1"


def timestamp_from_ns(ns: int | None = None) -> dict[str, int]:
    if ns is None:
        ns = time.time_ns()
    return {"sec": int(ns // 1_000_000_000), "nsec": int(ns % 1_000_000_000)}


def latest_file(pattern: str) -> Path | None:
    candidates = [Path(p) for p in glob.glob(pattern)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def read_last_json_line(path: Path) -> tuple[int, dict[str, Any] | None]:
    try:
        marker = path.stat().st_mtime_ns ^ path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            if line.strip():
                return marker, json.loads(line)
    except Exception:
        return 0, None
    return 0, None


def load_record_root(record_file: Path) -> Path | None:
    try:
        text = record_file.read_text(errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    root = Path(text)
    return root if root.exists() else None


def latest_session(record_file: Path) -> Path | None:
    root = load_record_root(record_file)
    if root is None:
        return None
    sessions = [p for p in root.glob("session_*") if p.is_dir()]
    if not sessions:
        return None
    return max(sessions, key=lambda p: p.stat().st_mtime_ns)


def compressed_image_payload(path: Path, frame_id: str) -> tuple[int, bytes]:
    stat = path.stat()
    stamp = timestamp_from_ns(stat.st_mtime_ns)
    suffix = path.suffix.lower()
    fmt = "png" if suffix == ".png" else "jpeg"
    payload = {
        "timestamp": stamp,
        "frame_id": frame_id,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        "format": fmt,
    }
    return stat.st_mtime_ns, json.dumps(payload, separators=(",", ":")).encode("utf-8")


def health_payload(path: Path) -> tuple[int, bytes] | None:
    marker, row = read_last_json_line(path)
    if not row:
        return None
    payload = {
        "timestamp": timestamp_from_ns(int(row.get("time_ns") or time.time_ns())),
        "camera_ok": bool(row.get("camera", {}).get("ok")),
        "camera_fps": float(row.get("camera", {}).get("fps") or 0.0),
        "camera_age_sec": float(row.get("camera", {}).get("age_sec") or 0.0),
        "dtof_ok": bool(row.get("dtof", {}).get("ok")),
        "dtof_transport_ok": bool(row.get("dtof", {}).get("transport_ok")),
        "dtof_depth_ok": bool(row.get("dtof", {}).get("depth_ok")),
        "dtof_fps": float(row.get("dtof", {}).get("fps") or 0.0),
        "dtof_bad_packets": int(row.get("dtof", {}).get("bad_packets") or 0),
        "raw_json": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
    }
    return marker, json.dumps(payload, separators=(",", ":")).encode("utf-8")


def metadata_payload(path: Path) -> tuple[int, bytes] | None:
    marker, row = read_last_json_line(path)
    if not row:
        return None
    payload = {
        "timestamp": timestamp_from_ns(int(row.get("recv_time_ns") or time.time_ns())),
        "packet_size": int(row.get("packet_size") or 0),
        "expected_shape": bool(row.get("expected_shape")),
        "width": int(row.get("width") or 0),
        "height": int(row.get("height") or 0),
        "pixel_number": int(row.get("pixel_number") or 0),
        "depth_ok": bool(row.get("depth_ok")),
        "depth_valid_pixels": int(row.get("depth_valid_pixels") or 0),
        "depth_unique_count": int(row.get("depth_unique_count") or 0),
        "depth_min_mm": int(row.get("depth_min_mm") or 0),
        "depth_max_mm": int(row.get("depth_max_mm") or 0),
        "depth_mean_mm": float(row.get("depth_mean_mm") or 0.0),
        "raw_json": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
    }
    return marker, json.dumps(payload, separators=(",", ":")).encode("utf-8")


def pointcloud_payload(path: Path) -> tuple[int, bytes] | None:
    stat = path.stat()
    try:
        depth = np.load(path).astype(np.float32)
    except Exception:
        return None
    if depth.ndim != 2:
        return None
    height, width = depth.shape
    points = bytearray()
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    for y in range(height):
        for x in range(width):
            z_m = float(depth[y, x]) / 1000.0
            if z_m <= 0.02 or z_m > 10.0:
                continue
            px = (x - cx) * z_m * 0.05
            py = (y - cy) * z_m * 0.05
            intensity = min(1.0, z_m / 10.0)
            points.extend(struct.pack("<ffff", px, py, z_m, intensity))
    payload = {
        "timestamp": timestamp_from_ns(stat.st_mtime_ns),
        "frame_id": "ss_ld_as01_dtof",
        "pose": {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
        "point_stride": 16,
        "fields": [
            {"name": "x", "offset": 0, "type": 7},
            {"name": "y", "offset": 4, "type": 7},
            {"name": "z", "offset": 8, "type": 7},
            {"name": "intensity", "offset": 12, "type": 7},
        ],
        "data": base64.b64encode(bytes(points)).decode("ascii"),
    }
    return stat.st_mtime_ns, json.dumps(payload, separators=(",", ":")).encode("utf-8")


COMPRESSED_IMAGE_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "timestamp": {
            "type": "object",
            "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}},
            "required": ["sec", "nsec"],
        },
        "frame_id": {"type": "string"},
        "data": {"type": "string", "contentEncoding": "base64"},
        "format": {"type": "string"},
    },
    "required": ["timestamp", "frame_id", "data", "format"],
}, separators=(",", ":"))

HEALTH_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "timestamp": {"type": "object"},
        "camera_ok": {"type": "boolean"},
        "camera_fps": {"type": "number"},
        "camera_age_sec": {"type": "number"},
        "dtof_ok": {"type": "boolean"},
        "dtof_transport_ok": {"type": "boolean"},
        "dtof_depth_ok": {"type": "boolean"},
        "dtof_fps": {"type": "number"},
        "dtof_bad_packets": {"type": "integer"},
        "raw_json": {"type": "string"},
    },
    "required": ["timestamp"],
}, separators=(",", ":"))

DTOF_META_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "timestamp": {"type": "object"},
        "packet_size": {"type": "integer"},
        "expected_shape": {"type": "boolean"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "pixel_number": {"type": "integer"},
        "depth_ok": {"type": "boolean"},
        "depth_valid_pixels": {"type": "integer"},
        "depth_unique_count": {"type": "integer"},
        "depth_min_mm": {"type": "integer"},
        "depth_max_mm": {"type": "integer"},
        "depth_mean_mm": {"type": "number"},
        "raw_json": {"type": "string"},
    },
    "required": ["timestamp"],
}, separators=(",", ":"))

POINTCLOUD_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "timestamp": {"type": "object"},
        "frame_id": {"type": "string"},
        "pose": {"type": "object"},
        "point_stride": {"type": "integer"},
        "fields": {"type": "array", "items": {"type": "object"}},
        "data": {"type": "string", "contentEncoding": "base64"},
    },
    "required": ["timestamp", "frame_id", "pose", "point_stride", "fields", "data"],
}, separators=(",", ":"))


CHANNELS = [
    {
        "id": 1,
        "topic": "/parking/camera/image",
        "encoding": "json",
        "schemaName": "foxglove.CompressedImage",
        "schema": COMPRESSED_IMAGE_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
    {
        "id": 2,
        "topic": "/parking/dtof/preview",
        "encoding": "json",
        "schemaName": "foxglove.CompressedImage",
        "schema": COMPRESSED_IMAGE_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
    {
        "id": 3,
        "topic": "/parking/preview/composite",
        "encoding": "json",
        "schemaName": "foxglove.CompressedImage",
        "schema": COMPRESSED_IMAGE_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
    {
        "id": 4,
        "topic": "/parking/dtof/points_lite",
        "encoding": "json",
        "schemaName": "foxglove.PointCloud",
        "schema": POINTCLOUD_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
    {
        "id": 5,
        "topic": "/parking/sensors/health_lite",
        "encoding": "json",
        "schemaName": "parking.Health",
        "schema": HEALTH_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
    {
        "id": 6,
        "topic": "/parking/dtof/metadata_lite",
        "encoding": "json",
        "schemaName": "parking.DtofMetadata",
        "schema": DTOF_META_SCHEMA,
        "schemaEncoding": "jsonschema",
    },
]


class ClientSession:
    def __init__(self, conn: socket.socket, addr: tuple[str, int], record_file: Path, rate_hz: float) -> None:
        self.conn = conn
        self.addr = addr
        self.record_file = record_file
        self.period = 1.0 / max(rate_hz, 0.1)
        self.subscriptions: dict[int, int] = {}
        self.sent_markers: dict[int, int] = {}
        self.running = True

    def send_text(self, payload: dict[str, Any]) -> None:
        self.send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def send_binary(self, payload: bytes) -> None:
        self.send_frame(0x2, payload)

    def send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.extend([126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([127])
            header.extend(struct.pack("!Q", length))
        self.conn.sendall(bytes(header) + payload)

    def recv_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.conn.recv(size - len(data))
            if not chunk:
                raise ConnectionError("socket closed")
            data.extend(chunk)
        return bytes(data)

    def recv_frame(self) -> tuple[int, bytes]:
        first = self.recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.recv_exact(8))[0]
        mask = self.recv_exact(4) if masked else b""
        payload = bytearray(self.recv_exact(length))
        if masked:
            for i in range(length):
                payload[i] ^= mask[i % 4]
        return opcode, bytes(payload)

    def handle_client_message(self, opcode: int, payload: bytes) -> None:
        if opcode == 0x8:
            self.running = False
            return
        if opcode == 0x9:
            self.send_frame(0xA, payload)
            return
        if opcode != 0x1:
            return
        try:
            msg = json.loads(payload.decode("utf-8"))
        except Exception:
            return
        op = msg.get("op")
        if op == "subscribe":
            for sub in msg.get("subscriptions", []):
                sub_id = int(sub.get("id"))
                channel_id = int(sub.get("channelId"))
                self.subscriptions[channel_id] = sub_id
        elif op == "unsubscribe":
            ids = {int(value) for value in msg.get("subscriptionIds", [])}
            self.subscriptions = {ch: sub for ch, sub in self.subscriptions.items() if sub not in ids}

    def send_message_data(self, channel_id: int, marker: int, payload: bytes) -> None:
        sub_id = self.subscriptions.get(channel_id)
        if sub_id is None or self.sent_markers.get(channel_id) == marker:
            return
        self.sent_markers[channel_id] = marker
        log_time = time.time_ns()
        self.send_binary(b"\x01" + struct.pack("<IQ", sub_id, log_time) + payload)

    def publish_from_files(self) -> None:
        session = latest_session(self.record_file)
        if session is None:
            return
        items: list[tuple[int, tuple[int, bytes] | None]] = []
        camera = latest_file(str(session / "camera_frames" / "*.jpg"))
        if camera:
            items.append((1, compressed_image_payload(camera, "os08a20_camera")))
        dtof_preview = latest_file(str(session / "dtof_preview" / "*.png"))
        if dtof_preview:
            items.append((2, compressed_image_payload(dtof_preview, "ss_ld_as01_dtof")))
        composite = latest_file(str(session / "preview" / "*.jpg"))
        if composite:
            items.append((3, compressed_image_payload(composite, "parking_preview")))
        depth = latest_file(str(session / "dtof_depth_npy" / "*.npy"))
        if depth:
            items.append((4, pointcloud_payload(depth)))
        health = session / "health.jsonl"
        if health.exists():
            items.append((5, health_payload(health)))
        meta = session / "dtof_metadata.jsonl"
        if meta.exists():
            items.append((6, metadata_payload(meta)))
        for channel_id, payload in items:
            if payload is not None:
                self.send_message_data(channel_id, payload[0], payload[1])

    def run(self) -> None:
        self.conn.settimeout(0.1)
        self.send_text({
            "op": "serverInfo",
            "name": "parking_board_agent foxglove lite",
            "capabilities": ["time"],
            "metadata": {"mode": "perception-only", "safety": "no chassis control"},
            "sessionId": str(int(time.time())),
        })
        self.send_text({"op": "advertise", "channels": CHANNELS})
        self.send_text({
            "op": "status",
            "level": 0,
            "message": "Parking perception Foxglove lite server connected. Read-only visualization only.",
            "id": "parking-lite-ready",
        })
        next_publish = 0.0
        while self.running:
            try:
                opcode, payload = self.recv_frame()
                self.handle_client_message(opcode, payload)
            except socket.timeout:
                pass
            except Exception:
                break
            now = time.monotonic()
            if now >= next_publish:
                next_publish = now + self.period
                try:
                    self.send_binary(b"\x02" + struct.pack("<Q", time.time_ns()))
                    self.publish_from_files()
                except Exception:
                    break
        self.conn.close()


def websocket_handshake(conn: socket.socket) -> bool:
    request = b""
    while b"\r\n\r\n" not in request and len(request) < 16384:
        chunk = conn.recv(4096)
        if not chunk:
            return False
        request += chunk
    text = request.decode("utf-8", errors="replace")
    headers: dict[str, str] = {}
    for line in text.split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    key = headers.get("sec-websocket-key")
    if not key:
        return False
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
    protocols = [item.strip() for item in headers.get("sec-websocket-protocol", "").split(",")]
    protocol_line = f"Sec-WebSocket-Protocol: {SUBPROTOCOL}\r\n" if SUBPROTOCOL in protocols else ""
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        f"{protocol_line}"
        "\r\n"
    )
    conn.sendall(response.encode("ascii"))
    return True


def serve(host: str, port: int, record_file: Path, rate_hz: float) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(8)
    print(f"FOXGLOVE_LITE_LISTEN ws://{host}:{port}", flush=True)
    print(f"FOXGLOVE_LITE_RECORD_FILE {record_file}", flush=True)
    while True:
        conn, addr = sock.accept()
        try:
            if websocket_handshake(conn):
                thread = threading.Thread(
                    target=ClientSession(conn, addr, record_file, rate_hz).run,
                    daemon=True,
                )
                thread.start()
            else:
                conn.close()
        except Exception:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--record-file", default="/tmp/parking_sensor_link/parking_record_dir")
    parser.add_argument("--rate-hz", type=float, default=5.0)
    args = parser.parse_args()
    serve(args.host, args.port, Path(args.record_file), args.rate_hz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
