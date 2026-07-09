#!/usr/bin/env python3
"""Board-side standby launcher: STM32 button token -> autonomous parking.

This helper is meant to run on the SS928 board while the system is otherwise
idle.  It listens to the STM32 UART for a standalone token (default ``CTR_PK``).
When received, it closes the UART, first ensures the YOLO UDP perception chain
is running and producing fresh slot detections, then creates the normal arm file
and launches ``board_parking_controller.py`` once.  A second bare ``CTR_PK``
while parking is treated as a safe-stop toggle by the controller: the chassis is
stopped, the controller exits normally, and ST_SB is restored.  ``CTR_PK STOP`` /
``BUTTON_STOP`` are also accepted for compatibility, but are not required.

It deliberately does not add ``--wait-stm32-trigger`` to the controller command:
the trigger has already been consumed by this standby launcher.

The launcher does not remove ``/tmp/parking_armed`` by default.  That keeps the
operator's explicit arm decision persistent across repeated button-triggered
runs; pass ``--cleanup-arm-file-on-exit`` only for a disposable test session.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_AUTOPARK_DIR = "/opt/parking/autopark"
DEFAULT_ARM_FILE = "/tmp/parking_armed"
DEFAULT_STATE_DIR = f"{DEFAULT_AUTOPARK_DIR}/state"
DEFAULT_BUTTON_RECORD_DIR = f"{DEFAULT_AUTOPARK_DIR}/demo_records"
DEFAULT_YOLO_START_SCRIPT = f"{DEFAULT_AUTOPARK_DIR}/board_start_yolo_closed_loop_monitor.sh"
DEFAULT_YOLO_PID_FILE = "/tmp/parking_yolo_closed_loop_monitor.pid"
DEFAULT_YOLO_TEE_PID_FILE = "/tmp/parking_yolo_udp_tee.pid"


def clip_text(value: str, limit: int = 2000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    keep = max(0, limit - 32)
    return text[:keep] + "...<truncated>"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def emit(event: str, **fields) -> None:
    payload = {"time": now(), "event": event}
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def import_controller(autopark_dir: str):
    sys.path.insert(0, autopark_dir)
    import board_parking_controller as bpc  # noqa: WPS433 - board-local helper

    return bpc


def controller_running() -> bool:
    try:
        out = subprocess.check_output(["ps", "w"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    for line in out.splitlines():
        if "board_parking_controller.py" in line and "grep" not in line:
            return True
    return False


def _pid_alive(pid) -> bool:
    try:
        number = int(str(pid).strip())
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _read_pid(path: str) -> int | None:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    try:
        pid = int(text.split()[0])
    except (IndexError, ValueError):
        return None
    return pid if pid > 0 else None


def _ps_text() -> str:
    try:
        return subprocess.check_output(["ps", "w"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            return subprocess.check_output(["ps"], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return ""


def _pid_from_ps_line(line: str) -> int | None:
    for token in str(line or "").split():
        try:
            pid = int(token)
        except ValueError:
            continue
        if pid > 0:
            return pid
    return None


def _first_process_pid(ps_text: str, needles: tuple[str, ...]) -> int | None:
    for line in str(ps_text or "").splitlines():
        if "grep" in line:
            continue
        if any(needle in line for needle in needles):
            pid = _pid_from_ps_line(line)
            if pid:
                return pid
    return None


def _read_process_env(pid: int | None) -> dict:
    if not pid:
        return {}
    try:
        raw = Path(f"/proc/{int(pid)}/environ").read_bytes()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode("utf-8", errors="replace")] = value.decode("utf-8", errors="replace")
    return env


def yolo_status(args) -> dict:
    yolo_pid = _read_pid(args.yolo_pid_file)
    tee_pid = _read_pid(args.yolo_tee_pid_file)
    ps_text = _ps_text()
    yolo_process_pid = _first_process_pid(
        ps_text,
        (
            "sample_parking_yolo",
            "sample_camera_rtsp",
            "parking_yolo_seg",
        ),
    )
    yolo_process_seen = any(
        needle in ps_text
        for needle in (
            "sample_parking_yolo",
            "sample_camera_rtsp",
            "parking_yolo_seg",
        )
    )
    tee_process_seen = "board_yolo_udp_tee.py" in ps_text
    yolo_alive = _pid_alive(yolo_pid) if yolo_pid is not None else False
    tee_alive = _pid_alive(tee_pid) if tee_pid is not None else False
    running = bool((yolo_alive or yolo_process_seen) and (tee_alive or tee_process_seen))
    effective_yolo_pid = yolo_pid if yolo_alive else yolo_process_pid
    yolo_env = _read_process_env(effective_yolo_pid)
    return {
        "running": running,
        "yolo_pid_file": args.yolo_pid_file,
        "yolo_pid": yolo_pid,
        "yolo_process_pid": yolo_process_pid,
        "effective_yolo_pid": effective_yolo_pid,
        "yolo_pid_alive": yolo_alive,
        "yolo_process_seen": yolo_process_seen,
        "record_path": yolo_env.get("PARKING_RECORD_PATH", ""),
        "recording_rtsp": yolo_env.get("PARKING_YOLO_RTSP", ""),
        "run_forever": yolo_env.get("PARKING_YOLO_RUN_FOREVER", ""),
        "tee_pid_file": args.yolo_tee_pid_file,
        "tee_pid": tee_pid,
        "tee_pid_alive": tee_alive,
        "tee_process_seen": tee_process_seen,
    }


def build_yolo_start_env(args, record_path: str = "") -> dict:
    env = os.environ.copy()
    env["AUTOPARK_DIR"] = args.autopark_dir
    env["LOCAL_CONTROLLER_HOST"] = args.yolo_wait_host
    env["LOCAL_CONTROLLER_PORT"] = str(args.listen_port)
    env["ACTION"] = "start"
    if record_path:
        env["PARKING_YOLO_RTSP"] = "1"
        env["PARKING_YOLO_RUN_FOREVER"] = "1"
        env["PARKING_RECORD_PATH"] = record_path
    else:
        env.pop("PARKING_RECORD_PATH", None)
    return env


def start_yolo_process(args, *, record_path: str = "", reason: str = "start") -> tuple[bool, bool]:
    """Start or restart YOLO. Return (ok, started_by_this_launcher)."""
    if not os.path.exists(args.yolo_start_script):
        emit("yolo_start_script_missing", script=args.yolo_start_script)
        return False, False

    env = build_yolo_start_env(args, record_path)
    cmd = ["/bin/sh", args.yolo_start_script]
    emit(
        "yolo_start",
        cmd=" ".join(shlex.quote(part) for part in cmd),
        reason=reason,
        recording=bool(record_path),
        record_path=record_path,
    )
    try:
        result = subprocess.run(
            cmd,
            cwd=args.autopark_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, float(args.yolo_start_timeout_sec)),
        )
    except subprocess.TimeoutExpired as exc:
        emit(
            "yolo_start_timeout",
            timeout_sec=args.yolo_start_timeout_sec,
            stdout=clip_text(exc.stdout or ""),
            stderr=clip_text(exc.stderr or ""),
        )
        return False, True
    except Exception as exc:
        emit("yolo_start_exception", error=str(exc))
        return False, True

    emit(
        "yolo_start_exit",
        returncode=result.returncode,
        stdout=clip_text(result.stdout),
        stderr=clip_text(result.stderr),
    )
    if result.returncode != 0:
        return False, True
    return True, True


def start_yolo_if_needed(args, record_path: str = "") -> tuple[bool, bool]:
    """Return (ok, started_by_this_launcher).

    When record_path is set, the button run needs a fresh per-run H264 file.
    If YOLO is already running without that exact PARKING_RECORD_PATH, restart
    it through the normal board script so the controller never moves without a
    synchronized native recording.
    """
    status = yolo_status(args)
    emit("yolo_check", **status)
    if status.get("running") and not record_path:
        emit("yolo_already_running", **status)
        return True, False
    if status.get("running") and record_path and status.get("record_path") == record_path:
        emit("yolo_recording_already_running", **status)
        return True, False
    if status.get("running") and record_path:
        emit(
            "yolo_recording_restart_required",
            current_record_path=status.get("record_path", ""),
            target_record_path=record_path,
        )
    elif not getattr(args, "yolo_autostart_enable", True):
        emit("yolo_not_running_autostart_disabled", **status)
        return False, False
    if record_path:
        try:
            Path(record_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            emit("record_dir_create_failed", record_path=record_path, error=str(exc))
            return False, False
    return start_yolo_process(
        args,
        record_path=record_path,
        reason="button_recording" if record_path else "autostart",
    )


def detection_gate_passes(payload: dict, args) -> tuple[bool, dict]:
    detections = payload.get("detections")
    if not isinstance(detections, list):
        return False, {"reason": "detections_not_list", "detection_count": 0}
    good = 0
    best_conf = None
    for det in detections:
        if not isinstance(det, dict):
            continue
        polygon = det.get("mask_polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            continue
        try:
            confidence = float(det.get("confidence", -1.0))
        except (TypeError, ValueError):
            confidence = -1.0
        if best_conf is None or confidence > best_conf:
            best_conf = confidence
        if confidence < float(args.yolo_ready_min_confidence):
            continue
        good += 1
    info = {
        "detection_count": len(detections),
        "good_detection_count": good,
        "best_confidence": best_conf,
        "min_required": int(args.yolo_ready_min_detections),
        "min_confidence": float(args.yolo_ready_min_confidence),
    }
    if good < int(args.yolo_ready_min_detections):
        info["reason"] = "not_enough_mask_confident_detections"
        return False, info
    return True, info


def wait_for_fresh_yolo(args) -> tuple[bool, dict]:
    host = str(args.yolo_wait_host or "127.0.0.1")
    port = int(args.listen_port)
    timeout_sec = max(0.1, float(args.yolo_ready_timeout_sec))
    deadline = time.monotonic() + timeout_sec
    packets = 0
    json_errors = 0
    gate_failures = 0
    last_failure: dict = {}
    emit("yolo_wait_start", host=host, port=port, timeout_sec=timeout_sec)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(0.25)
        while time.monotonic() < deadline:
            try:
                packet, source = sock.recvfrom(int(args.yolo_ready_recv_bytes))
            except socket.timeout:
                continue
            packets += 1
            try:
                payload = json.loads(packet.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError as exc:
                json_errors += 1
                last_failure = {"reason": "json_decode_error", "error": str(exc)}
                continue
            if not isinstance(payload, dict):
                gate_failures += 1
                last_failure = {"reason": "payload_not_object"}
                continue
            ok, info = detection_gate_passes(payload, args)
            if not ok:
                gate_failures += 1
                last_failure = info
                continue
            result = {
                "host": host,
                "port": port,
                "source": "%s:%d" % source,
                "packets": packets,
                "json_errors": json_errors,
                "gate_failures": gate_failures,
            }
            result.update(info)
            emit("yolo_fresh_frame", **result)
            return True, result
    except OSError as exc:
        result = {"host": host, "port": port, "error": str(exc)}
        emit("yolo_wait_bind_or_recv_error", **result)
        return False, result
    finally:
        sock.close()

    result = {
        "host": host,
        "port": port,
        "timeout_sec": timeout_sec,
        "packets": packets,
        "json_errors": json_errors,
        "gate_failures": gate_failures,
        "last_failure": last_failure,
    }
    emit("yolo_wait_timeout", **result)
    return False, result


def stop_autostarted_yolo(args, reason: str, *, force: bool = False) -> None:
    if not force and not args.yolo_stop_autostarted_on_exit:
        emit("yolo_autostarted_stop_skip", reason=reason, configured=False)
        return
    if not os.path.exists(args.yolo_start_script):
        emit("yolo_autostarted_stop_skip", reason=reason, configured=True, error="script_missing")
        return
    env = os.environ.copy()
    env["AUTOPARK_DIR"] = args.autopark_dir
    env["ACTION"] = "stop"
    cmd = ["/bin/sh", args.yolo_start_script]
    emit("yolo_autostarted_stop", reason=reason, cmd=" ".join(shlex.quote(part) for part in cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=args.autopark_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, float(args.yolo_stop_timeout_sec)),
        )
        emit(
            "yolo_autostarted_stop_exit",
            reason=reason,
            returncode=result.returncode,
            stdout=clip_text(result.stdout),
            stderr=clip_text(result.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        emit(
            "yolo_autostarted_stop_timeout",
            reason=reason,
            timeout_sec=args.yolo_stop_timeout_sec,
            stdout=clip_text(exc.stdout or ""),
            stderr=clip_text(exc.stderr or ""),
        )
    except Exception as exc:
        emit("yolo_autostarted_stop_exception", reason=reason, error=str(exc))


def wait_for_recording_ready(args, record_path: str) -> tuple[bool, dict]:
    if not record_path:
        return True, {"disabled": True}
    timeout_sec = max(0.1, min(20.0, float(args.yolo_ready_timeout_sec)))
    deadline = time.monotonic() + timeout_sec
    last_size = 0
    while time.monotonic() < deadline:
        try:
            path = Path(record_path)
            if path.exists():
                last_size = int(path.stat().st_size)
                if last_size > 0:
                    info = {
                        "reason": "recording_ready",
                        "h264_path": record_path,
                        "bytes": last_size,
                    }
                    emit("recording_ready", **info)
                    return True, info
        except OSError as exc:
            info = {"reason": "recording_stat_error", "h264_path": record_path, "error": str(exc)}
            emit("recording_wait_stat_error", **info)
            return False, info
        time.sleep(0.25)
    info = {
        "reason": "recording_not_ready",
        "h264_path": record_path,
        "timeout_sec": timeout_sec,
        "last_size": last_size,
    }
    emit("recording_not_ready", **info)
    return False, info


def ensure_yolo_ready(args, record_path: str = "") -> tuple[bool, bool, dict]:
    if not args.yolo_gate_enable and not record_path:
        emit("yolo_gate_disabled")
        return True, False, {"disabled": True}
    ok, started = start_yolo_if_needed(args, record_path=record_path)
    if not ok:
        reason = "recording_not_ready" if record_path else "yolo_start_failed"
        return False, started, {"reason": reason}
    if args.yolo_gate_enable:
        ready, info = wait_for_fresh_yolo(args)
        if not ready:
            return False, started, info
    else:
        emit("yolo_gate_disabled")
        info = {"disabled": True}
    if record_path:
        recording_ready, recording_info = wait_for_recording_ready(args, record_path)
        if not recording_ready:
            recording_info["reason"] = "recording_not_ready"
            return False, started, recording_info
        info = dict(info or {})
        info["recording"] = recording_info
    return True, started, info


def restore_normal_yolo(args, reason: str) -> None:
    ok, started = start_yolo_process(args, record_path="", reason=reason)
    emit("yolo_restore_normal_done", reason=reason, ok=ok, started_by_launcher=started)


def button_run_paths(args, stamp: str) -> dict:
    stem = f"button_autopark_{stamp}"
    state_dir = str(args.state_dir)
    record_dir = str(args.button_record_dir)
    return {
        "stem": stem,
        "log_jsonl": f"{state_dir}/{stem}.jsonl",
        "stdout_log": f"{state_dir}/{stem}.log",
        "h264_path": f"{record_dir}/{stem}.h264",
        "record_meta": f"{record_dir}/{stem}.record_meta.json",
    }


def write_record_meta(path: str, payload: dict) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        emit("record_meta_write_error", path=path, error=str(exc))


def send_safe_standby(args, bpc, reason: str) -> None:
    try:
        if args.stm32_tty:
            bpc.configure_stm32_tty(args.stm32_tty, explicit=True)
        bpc.serial_setup()
        stop_resp = bpc.send_cmd_stop().strip()
        state_resp = bpc.send_cmd("ST_SB", read_sec=2.0).strip()
        emit("safe_standby_sent", reason=reason, stop_resp=stop_resp, state_resp=state_resp)
    except Exception as exc:
        emit("safe_standby_error", reason=reason, error=str(exc))


def token_seen(text: str, token: str, bpc) -> bool:
    if hasattr(bpc, "stm32_text_has_token"):
        return bool(bpc.stm32_text_has_token(text, token))
    needle = str(token or "").strip().upper()
    return any(part == needle for part in text.upper().replace("\r", " ").replace("\n", " ").split())


def wait_for_trigger(args, bpc) -> dict:
    token = str(args.trigger_cmd or "CTR_PK").strip()
    if not token:
        raise ValueError("empty trigger token")

    if args.stm32_tty:
        bpc.configure_stm32_tty(args.stm32_tty, explicit=True)
    bpc.serial_setup()
    tty = bpc.resolve_stm32_tty(refresh=True)
    emit("trigger_wait_start", token=token, tty=tty)

    buf = b""
    fd = os.open(tty, os.O_RDWR | os.O_NOCTTY)
    try:
        while True:
            if args.stop_file and os.path.exists(args.stop_file):
                return {"ok": False, "reason": "stop_file", "token": token, "raw_tail": ""}

            # If an operator starts the controller from the PC side, back off so
            # this standby listener does not race for UART response bytes.
            if controller_running():
                os.close(fd)
                fd = -1
                emit("external_controller_detected_pause")
                while controller_running():
                    time.sleep(0.5)
                bpc.serial_setup()
                tty = bpc.resolve_stm32_tty(refresh=True)
                fd = os.open(tty, os.O_RDWR | os.O_NOCTTY)
                buf = b""
                emit("external_controller_done_resume", tty=tty)

            try:
                chunk = os.read(fd, 256)
            except OSError:
                chunk = b""
            if chunk:
                buf += chunk
                if len(buf) > 4096:
                    buf = buf[-4096:]
                text = buf.decode("ascii", "replace")
                if token_seen(text, token, bpc):
                    raw_tail = buf[-512:].decode("ascii", "replace")
                    emit("trigger_received", token=token, raw_tail=raw_tail)
                    return {"ok": True, "reason": "token", "token": token, "raw_tail": raw_tail}
            else:
                time.sleep(max(0.02, float(args.poll_sec)))
    finally:
        if fd >= 0:
            os.close(fd)


def build_controller_cmd(args, log_jsonl: str) -> list[str]:
    autopark_dir = args.autopark_dir
    cmd = [
        args.python,
        args.controller,
        "--strategy",
        "diy_first_frame_path_parking",
        "--diy-path-profile",
        "h1_structured_phase_parking",
        "--diy-path-structured-decision",
        "rollout_optimizer",
        "--diy-path-max-total-cm",
        "150",
        "--arm",
        "--arm-file",
        args.arm_file,
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        str(args.listen_port),
        "--stable-frames",
        "1",
        "--target-wait-sec",
        "0.25",
        "--settle-sec",
        "0.20",
        "--diy-path-fast-stop-response-enable",
        "--diy-path-terminal-shuffle-enable",
        "--diy-path-rollout-optimizer-config-json",
        f"{autopark_dir}/parking_rollout_optimizer_h1.json",
        "--diy-path-effective-target-y-cm",
        "1.5",
        "--diy-path-success-lateral-tol-cm",
        "2.0",
        "--diy-path-success-heading-tol-deg",
        "3.0",
        "--diy-path-side-clearance-target-cm",
        "3.0",
        "--diy-path-side-clearance-min-cm",
        "2.0",
        "--diy-path-side-clearance-hard-block-cm",
        "1.0",
        "--diy-path-side-clearance-weight",
        "16.0",
        "--diy-path-near-side-min-clearance-cm",
        "3.0",
        "--diy-path-near-side-clearance-weight",
        "22.0",
        "--diy-path-bottom-depth-success-y-cm",
        "2.0",
        "--diy-path-terminal-shuffle-heading-trigger-deg",
        "3.0",
        "--diy-path-bottom-depth-success-heading-relax-cap-deg",
        "3.0",
        "--diy-path-terminal-shuffle-forward-kinematics-json",
        f"{autopark_dir}/terminal_shuffle_forward_kinematics.json",
        "--chassis-kinematics-json",
        f"{autopark_dir}/chassis_kinematics.json",
        "--chassis-signs-json",
        f"{autopark_dir}/chassis_signs.json",
        "--require-fusion-signs",
        "--perception-filter-json",
        f"{autopark_dir}/perception_filter.json",
        "--stm32-button-stop-token",
        args.trigger_cmd,
        "--log-jsonl",
        log_jsonl,
    ]
    if args.controller_extra:
        cmd.extend(shlex.split(args.controller_extra))
    return cmd


def run_controller_once(args, trigger: dict, bpc) -> int:
    if controller_running():
        emit("controller_already_running_skip")
        return 0

    Path(args.state_dir).mkdir(parents=True, exist_ok=True)
    if args.button_record_enable:
        Path(args.button_record_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    paths = button_run_paths(args, stamp)
    log_jsonl = paths["log_jsonl"]
    stdout_log = paths["stdout_log"]
    h264_path = paths["h264_path"] if args.button_record_enable else ""
    record_meta_path = paths["record_meta"]
    latest_file = Path(args.state_dir) / "latest_log_jsonl"
    start_time = now()
    record_meta = {
        "schema": "button_autopark_record_meta.v1",
        "controller_jsonl": log_jsonl,
        "controller_stdout_log": stdout_log,
        "h264_path": h264_path,
        "record_meta": record_meta_path,
        "start_time": start_time,
        "end_time": None,
        "controller_returncode": None,
        "yolo_started_by_launcher": None,
        "recording_enabled": bool(args.button_record_enable),
        "trigger": trigger,
    }
    if args.button_record_enable:
        write_record_meta(record_meta_path, record_meta)

    yolo_started = False
    yolo_ok, yolo_started, yolo_info = ensure_yolo_ready(args, record_path=h264_path)
    record_meta["yolo_started_by_launcher"] = bool(yolo_started)
    record_meta["yolo_info"] = yolo_info
    if not yolo_ok:
        reason = "recording_not_ready" if args.button_record_enable else "yolo_not_ready"
        record_meta["end_time"] = now()
        record_meta["reason"] = reason
        if args.button_record_enable:
            write_record_meta(record_meta_path, record_meta)
        emit("controller_not_started", reason=reason, yolo_info=yolo_info)
        send_safe_standby(args, bpc, reason)
        if yolo_started:
            stop_autostarted_yolo(args, reason, force=bool(args.button_record_enable))
            if args.button_record_enable:
                restore_normal_yolo(args, f"{reason}_restore_normal")
        return 8

    Path(args.arm_file).write_text(
        "armed_by=stm32_button_autopark\n"
        f"time={now()}\n"
        f"trigger={trigger.get('token', '')}\n",
        encoding="utf-8",
    )
    cmd = build_controller_cmd(args, log_jsonl)
    latest_file.write_text(log_jsonl + "\n", encoding="utf-8")
    emit("controller_start", cmd=" ".join(shlex.quote(part) for part in cmd), log_jsonl=log_jsonl)

    rc = 127
    try:
        with open(stdout_log, "ab") as out:
            proc = subprocess.Popen(
                cmd,
                cwd=args.autopark_dir,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
            rc = int(proc.wait())
    finally:
        record_meta["end_time"] = now()
        record_meta["controller_returncode"] = rc
        if args.button_record_enable:
            try:
                record_meta["h264_bytes"] = Path(h264_path).stat().st_size if h264_path else 0
            except OSError:
                record_meta["h264_bytes"] = 0
            write_record_meta(record_meta_path, record_meta)
        if args.cleanup_arm_file_on_exit:
            try:
                os.unlink(args.arm_file)
                emit("arm_file_removed", arm_file=args.arm_file)
            except FileNotFoundError:
                pass
        else:
            emit("arm_file_preserved", arm_file=args.arm_file)
        if args.button_record_enable:
            stop_autostarted_yolo(args, "button_recording_controller_exit", force=True)
            restore_normal_yolo(args, "button_recording_controller_exit_restore_normal")
        elif yolo_started:
            stop_autostarted_yolo(args, "controller_exit")
    emit(
        "controller_exit",
        returncode=rc,
        log_jsonl=log_jsonl,
        stdout_log=stdout_log,
        h264_path=h264_path,
        record_meta=record_meta_path if args.button_record_enable else "",
    )
    return rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--autopark-dir", default=DEFAULT_AUTOPARK_DIR)
    ap.add_argument("--controller", default=f"{DEFAULT_AUTOPARK_DIR}/board_parking_controller.py")
    ap.add_argument("--python", default="/usr/local/bin/python3")
    ap.add_argument("--trigger-cmd", default="CTR_PK")
    ap.add_argument("--stm32-tty", default=os.environ.get("PARKING_STM32_TTY", ""))
    ap.add_argument("--arm-file", default=DEFAULT_ARM_FILE)
    ap.add_argument("--listen-port", type=int, default=24580)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--button-record-enable", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--button-record-dir", default=DEFAULT_BUTTON_RECORD_DIR)
    ap.add_argument("--stop-file", default=f"{DEFAULT_STATE_DIR}/stop")
    ap.add_argument("--poll-sec", type=float, default=0.05)
    ap.add_argument("--yolo-gate-enable", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--yolo-autostart-enable", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--yolo-start-script", default=DEFAULT_YOLO_START_SCRIPT)
    ap.add_argument("--yolo-pid-file", default=DEFAULT_YOLO_PID_FILE)
    ap.add_argument("--yolo-tee-pid-file", default=DEFAULT_YOLO_TEE_PID_FILE)
    ap.add_argument("--yolo-start-timeout-sec", type=float, default=70.0)
    ap.add_argument("--yolo-stop-timeout-sec", type=float, default=45.0)
    ap.add_argument("--yolo-wait-host", default="127.0.0.1")
    ap.add_argument("--yolo-ready-timeout-sec", type=float, default=20.0)
    ap.add_argument("--yolo-ready-min-detections", type=int, default=1)
    ap.add_argument("--yolo-ready-min-confidence", type=float, default=0.40)
    ap.add_argument("--yolo-ready-recv-bytes", type=int, default=65535)
    ap.add_argument("--yolo-stop-autostarted-on-exit", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--oneshot", action="store_true", help="exit after one trigger/run")
    ap.add_argument(
        "--cleanup-arm-file-on-exit",
        action="store_true",
        help="remove --arm-file after each run; default is to preserve it",
    )
    ap.add_argument("--controller-extra", default="", help="extra args appended to board_parking_controller.py")
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    Path(args.state_dir).mkdir(parents=True, exist_ok=True)
    bpc = import_controller(args.autopark_dir)
    emit(
        "launcher_start",
        trigger_cmd=args.trigger_cmd,
        autopark_dir=args.autopark_dir,
        controller=args.controller,
        state_dir=args.state_dir,
    )
    while True:
        trigger = wait_for_trigger(args, bpc)
        if not trigger.get("ok"):
            emit("launcher_stop", reason=trigger.get("reason"))
            return 0
        run_controller_once(args, trigger, bpc)
        if args.oneshot:
            return 0
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
