#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render camera+YOLO mask/polygon overlays from steps.json and optional frames.

Offline/read-only.  If real camera frames are missing, the script creates a
640x640 placeholder and still draws polygon data extracted from the JSONL log.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from demo_video_utils import ensure_dir, fit_image, list_images, load_font, load_steps, placeholder_image

DEFAULT_DOMAIN = (640.0, 640.0)


def scale_poly(poly: Any, width: int, height: int, domain: tuple[float, float] = DEFAULT_DOMAIN) -> list[tuple[float, float]]:
    if not isinstance(poly, list):
        return []
    sx = width / max(1.0, float(domain[0]))
    sy = height / max(1.0, float(domain[1]))
    out: list[tuple[float, float]] = []
    for pt in poly:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                out.append((float(pt[0]) * sx, float(pt[1]) * sy))
            except Exception:
                pass
    return out


def draw_poly(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], outline: str, fill: str | None = None, width: int = 4) -> None:
    if len(points) < 2:
        return
    if fill and len(points) >= 3:
        draw.polygon(points, fill=fill)
    draw.line(points + [points[0]], fill=outline, width=width, joint="curve")
    for i, (x, y) in enumerate(points):
        r = 5
        draw.ellipse([x-r, y-r, x+r, y+r], fill=outline)
        draw.text((x + 7, y - 15), str(i), font=load_font(14, bold=True), fill=outline)


def draw_edges(draw: ImageDraw.ImageDraw, edges: Any, width: int, height: int, domain: tuple[float, float]) -> None:
    if not isinstance(edges, dict):
        return
    colors = {"entrance": "#f97316", "back": "#a855f7", "left": "#22c55e", "right": "#38bdf8"}
    font = load_font(15, bold=True)
    for name, pts in edges.items():
        sp = scale_poly(pts, width, height, domain)
        if len(sp) >= 2:
            color = colors.get(str(name), "#e5e7eb")
            draw.line(sp[:2], fill=color, width=5)
            mx = (sp[0][0] + sp[1][0]) / 2
            my = (sp[0][1] + sp[1][1]) / 2
            draw.text((mx + 6, my + 6), str(name), font=font, fill=color)


def frame_for_step(frames: list[Path], idx: int, size: tuple[int, int]) -> Image.Image:
    if 0 <= idx < len(frames):
        try:
            return Image.open(frames[idx]).convert("RGB")
        except Exception:
            pass
    return placeholder_image(size, "Camera frame not available", "YOLO polygon is drawn from log when available")


def render_step(step: dict[str, Any], out_path: Path, frame: Image.Image, idx: int) -> None:
    # Keep raw size for actual frames; placeholder defaults to 640x640.
    frame = frame.convert("RGB")
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    yolo = step.get("yolo_overlay") or {}
    domain_raw = yolo.get("image_size") or [640, 640]
    try:
        domain = (float(domain_raw[0]), float(domain_raw[1]))
    except Exception:
        domain = DEFAULT_DOMAIN
    raw = scale_poly(yolo.get("raw_mask_polygon_px"), frame.width, frame.height, domain)
    slot = scale_poly(yolo.get("slot_polygon_px"), frame.width, frame.height, domain)
    clean = scale_poly(yolo.get("cleaned_polygon_px"), frame.width, frame.height, domain)
    draw_poly(od, raw, "#facc15", fill=(250, 204, 21, 55), width=3)
    draw_poly(od, clean, "#22c55e", fill=None, width=3)
    draw_poly(od, slot, "#ef4444", fill=None, width=5)
    draw_edges(od, yolo.get("slot_edges_px"), frame.width, frame.height, domain)
    img = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    font_title = load_font(28, bold=True)
    font = load_font(20)
    draw.rectangle([0, 0, img.width, 70], fill="#000000")
    draw.text((18, 14), f"Camera + YOLO polygon · Step {step.get('step_index', idx)}", font=font_title, fill="#f8fafc")
    conf = step.get("confidence")
    risk = step.get("effective_line_risk", step.get("line_risk"))
    draw.text((18, 48), f"confidence={conf if conf is not None else 'N/A'}   line_risk={risk if risk is not None else 'N/A'}", font=font, fill="#93c5fd")
    if not raw and not slot and not clean:
        draw.text((18, img.height - 42), "No mask polygon found in this step log", font=font, fill="#fca5a5")
    img = fit_image(img, (1280, 720))
    img.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frame-dir", default="", help="optional camera/YOLO raw frame directory, sorted by filename")
    args = ap.parse_args()
    payload = load_steps(Path(args.steps_json))
    frames = list_images(Path(args.frame_dir)) if args.frame_dir else []
    out_dir = ensure_dir(Path(args.out_dir))
    for i, step in enumerate(payload.get("steps") or [], 1):
        frame = frame_for_step(frames, i - 1, (640, 640))
        render_step(step, out_dir / f"frame_{i:04d}.png", frame, i)
    print("YOLO_OVERLAY_DIR", out_dir)
    print("FRAMES", len(payload.get("steps") or []))
    print("SOURCE_FRAMES", len(frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
