#!/usr/bin/env python3
"""Capture board YOLO UDP side-channel for demo/offline overlay.

Read-only local receiver:
- listens for detection JSON UDP on 24580 and writes detections.jsonl
- listens for raw YOLO image UDP packets on 24581 and writes frame PNG/JPG files

It does not talk to STM32, board control, or parking commands.
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import struct
import sys
import time
from pathlib import Path


IMAGE_MAGIC = 0x50594931  # "PYI1"
HDR = struct.Struct("!IIIII")


def make_udp_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def infer_nv12_shape(total_len: int, default_w: int, default_h: int) -> tuple[int, int]:
    if total_len == default_w * default_h * 3 // 2:
        return default_w, default_h
    common = [(640, 640), (320, 320), (416, 416), (384, 384), (640, 360), (1280, 720)]
    for w, h in common:
        if total_len == w * h * 3 // 2:
            return w, h
    return default_w, default_h


def nv12_to_bgr(data: bytes, w: int, h: int):
    try:
        import numpy as np
        import cv2
    except Exception:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    expected = w * h * 3 // 2
    if arr.size < expected:
        return None
    arr = arr[:expected].reshape((h * 3 // 2, w))
    return cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_NV12)


def save_frame(data: bytes, out_dir: Path, idx: int, frame_idx: int, w: int, h: int, fmt: str) -> str:
    bgr = nv12_to_bgr(data, w, h)
    stem = f"frame_{idx:06d}_src{frame_idx}"
    if bgr is not None:
        import cv2
        path = out_dir / f"{stem}.{fmt}"
        if fmt.lower() in ("jpg", "jpeg"):
            cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        else:
            cv2.imwrite(str(path), bgr)
        return str(path)
    raw = out_dir / f"{stem}_{w}x{h}.nv12"
    raw.write_bytes(data)
    return str(raw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture board YOLO detection/image UDP for demo assets.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--listen-host", default="0.0.0.0")
    ap.add_argument("--det-port", type=int, default=24580)
    ap.add_argument("--image-port", type=int, default=24581)
    ap.add_argument("--image-width", type=int, default=640)
    ap.add_argument("--image-height", type=int, default=640)
    ap.add_argument("--frame-format", choices=["png", "jpg"], default="jpg")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--stop-file", default="")
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    frames = out / "yolo_input_frames"
    out.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    stop_file = Path(args.stop_file) if args.stop_file else out / "STOP"

    det_sock = make_udp_socket(args.listen_host, args.det_port)
    img_sock = make_udp_socket(args.listen_host, args.image_port)
    det_fh = (out / "detections.jsonl").open("a", encoding="utf-8")
    frame_fh = (out / "frames.jsonl").open("a", encoding="utf-8")
    meta = {
        "started_unix": time.time(),
        "listen_host": args.listen_host,
        "det_port": args.det_port,
        "image_port": args.image_port,
        "image_width": args.image_width,
        "image_height": args.image_height,
        "frame_format": args.frame_format,
        "stop_file": str(stop_file),
    }
    (out / "capture_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    buffers: dict[int, dict[str, object]] = {}
    saved = 0
    det_count = 0
    last_print = 0.0
    print(f"YOLO_UDP_CAPTURE_READY out={out} det={args.det_port} image={args.image_port} stop_file={stop_file}", flush=True)

    try:
        while True:
            if stop_file.exists():
                print("YOLO_UDP_CAPTURE_STOP_FILE", flush=True)
                break
            readable, _, _ = select.select([det_sock, img_sock], [], [], 0.25)
            now = time.time()
            for sock in readable:
                try:
                    pkt, addr = sock.recvfrom(65535)
                except BlockingIOError:
                    continue
                if sock is det_sock:
                    text = pkt.decode("utf-8", errors="replace").strip()
                    rec = {"time_unix": now, "src": addr, "raw": text}
                    try:
                        rec["json"] = json.loads(text)
                    except Exception:
                        pass
                    det_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    det_fh.flush()
                    det_count += 1
                    continue

                if len(pkt) < HDR.size:
                    continue
                magic, frame_idx, total_len, offset, payload_len = HDR.unpack(pkt[:HDR.size])
                if magic != IMAGE_MAGIC or payload_len <= 0:
                    continue
                payload = pkt[HDR.size:HDR.size + payload_len]
                if len(payload) != payload_len:
                    continue
                buf = buffers.get(frame_idx)
                if buf is None or buf.get("total_len") != total_len:
                    buf = {
                        "total_len": total_len,
                        "data": bytearray(total_len),
                        "ranges": set(),
                        "first_unix": now,
                    }
                    buffers[frame_idx] = buf
                if offset + payload_len <= total_len:
                    data = buf["data"]
                    assert isinstance(data, bytearray)
                    data[offset:offset + payload_len] = payload
                    ranges = buf["ranges"]
                    assert isinstance(ranges, set)
                    ranges.add((offset, payload_len))
                    have = sum(length for _, length in ranges)
                    if have >= total_len:
                        w, h = infer_nv12_shape(total_len, args.image_width, args.image_height)
                        saved += 1
                        path = save_frame(bytes(data), frames, saved, frame_idx, w, h, args.frame_format)
                        frame_rec = {
                            "time_unix": now,
                            "frame_seq": saved,
                            "src_frame_idx": frame_idx,
                            "total_len": total_len,
                            "width": w,
                            "height": h,
                            "path": path,
                            "latency_sec": now - float(buf.get("first_unix") or now),
                        }
                        frame_fh.write(json.dumps(frame_rec, ensure_ascii=False) + "\n")
                        frame_fh.flush()
                        buffers.pop(frame_idx, None)
                        # Keep memory bounded.
                        for old in list(buffers)[: max(0, len(buffers) - 8)]:
                            buffers.pop(old, None)
                        if args.max_frames and saved >= args.max_frames:
                            print("YOLO_UDP_CAPTURE_MAX_FRAMES", saved, flush=True)
                            return 0
            if now - last_print > 5.0:
                last_print = now
                print(f"YOLO_UDP_CAPTURE_STATUS frames={saved} det={det_count} partial={len(buffers)}", flush=True)
    finally:
        det_fh.close()
        frame_fh.close()
        det_sock.close()
        img_sock.close()
        summary = {"ended_unix": time.time(), "saved_frames": saved, "detections": det_count}
        (out / "capture_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"YOLO_UDP_CAPTURE_DONE frames={saved} det={det_count} out={out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
