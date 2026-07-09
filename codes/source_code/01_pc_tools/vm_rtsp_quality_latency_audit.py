#!/usr/bin/env python3
"""Audit RTSP quality, startup latency proxies, and decoder alternatives on the VM."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np


def run_cmd_watch_frames(cmd: list[str], frame_dir: Path, timeout_sec: float) -> dict[str, object]:
    start = time.time()
    first_frame_sec: float | None = None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        while proc.poll() is None:
            if first_frame_sec is None and next(frame_dir.glob("*.jpg"), None) is not None:
                first_frame_sec = time.time() - start
            if time.time() - start > timeout_sec:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.05)
        stdout, stderr = proc.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    elapsed = time.time() - start
    if first_frame_sec is None and next(frame_dir.glob("*.jpg"), None) is not None:
        first_frame_sec = elapsed
    return {
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "first_frame_sec": first_frame_sec,
        "stdout_tail": "\n".join((stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((stderr or "").splitlines()[-20:]),
    }


def safe_rate(rate: str) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def ffprobe_stream(url: str, timeout_sec: float) -> dict[str, object]:
    cmd = [
        "timeout",
        str(int(timeout_sec)),
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        url,
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    info: dict[str, object] = {"returncode": proc.returncode, "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:])}
    try:
        parsed = json.loads(proc.stdout or "{}")
        stream = (parsed.get("streams") or [{}])[0]
    except Exception:
        stream = {}
    info.update(
        {
            "codec_name": stream.get("codec_name") or "",
            "width": stream.get("width") or 0,
            "height": stream.get("height") or 0,
            "r_frame_rate": stream.get("r_frame_rate") or "",
            "avg_frame_rate": stream.get("avg_frame_rate") or "",
            "r_fps": safe_rate(str(stream.get("r_frame_rate") or "")),
            "avg_fps": safe_rate(str(stream.get("avg_frame_rate") or "")),
        }
    )
    return info


def audit_frames(frame_dir: Path, flat_std: float, gray_delta: float) -> dict[str, object]:
    files = sorted(frame_dir.glob("*.jpg"))
    bad_decode: list[str] = []
    flat: list[tuple[str, float, float, float, int]] = []
    grayish: list[tuple[str, float, float, float, int]] = []
    stats: list[tuple[str, float, float, float, int]] = []
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            bad_decode.append(path.name)
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean = float(gray.mean())
        luma_std = float(gray.std())
        b = img[:, :, 0].astype(np.int16)
        g = img[:, :, 1].astype(np.int16)
        r = img[:, :, 2].astype(np.int16)
        color_delta = float(np.mean(np.abs(b - g) + np.abs(g - r) + np.abs(b - r)) / 3.0)
        row = (path.name, mean, luma_std, color_delta, path.stat().st_size)
        stats.append(row)
        if luma_std < flat_std and color_delta < gray_delta:
            flat.append(row)
        if color_delta < gray_delta:
            grayish.append(row)
    sizes = [row[4] for row in stats]
    means = [row[1] for row in stats]
    luma = [row[2] for row in stats]
    colors = [row[3] for row in stats]
    return {
        "files": len(files),
        "bad_decode": len(bad_decode),
        "flat": len(flat),
        "grayish": len(grayish),
        "jpeg_total_bytes": int(sum(sizes)),
        "jpeg_avg_bytes": float(sum(sizes) / len(sizes)) if sizes else 0.0,
        "mean_range": [min(means), max(means)] if means else [],
        "luma_std_range": [min(luma), max(luma)] if luma else [],
        "color_delta_range": [min(colors), max(colors)] if colors else [],
        "flat_tail": flat[-8:],
        "grayish_tail": grayish[-8:],
        "stats_tail": stats[-8:],
    }


def capture_bitrate(url: str, raw_path: Path, codec: str, mode_args: list[str], seconds: int) -> dict[str, object]:
    raw_path.unlink(missing_ok=True)
    muxer = "h265" if codec == "hevc" or codec == "h265" else "h264"
    cmd = [
        "timeout",
        str(seconds + 6),
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *mode_args,
        "-i",
        url,
        "-an",
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-t",
        str(seconds),
        "-f",
        muxer,
        str(raw_path),
    ]
    start = time.time()
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.time() - start
    size = raw_path.stat().st_size if raw_path.exists() else 0
    return {
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "raw_bytes": size,
        "bitrate_kbps": (size * 8.0 / max(0.001, seconds)) / 1000.0,
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
    }


def ffmpeg_capture(url: str, out_dir: Path, mode_args: list[str], seconds: int) -> dict[str, object]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *mode_args,
        "-i",
        url,
        "-an",
        "-vf",
        "scale=768:-2",
        "-q:v",
        "4",
        "-vsync",
        "0",
        "-t",
        str(seconds),
        str(out_dir / "frame_%06d.jpg"),
    ]
    return run_cmd_watch_frames(cmd, out_dir, seconds + 8)


def gstreamer_capture(url: str, out_dir: Path, codec: str, seconds: int) -> dict[str, object]:
    if shutil.which("gst-launch-1.0") is None:
        return {"returncode": 127, "elapsed_sec": 0.0, "first_frame_sec": None, "stderr_tail": "gst-launch-1.0 missing"}
    if codec in {"h265", "hevc"}:
        depay = "rtph265depay"
        parse = "h265parse"
        decoder = "avdec_h265"
    else:
        depay = "rtph264depay"
        parse = "h264parse"
        decoder = "avdec_h264"
    cmd = [
        "timeout",
        str(seconds + 8),
        "gst-launch-1.0",
        "-q",
        "rtspsrc",
        f"location={url}",
        "protocols=tcp",
        "latency=0",
        "drop-on-latency=true",
        "name=src",
        "src.",
        "!",
        "queue",
        "leaky=downstream",
        "max-size-buffers=1",
        "!",
        depay,
        "!",
        parse,
        "!",
        decoder,
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "!",
        "video/x-raw,width=768",
        "!",
        "jpegenc",
        "quality=85",
        "!",
        "multifilesink",
        f"location={out_dir / 'frame_%06d.jpg'}",
    ]
    return run_cmd_watch_frames(cmd, out_dir, seconds + 10)


def run_mode(
    name: str,
    url: str,
    root: Path,
    codec: str,
    seconds: int,
    min_fps: float,
    max_first_frame_sec: float,
    flat_std: float,
    gray_delta: float,
    ffmpeg_args: list[str] | None = None,
    use_gst: bool = False,
) -> dict[str, object]:
    out_dir = root / name
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    if use_gst:
        run_result = gstreamer_capture(url, out_dir, codec, seconds)
        bitrate = {"returncode": None, "raw_bytes": None, "bitrate_kbps": None}
    else:
        mode_args = ffmpeg_args or []
        run_result = ffmpeg_capture(url, out_dir, mode_args, seconds)
        bitrate = capture_bitrate(url, root / f"{name}.{codec if codec in {'h265', 'hevc'} else 'h264'}", codec, mode_args, seconds)
    frames = audit_frames(out_dir, flat_std, gray_delta)
    fps = float(frames["files"]) / max(0.001, seconds)
    first = run_result.get("first_frame_sec")
    ok = (
        run_result.get("returncode") == 0
        and int(frames["files"]) >= int(min_fps * seconds)
        and int(frames["bad_decode"]) == 0
        and int(frames["flat"]) == 0
        and int(frames["grayish"]) == 0
        and first is not None
        and float(first) <= max_first_frame_sec
    )
    return {
        "name": name,
        "ok": ok,
        "seconds": seconds,
        "fps": fps,
        "capture": run_result,
        "frames": frames,
        "bitrate": bitrate,
        "frame_dir": str(out_dir),
    }


def print_mode(mode: dict[str, object]) -> None:
    frames = mode["frames"]
    capture = mode["capture"]
    bitrate = mode["bitrate"]
    print(f"MODE {mode['name']}")
    print(f"MODE_OK {mode['ok']}")
    print(f"RC {capture.get('returncode')}")
    print(f"ELAPSED_SEC {float(capture.get('elapsed_sec') or 0.0):.2f}")
    first = capture.get("first_frame_sec")
    print(f"FIRST_FRAME_SEC {float(first):.3f}" if first is not None else "FIRST_FRAME_SEC none")
    print(f"FPS {float(mode['fps']):.3f}")
    print(f"BITRATE_KBPS {float(bitrate.get('bitrate_kbps')):.1f}" if bitrate.get("bitrate_kbps") is not None else "BITRATE_KBPS n/a")
    print(f"FILES {frames['files']}")
    print(f"BAD_DECODE {frames['bad_decode']}")
    print(f"FLAT {frames['flat']}")
    print(f"GRAYISH {frames['grayish']}")
    print(f"JPEG_AVG_BYTES {float(frames['jpeg_avg_bytes']):.1f}")
    print(f"LUMA_STD_RANGE {frames['luma_std_range']}")
    print(f"COLOR_DELTA_RANGE {frames['color_delta_range']}")
    if capture.get("stderr_tail"):
        print("STDERR_TAIL_BEGIN")
        print(capture["stderr_tail"])
        print("STDERR_TAIL_END")


def select_best_mode(modes: list[dict[str, object]]) -> dict[str, object] | None:
    ok_modes = [mode for mode in modes if mode.get("ok")]
    if not ok_modes:
        return None

    def score(mode: dict[str, object]) -> tuple[int, float, float]:
        name = str(mode.get("name") or "")
        # Prefer the FFmpeg receiver family used by the ROS node when metrics
        # are otherwise close; GStreamer remains a measured candidate.
        family_rank = 0 if name.startswith("ffmpeg") else 1
        first = float((mode.get("capture") or {}).get("first_frame_sec") or 9999.0)
        fps = -float(mode.get("fps") or 0.0)
        return (family_rank, first, fps)

    return sorted(ok_modes, key=score)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--root", default="/tmp/rtsp_quality_latency_audit")
    parser.add_argument("--min-fps", type=float, default=20.0)
    parser.add_argument("--max-first-frame-sec", type=float, default=5.0)
    parser.add_argument("--flat-std", type=float, default=6.0)
    parser.add_argument("--gray-delta", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(args.root) / time.strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    stream = ffprobe_stream(args.url, timeout_sec=12.0)
    codec = str(stream.get("codec_name") or "h264")
    modes = [
        run_mode(
            "ffmpeg_tcp_default",
            args.url,
            root,
            codec,
            args.seconds,
            args.min_fps,
            args.max_first_frame_sec,
            args.flat_std,
            args.gray_delta,
            ffmpeg_args=["-rtsp_transport", "tcp"],
        ),
        run_mode(
            "ffmpeg_tcp_lowdelay",
            args.url,
            root,
            codec,
            args.seconds,
            args.min_fps,
            args.max_first_frame_sec,
            args.flat_std,
            args.gray_delta,
            ffmpeg_args=["-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay"],
        ),
        run_mode(
            "gstreamer_tcp_lowdelay",
            args.url,
            root,
            codec,
            args.seconds,
            args.min_fps,
            args.max_first_frame_sec,
            args.flat_std,
            args.gray_delta,
            use_gst=True,
        ),
    ]
    selected = select_best_mode(modes)
    report = {
        "rtsp_url": args.url,
        "stream": stream,
        "root": str(root),
        "thresholds": {
            "min_fps": args.min_fps,
            "max_first_frame_sec": args.max_first_frame_sec,
            "flat_std": args.flat_std,
            "gray_delta": args.gray_delta,
        },
        "modes": modes,
        "selected_mode": selected.get("name") if selected else "",
        "overall": "PASS" if selected else "FAIL",
    }
    report_path = root / "rtsp_quality_latency_audit.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("RTSP_QUALITY_LATENCY_AUDIT_BEGIN")
    print(f"RTSP_URL {args.url}")
    print(f"STREAM_CODEC {stream.get('codec_name')}")
    print(f"STREAM_SIZE {stream.get('width')}x{stream.get('height')}")
    print(f"STREAM_R_FPS {stream.get('r_fps')}")
    for mode in modes:
        print_mode(mode)
    print(f"SELECTED_MODE {report['selected_mode'] or 'none'}")
    print(f"RTSP_QUALITY_LATENCY_AUDIT {report['overall']}")
    print(f"RTSP_QUALITY_LATENCY_REPORT {report_path}")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
