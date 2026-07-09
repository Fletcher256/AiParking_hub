#!/usr/bin/env python3
"""Normalize and forward board YOLO detection UDP JSON."""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
from typing import Any


ALLOWED_CLASS_NAMES = {"parking", "parking_slot", "slot"}
FORBIDDEN_OUTPUT_KEY_FRAGMENTS = ("b" + "box",)


def parse_target(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("target must be HOST:PORT")
    host, port_text = value.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("target port must be an integer") from exc
    if not host or port <= 0 or port > 65535:
        raise argparse.ArgumentTypeError("target must be HOST:PORT")
    return host, port


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def polygon_area(points: list[list[float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        total += a[0] * b[1] - b[0] * a[1]
    return abs(total) * 0.5


def normalize_polygon(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list):
        return []
    points: list[list[float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return []
        x = as_float(point[0])
        y = as_float(point[1])
        if x is None or y is None:
            return []
        points.append([round(x, 3), round(y, 3)])
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points if len(points) >= 3 and polygon_area(points) > 1.0 else []


def time_ns_from_payload(payload: dict[str, Any]) -> int:
    raw_ns = payload.get("time_ns")
    try:
        ns = int(raw_ns)
    except (TypeError, ValueError):
        ns = 0
    if ns > 0:
        return ns
    raw_ms = payload.get("time_ms")
    try:
        ms = int(raw_ms)
    except (TypeError, ValueError):
        ms = 0
    if ms > 0:
        return ms * 1_000_000
    return int(time.time() * 1_000_000_000)


def class_name_allowed(det: dict[str, Any]) -> bool:
    name = str(det.get("class_name", det.get("label", det.get("name", "")))).strip()
    return name.lower() in ALLOWED_CLASS_NAMES


def normalize_detection(det: dict[str, Any], idx: int) -> dict[str, Any] | None:
    if not class_name_allowed(det):
        return None
    polygon = normalize_polygon(det.get("mask_polygon"))
    if not polygon:
        return None
    confidence = as_float(det.get("confidence", det.get("score")))
    if confidence is None:
        return None

    out: dict[str, Any] = {
        "id": det.get("id", idx),
        "class_id": det.get("class_id", 0),
        "class_name": "Parking",
        "confidence": round(confidence, 4),
    }
    # Project policy: the parking chain is mask-polygon-only.  The board C
    # binary may still emit rectangular detector metadata, but the Python
    # project boundary must never forward those fields to controller/monitor
    # consumers.
    for key in ("center_px", "center_norm"):
        if key in det:
            out[key] = det[key]
    out["mask_polygon"] = polygon
    out["polygon_source"] = "mask"

    mask_area = as_float(det.get("mask_area_px"))
    out["mask_area_px"] = int(round(mask_area)) if mask_area and mask_area > 0 else round(polygon_area(polygon), 2)
    out["slot_status"] = str(det.get("slot_status", "unknown"))
    assert_no_forbidden_output_keys(out)
    return out


def assert_no_forbidden_output_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in FORBIDDEN_OUTPUT_KEY_FRAGMENTS):
                raise AssertionError(f"forbidden YOLO output key: {key}")
            assert_no_forbidden_output_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_forbidden_output_keys(child)


def normalize_payload(packet: bytes) -> bytes | None:
    try:
        payload = json.loads(packet.decode("utf-8", errors="replace").strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    detections: list[dict[str, Any]] = []
    raw_dets = payload.get("detections")
    if isinstance(raw_dets, list):
        for idx, raw_det in enumerate(raw_dets):
            if not isinstance(raw_det, dict):
                continue
            det = normalize_detection(raw_det, idx)
            if det is not None:
                detections.append(det)
    out = {
        "time_ns": time_ns_from_payload(payload),
        "detections": detections,
    }
    assert_no_forbidden_output_keys(out)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=24579)
    parser.add_argument(
        "--target",
        action="append",
        type=parse_target,
        required=True,
        help="Forward target as HOST:PORT. Can be repeated.",
    )
    parser.add_argument("--recv-bytes", type=int, default=65535)
    parser.add_argument("--print-every", type=int, default=30)
    args = parser.parse_args()

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind((args.listen_host, args.listen_port))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    count = 0
    forwarded = 0
    dropped = 0
    start = time.monotonic()
    targets = list(dict.fromkeys(args.target))
    print(
        "BOARD_YOLO_UDP_TEE listen=%s:%d targets=%s normalizer=mask_polygon.v1"
        % (args.listen_host, args.listen_port, ",".join("%s:%d" % t for t in targets)),
        flush=True,
    )
    try:
        while True:
            packet, source = rx.recvfrom(args.recv_bytes)
            count += 1
            normalized = normalize_payload(packet)
            if normalized is None:
                dropped += 1
                continue
            for target in targets:
                tx.sendto(normalized, target)
                forwarded += 1
            if args.print_every > 0 and count % args.print_every == 0:
                elapsed = max(1e-6, time.monotonic() - start)
                print(
                    "BOARD_YOLO_UDP_TEE packets=%d forwarded=%d dropped=%d rate=%.2fHz last_source=%s:%d bytes=%d out_bytes=%d"
                    % (count, forwarded, dropped, count / elapsed, source[0], source[1], len(packet), len(normalized)),
                    flush=True,
                )
    except KeyboardInterrupt:
        print("BOARD_YOLO_UDP_TEE stopped packets=%d forwarded=%d dropped=%d" % (count, forwarded, dropped), flush=True)
        return 0
    except OSError as exc:
        print("BOARD_YOLO_UDP_TEE error: %s" % exc, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
