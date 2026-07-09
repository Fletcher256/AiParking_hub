#!/usr/bin/env python3
"""Tiny HTTP live viewer for parking_bridge preview images on the VM."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import time
from urllib.parse import urlparse


RECORD_FILE = Path("/tmp/parking_sensor_live_record_dir")


def latest_session() -> Path | None:
    if not RECORD_FILE.exists():
        return None
    root = Path(RECORD_FILE.read_text(errors="replace").strip())
    sessions = sorted(root.glob("session_*"))
    return sessions[-1] if sessions else None


def latest_image() -> Path | None:
    session = latest_session()
    if session is None:
        return None
    for pattern in ["preview/*.jpg", "camera_frames/*.jpg", "dtof_preview/*.png"]:
        images = sorted(session.glob(pattern))
        if images:
            return images[-1]
    return None


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(errors="replace").splitlines())


def status_payload() -> dict:
    session = latest_session()
    if session is None:
        return {"ok": False, "message": "No live record session yet."}
    return {
        "ok": True,
        "session": str(session),
        "camera_frames": len(list((session / "camera_frames").glob("*.jpg"))),
        "dtof_packets": count_lines(session / "dtof_metadata.jsonl"),
        "sync_pairs": count_lines(session / "sync_pairs.jsonl"),
        "previews": len(list((session / "preview").glob("*.jpg"))),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/status.json":
            self.send_bytes(json.dumps(status_payload(), ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if path == "/latest":
            image = latest_image()
            if image is None:
                self.send_bytes(b"No preview image yet.", "text/plain", 404)
                return
            content_type = mimetypes.guess_type(str(image))[0] or "application/octet-stream"
            self.send_bytes(image.read_bytes(), content_type)
            return
        if path != "/":
            self.send_bytes(b"Not found", "text/plain", 404)
            return

        html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Parking Sensor Live Preview</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: sans-serif; }
    header { padding: 10px 14px; background: #1e1e1e; font-size: 14px; }
    img { display: block; max-width: 100vw; max-height: calc(100vh - 42px); margin: auto; object-fit: contain; }
  </style>
</head>
<body>
  <header id="status">loading...</header>
  <img id="preview" src="/latest?ts=0" alt="live preview">
  <script>
    async function tick() {
      const ts = Date.now();
      document.getElementById('preview').src = '/latest?ts=' + ts;
      try {
        const r = await fetch('/status.json?ts=' + ts, {cache: 'no-store'});
        const s = await r.json();
        document.getElementById('status').textContent =
          `camera=${s.camera_frames || 0} dtof=${s.dtof_packets || 0} sync=${s.sync_pairs || 0} previews=${s.previews || 0} ${s.session || s.message || ''}`;
      } catch (e) {
        document.getElementById('status').textContent = String(e);
      }
    }
    setInterval(tick, 150);
    tick();
  </script>
</body>
</html>
"""
        self.send_bytes(html.encode("utf-8"), "text/html")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving live preview on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
