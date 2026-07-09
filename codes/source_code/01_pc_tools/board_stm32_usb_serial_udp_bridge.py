#!/usr/bin/env python3
"""Receive STM32 USB serial data on the board and forward it to the VM over UDP.

This board-side helper is receive-only. It never writes bytes to the STM32
serial port.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import termios
import time
from typing import Any


def speed_table() -> dict[int, int]:
    speeds: dict[int, int] = {}
    for value in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
        const = getattr(termios, f"B{value}", None)
        if const is not None:
            speeds[value] = const
    return speeds


SPEEDS = speed_table()
MAGIC = b"STM32USB1 "


def now_ns() -> int:
    return time.time_ns()


def printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = sum(1 for byte in data if byte in (9, 10, 13) or 32 <= byte <= 126)
    return printable / len(data)


def ascii_preview(data: bytes, limit: int = 160) -> str:
    chars = []
    for byte in data[:limit]:
        if byte in (9, 10, 13) or 32 <= byte <= 126:
            chars.append(chr(byte))
        else:
            chars.append(".")
    return "".join(chars).replace("\r", " ").replace("\n", " ")


def has_usb_device(vid: str, pid: str) -> str | None:
    for entry in Path("/sys/bus/usb/devices").glob("*"):
        vendor = entry / "idVendor"
        product = entry / "idProduct"
        if not vendor.exists() or not product.exists():
            continue
        if vendor.read_text().strip() == vid and product.read_text().strip() == pid:
            return str(entry)
    return None


def usb_device_node(usb_path: str) -> str | None:
    base = Path(usb_path)
    try:
        bus = int((base / "busnum").read_text().strip())
        dev = int((base / "devnum").read_text().strip())
    except (OSError, ValueError):
        return None
    return f"/dev/bus/usb/{bus:03d}/{dev:03d}"


def run_ch341_user_init(helper: str, usb_path: str) -> dict[str, Any]:
    usbdev = usb_device_node(usb_path)
    if not helper:
        return {"ch341_user_init": "disabled", "usbdev": usbdev}
    if not usbdev:
        return {"ch341_user_init": "skipped_no_usbdev", "helper": helper, "usbdev": usbdev}
    if not Path(helper).exists():
        return {"ch341_user_init": "skipped_missing_helper", "helper": helper, "usbdev": usbdev}
    if not os.access(helper, os.X_OK):
        return {"ch341_user_init": "skipped_not_executable", "helper": helper, "usbdev": usbdev}
    try:
        result = subprocess.run(
            [helper, usbdev],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            check=False,
        )
    except Exception as exc:
        return {
            "ch341_user_init": "error",
            "helper": helper,
            "usbdev": usbdev,
            "error": repr(exc),
        }
    return {
        "ch341_user_init": "ok" if result.returncode == 0 else "failed",
        "helper": helper,
        "usbdev": usbdev,
        "returncode": result.returncode,
        "output": result.stdout.strip()[-800:],
    }


def find_serial_device(explicit: str) -> str | None:
    if explicit and Path(explicit).exists():
        return explicit
    for entry in Path("/sys/bus/usb-serial/devices").glob("*"):
        dev = Path("/dev") / entry.name
        if dev.exists():
            return str(dev)
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        for dev in sorted(Path("/dev").glob(Path(pattern).name)):
            return str(dev)
    return None


def serial_driver_info(device: str) -> dict[str, Any]:
    tty = Path(device).name
    driver = None
    mode = "unknown"
    status_path = Path("/tmp/stm32_usb_serial_driver_status.json")
    for candidate in (
        Path("/sys/bus/usb-serial/devices") / tty / "driver",
        Path("/sys/class/tty") / tty / "device" / "driver",
    ):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists():
            driver = resolved.name
            break
    if driver == "ch341":
        mode = "formal_ch341"
    elif driver == "generic":
        mode = "generic_fallback"
    elif driver:
        mode = "other"
    status: dict[str, Any] | None = None
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            status = None
    return {
        "serial_driver": driver,
        "serial_driver_mode": mode,
        "driver_status_file": str(status_path) if status_path.exists() else None,
        "driver_status": status,
    }


def bind_generic(vid: str, pid: str) -> bool:
    path = Path("/sys/bus/usb-serial/drivers/generic/new_id")
    if not path.exists():
        return False
    try:
        path.write_text(f"{vid} {pid}")
    except OSError:
        return False
    time.sleep(1.0)
    return True


def configure_serial(fd: int, baud: int) -> None:
    if baud not in SPEEDS:
        raise ValueError(f"unsupported baud: {baud}")
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CLOCAL | termios.CREAD
    attrs[3] = 0
    attrs[4] = SPEEDS[baud]
    attrs[5] = SPEEDS[baud]
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def emit_datagram(
    sock: socket.socket,
    target: tuple[str, int],
    header: dict[str, Any],
    data: bytes = b"",
) -> None:
    payload = MAGIC + json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload += b"\n" + data
    sock.sendto(payload, target)


def json_line(handle, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-ip", required=True)
    parser.add_argument("--udp-port", type=int, default=24680)
    parser.add_argument("--vid", default="1a86")
    parser.add_argument("--pid", default="7523")
    parser.add_argument("--device", default="")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--chunk-size", type=int, default=256)
    parser.add_argument("--poll-ms", type=int, default=50)
    parser.add_argument("--health-period-sec", type=float, default=1.0)
    parser.add_argument("--duration-sec", type=float, default=0.0)
    parser.add_argument("--record-dir", default="/tmp/stm32_serial_bridge_records")
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--bind-generic", action="store_true")
    parser.add_argument("--no-bind", action="store_true")
    parser.add_argument(
        "--ch341-init-helper",
        default="/opt/parking/stm32_uart/ch341_user_init",
        help="Optional userspace CH340/CH341 initializer. It writes no serial bytes.",
    )
    parser.add_argument("--no-ch341-init", action="store_true")
    args = parser.parse_args()

    usb_path = has_usb_device(args.vid, args.pid)
    if not usb_path:
        print(json.dumps({"status": "error", "reason": "usb_device_not_found", "vid": args.vid, "pid": args.pid}))
        return 3

    ch341_init_info = {"ch341_user_init": "disabled"}
    if not args.no_ch341_init:
        ch341_init_info = run_ch341_user_init(args.ch341_init_helper, usb_path)

    device = find_serial_device(args.device)
    bind_attempted = False
    if not device and not args.no_bind and args.bind_generic:
        bind_attempted = True
        bind_generic(args.vid, args.pid)
        device = find_serial_device(args.device)
    if not device:
        print(json.dumps({"status": "error", "reason": "serial_device_not_found", "vid": args.vid, "pid": args.pid}))
        return 4

    fd = os.open(device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    configure_serial(fd, args.baud)

    record_raw = None
    record_meta = None
    session_dir = None
    if not args.no_record:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        session_dir = Path(args.record_dir) / f"session_{stamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        record_raw = (session_dir / "stm32_serial_raw.bin").open("ab")
        record_meta = (session_dir / "stm32_serial_chunks.jsonl").open("a", encoding="utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.vm_ip, args.udp_port)
    start_ns = now_ns()
    start_time = time.monotonic()
    last_health = 0.0
    last_rx_ns = None
    seq = 0
    total_bytes = 0

    startup = {
        "type": "health",
        "version": 1,
        "event": "startup",
        "board_time_ns": start_ns,
        "usb_path": usb_path,
        "device": device,
        "vid": args.vid,
        "pid": args.pid,
        "baud": args.baud,
        "bind_generic_attempted": bind_attempted,
        "record_dir": str(session_dir) if session_dir else None,
    }
    startup.update(serial_driver_info(device))
    startup.update(ch341_init_info)
    print(json.dumps(startup, ensure_ascii=False))
    emit_datagram(sock, target, startup)

    try:
        try:
            while True:
                if args.duration_sec > 0 and time.monotonic() - start_time >= args.duration_sec:
                    break
                try:
                    ready, _, _ = select.select([fd], [], [], max(0.001, args.poll_ms / 1000.0))
                except InterruptedError:
                    continue
                if ready:
                    try:
                        data = os.read(fd, max(1, args.chunk_size))
                    except BlockingIOError:
                        continue
                    except InterruptedError:
                        continue
                    if not data:
                        continue
                    seq += 1
                    recv_ns = now_ns()
                    total_bytes += len(data)
                    last_rx_ns = recv_ns
                    header = {
                        "type": "serial_chunk",
                        "version": 1,
                        "seq": seq,
                        "board_time_ns": recv_ns,
                        "device": device,
                        "baud": args.baud,
                        "bytes": len(data),
                        "total_bytes": total_bytes,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "printable_ascii_ratio": printable_ratio(data),
                        "ascii_preview": ascii_preview(data),
                    }
                    header.update(serial_driver_info(device))
                    emit_datagram(sock, target, header, data)
                    if record_raw:
                        record_raw.write(data)
                        record_raw.flush()
                    if record_meta:
                        json_line(record_meta, header)

                current = time.monotonic()
                if current - last_health >= args.health_period_sec:
                    last_health = current
                    health = {
                        "type": "health",
                        "version": 1,
                        "event": "periodic",
                        "board_time_ns": now_ns(),
                        "device": device,
                        "baud": args.baud,
                        "seq": seq,
                        "total_bytes": total_bytes,
                        "last_rx_age_sec": None if last_rx_ns is None else (now_ns() - last_rx_ns) / 1e9,
                    }
                    health.update(serial_driver_info(device))
                    emit_datagram(sock, target, health)
                    print(json.dumps(health, ensure_ascii=False))
        except KeyboardInterrupt:
            pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        sock.close()
        if record_raw:
            record_raw.close()
        if record_meta:
            record_meta.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
