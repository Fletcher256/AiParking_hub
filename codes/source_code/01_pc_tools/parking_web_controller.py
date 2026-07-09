#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC-side local web console for the current H1 parking workflow."""

from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BOARD_AUTO_SSH = TOOLS / "board_auto_ssh.py"
STM32_SEND = TOOLS / "stm32_send.py"
RUN_LOG_DIR = ROOT / "artifacts" / "web_controller" / "runtime_logs"
DEMO_LOG_DIR = ROOT / "artifacts" / "dashboard_demo"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_BOARD_HOST = "192.168.137.2"
DEFAULT_BOARD_USER = "root"
DEFAULT_BOARD_PASSWORD = "ebaina"
YOLO_PORT = 24580


def stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def send_json(h: BaseHTTPRequestHandler, obj: Any, status: int = 200) -> None:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def send_html(h: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    body = text.encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def send_text(h: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    body = text.encode("utf-8", errors="replace")
    h.send_response(status)
    h.send_header("Content-Type", "text/plain; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def q(s: str) -> str:
    if not s:
        return "''"
    if re.search(r"\s", s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def parse_stat(line: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"imu": "UNKNOWN"}
    for k, v in re.findall(r"([A-Z]+)=([^\s]+)", line or ""):
        kl = k.lower()
        if kl in ("yaw", "d", "vel", "x", "y"):
            try:
                out[kl] = float(v)
            except ValueError:
                out[kl] = v
        elif kl == "drop":
            try:
                out[kl] = int(float(v))
            except ValueError:
                out[kl] = v
        elif kl == "imu":
            out["imu"] = v
        else:
            out[kl] = v
    return out


def as_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def first_present(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def get_path(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def compact_pose(obj: Any) -> Optional[Dict[str, Optional[float]]]:
    if not isinstance(obj, dict):
        return None
    y = first_present(obj.get("y_dist_cm"), obj.get("y_cm"), obj.get("target_y_dist_cm"))
    lat = first_present(obj.get("lateral_cm"), obj.get("x_cm"), obj.get("target_lateral_cm"))
    head = first_present(obj.get("heading_deg"), obj.get("yaw_deg"), obj.get("theta_deg"))
    if y is None and lat is None and head is None:
        return None
    return {"y_dist_cm": as_float(y), "lateral_cm": as_float(lat), "heading_deg": as_float(head)}


def find_pose(obj: Any) -> Optional[Dict[str, Optional[float]]]:
    if not isinstance(obj, dict):
        return None
    direct = compact_pose(obj)
    if direct:
        return direct
    for key in (
        "estimated_pose_after_correction",
        "estimated_pose_after_odom",
        "estimated_pose_after",
        "estimated_pose_before",
        "current_pose",
        "pose",
        "predicted_pose",
        "visual_pose",
        "locked_initial_pose",
    ):
        p = compact_pose(obj.get(key))
        if p:
            return p
    state = obj.get("state")
    if isinstance(state, dict):
        p = compact_pose(state.get("pose"))
        if p:
            return p
    stop_review = obj.get("stop_review")
    if isinstance(stop_review, dict):
        p = compact_pose(stop_review.get("pose"))
        if p:
            return p
    return None


def parse_cmd_bits(cmd: Any) -> Dict[str, Optional[float]]:
    text = str(cmd or "")
    out: Dict[str, Optional[float]] = {"ste": None, "signed_distance_cm": None, "distance_cm": None}
    m = re.search(r"\bSTE=([-+]?\d+(?:\.\d+)?)", text, re.I)
    if m:
        out["ste"] = as_float(m.group(1))
    m = re.search(r"\bD=([-+]?\d+(?:\.\d+)?)", text, re.I)
    if m:
        out["signed_distance_cm"] = as_float(m.group(1))
        if out["signed_distance_cm"] is not None:
            out["distance_cm"] = abs(out["signed_distance_cm"] or 0.0)
    return out


def normalize_point(p: Any) -> Optional[Dict[str, Optional[float]]]:
    if isinstance(p, dict):
        x = first_present(p.get("x_cm"), p.get("lateral_cm"), p.get("x"))
        y = first_present(p.get("y_cm"), p.get("y_dist_cm"), p.get("y"))
        h = first_present(p.get("heading_deg"), p.get("theta_deg"), p.get("yaw_deg"))
        if x is None and y is None and h is None:
            return None
        return {"x_cm": as_float(x), "y_cm": as_float(y), "heading_deg": as_float(h)}
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return {"x_cm": as_float(p[0]), "y_cm": as_float(p[1]), "heading_deg": as_float(p[2]) if len(p) > 2 else None}
    return None


def pose_to_point(p: Optional[Dict[str, Optional[float]]]) -> Optional[Dict[str, Optional[float]]]:
    if not p:
        return None
    return {"x_cm": p.get("lateral_cm"), "y_cm": p.get("y_dist_cm"), "heading_deg": p.get("heading_deg")}


def summarize_text(value: Any, max_len: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= max_len else text[:max_len] + "..."


class ParkingLogTail:
    """Read-only local JSONL tailer for dashboard visualization."""

    def __init__(self, path: str = "", max_events: int = 300) -> None:
        self.path = path or ""
        self.offset = 0
        self.last_size = 0
        self.lock = threading.Lock()
        self.events: deque[Dict[str, Any]] = deque(maxlen=max_events)
        self.decode_errors = 0
        self.state: Dict[str, Any] = self._empty_state("WAITING", "log_path_not_configured")

    def _empty_state(self, status: str, reason: str) -> Dict[str, Any]:
        return {
            "schema": "parking_log_dashboard_state.v1",
            "status": status,
            "reason": reason,
            "log_path": self.path,
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "current_pose": None,
            "locked_initial_pose": None,
            "visual_pose": None,
            "confidence": None,
            "min_margin_px": None,
            "line_risk": None,
            "effective_line_risk": None,
            "chosen_action": None,
            "step_index": None,
            "total_reverse_cm": None,
            "total_forward_shuffle_cm": None,
            "stm32": {},
            "stop_reason": None,
            "success_reason": None,
            "candidates": [],
            "event_count": 0,
            "decode_errors": self.decode_errors,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            self._poll_locked()
            return json.loads(json.dumps(self.state, ensure_ascii=False))

    def recent_events(self, limit: int = 80) -> Dict[str, Any]:
        with self.lock:
            self._poll_locked()
            return {
                "schema": "parking_log_dashboard_events.v1",
                "log_path": self.path,
                "events": list(self.events)[-limit:],
                "state_status": self.state.get("status"),
                "updated_at": self.state.get("updated_at"),
            }

    def _poll_locked(self) -> None:
        if not self.path:
            self.state.update(self._empty_state("WAITING", "log_path_not_configured"))
            return
        p = Path(self.path)
        self.state["log_path"] = str(p)
        if not p.exists():
            self.state.update(self._empty_state("WAITING", "log_not_found"))
            self.state["log_path"] = str(p)
            return
        try:
            size = p.stat().st_size
            if size < self.offset:
                self.offset = 0
            with p.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
                f.seek(self.offset)
                lines = f.readlines()
                self.offset = f.tell()
            self.last_size = size
        except Exception as e:
            self.state.update(self._empty_state("ERROR", f"read_failed:{type(e).__name__}"))
            self.state["log_path"] = str(p)
            return
        if not lines and self.state.get("event_count", 0) == 0:
            self.state.update(self._empty_state("WAITING", "waiting_for_log_events"))
            self.state["log_path"] = str(p)
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                self.decode_errors += 1
                continue
            if isinstance(obj, dict):
                self._apply_event(obj)
        self.state["decode_errors"] = self.decode_errors

    def _apply_event(self, obj: Dict[str, Any]) -> None:
        ev = str(obj.get("event") or obj.get("type") or "event")
        now = dt.datetime.now().isoformat(timespec="seconds")
        status = self._status_for_event(ev, obj)
        if status:
            self.state["status"] = status
        self.state["reason"] = obj.get("reason") or obj.get("status") or self.state.get("reason")
        self.state["updated_at"] = now
        self.state["event_count"] = int(self.state.get("event_count") or 0) + 1

        pose = find_pose(obj)
        if pose:
            self.state["current_pose"] = pose
        locked = compact_pose(obj.get("locked_initial_pose")) or compact_pose(get_path(obj, "state", "locked_initial_pose"))
        if locked:
            self.state["locked_initial_pose"] = locked
        visual_pose = compact_pose(obj.get("visual_pose")) or compact_pose(get_path(obj, "visual_review", "visual_pose"))
        if visual_pose:
            self.state["visual_pose"] = visual_pose

        self._apply_visual(obj)
        chosen = self._extract_chosen(obj)
        if chosen:
            self.state["chosen_action"] = chosen
        self._apply_step_totals(obj)
        self._apply_stm32(obj)
        if ev == "diy_path_stop":
            self.state["stop_reason"] = first_present(obj.get("reason"), obj.get("stop_reason"), get_path(obj, "stop_review", "reason"))
        if ev == "diy_path_success":
            self.state["success_reason"] = first_present(obj.get("reason"), obj.get("success_reason"), get_path(obj, "success_review", "reason"))
        if ev == "vision_lost":
            self.state["status"] = "VISION_LOST"

        candidates = self._extract_candidates(obj)
        if candidates:
            self.state["candidates"] = candidates

        self.events.append({
            "ts": obj.get("timestamp") or obj.get("ts") or now,
            "event": ev,
            "status": self.state.get("status"),
            "pose": pose,
            "chosen_action": chosen,
            "candidate_count": len(candidates) if candidates else None,
            "reason": obj.get("reason") or obj.get("stop_reason") or obj.get("success_reason"),
        })

    def _status_for_event(self, ev: str, obj: Dict[str, Any]) -> Optional[str]:
        if ev in ("diy_path_replan", "replanner_step", "candidate"):
            return "PLANNING"
        if ev in ("diy_path_step", "stm32_result"):
            return "EXECUTING"
        if ev == "diy_path_stop":
            return "STOPPED"
        if ev == "diy_path_success":
            return "SUCCESS"
        if ev == "vision_lost":
            return "VISION_LOST"
        if obj.get("error") or ev.lower().endswith("error"):
            return "ERROR"
        return None

    def _apply_visual(self, obj: Dict[str, Any]) -> None:
        vr = obj.get("visual_review") if isinstance(obj.get("visual_review"), dict) else {}
        vs = obj.get("visual_state") if isinstance(obj.get("visual_state"), dict) else {}
        for key in ("confidence", "min_margin_px", "line_risk", "effective_line_risk"):
            val = first_present(obj.get(key), vr.get(key), vs.get(key), get_path(vr, "checks", key))
            if val is not None:
                self.state[key] = val

    def _apply_step_totals(self, obj: Dict[str, Any]) -> None:
        for key in ("step_index", "steps", "total_reverse_cm", "total_forward_shuffle_cm"):
            val = first_present(obj.get(key), get_path(obj, "state", key), get_path(obj, "stop_review", key))
            if val is not None:
                if key == "steps":
                    self.state["step_index"] = val
                else:
                    self.state[key] = val

    def _apply_stm32(self, obj: Dict[str, Any]) -> None:
        src = obj.get("stm32_result") if isinstance(obj.get("stm32_result"), dict) else {}
        od = obj.get("odom_delta") if isinstance(obj.get("odom_delta"), dict) else {}
        stat_after = first_present(obj.get("stat_after"), src.get("stat_after"), src.get("stat"))
        parsed = parse_stat(stat_after if isinstance(stat_after, str) else "")
        stm = dict(self.state.get("stm32") or {})
        stm.update({
            "ack": first_present(src.get("ack"), obj.get("ack")),
            "done": first_present(src.get("done"), obj.get("done")),
            "stat_summary": summarize_text(stat_after),
            "odom_progress_cm": first_present(obj.get("odom_progress_cm"), src.get("odom_progress_cm"), od.get("progress_cm")),
            "yaw_delta_deg": first_present(obj.get("yaw_delta_deg"), src.get("yaw_delta_deg"), od.get("yaw_delta_deg")),
            "imu": first_present(src.get("imu"), obj.get("imu"), parsed.get("imu")),
            "drop": first_present(src.get("drop"), obj.get("drop"), parsed.get("drop")),
            "motion_events": summarize_text(first_present(obj.get("motion_events"), src.get("motion_events")), 500),
        })
        self.state["stm32"] = {k: v for k, v in stm.items() if v not in (None, "")}

    def _extract_chosen(self, obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw = first_present(obj.get("chosen_action"), obj.get("selected_action"), get_path(obj, "plan", "chosen_action"), get_path(obj, "new_plan", "chosen_action"))
        if isinstance(raw, dict):
            return self._normalize_candidate(raw, self.state.get("current_pose"), selected=True)
        return None

    def _extract_candidates(self, obj: Dict[str, Any]) -> List[Dict[str, Any]]:
        buckets: List[Any] = []
        for path in (
            ("new_plan", "planned_actions"),
            ("plan", "planned_actions"),
            ("planned_actions",),
            ("candidates",),
            ("candidate_scores",),
        ):
            val = get_path(obj, *path)
            if isinstance(val, list):
                buckets.extend(val)
        for key in ("chosen_action", "selected_action"):
            val = obj.get(key)
            if isinstance(val, dict):
                buckets.append(val)
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        current_pose = self.state.get("current_pose")
        selected_cmd = None
        chosen = self._extract_chosen(obj)
        if chosen:
            selected_cmd = chosen.get("cmd")
        for raw in buckets[:80]:
            if not isinstance(raw, dict):
                continue
            cand = self._normalize_candidate(raw, current_pose, selected=(selected_cmd is not None and self._candidate_cmd(raw) == selected_cmd))
            sig = f"{cand.get('cmd')}|{cand.get('score')}|{cand.get('status')}"
            if sig in seen:
                continue
            seen.add(sig)
            out.append(cand)
        return out

    def _candidate_cmd(self, raw: Dict[str, Any]) -> str:
        action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
        return str(first_present(raw.get("cmd"), raw.get("command"), action.get("cmd"), action.get("command"), ""))

    def _normalize_candidate(self, raw: Dict[str, Any], current_pose: Any, selected: bool = False) -> Dict[str, Any]:
        action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
        cmd = self._candidate_cmd(raw)
        bits = parse_cmd_bits(cmd)
        ste = first_present(raw.get("ste"), raw.get("servo"), action.get("ste"), action.get("servo"), bits.get("ste"))
        signed_d = first_present(raw.get("signed_distance_cm"), action.get("signed_distance_cm"), bits.get("signed_distance_cm"))
        dist = first_present(raw.get("distance_cm"), action.get("distance_cm"), bits.get("distance_cm"), abs(signed_d) if isinstance(signed_d, (int, float)) else None)
        pred = compact_pose(raw.get("predicted_pose")) or compact_pose(raw.get("pose_after")) or compact_pose(raw.get("end_pose"))
        hard_block = bool(first_present(raw.get("hard_block"), raw.get("blocked"), raw.get("rejected"), False))
        status = str(raw.get("status") or ("selected" if selected else ("blocked" if hard_block else "candidate")))
        if selected:
            status = "selected"
        traj = []
        raw_traj = first_present(raw.get("trajectory"), raw.get("path"), raw.get("samples"))
        if isinstance(raw_traj, list):
            traj = [p for p in (normalize_point(x) for x in raw_traj) if p]
        if not traj:
            a = pose_to_point(current_pose if isinstance(current_pose, dict) else None)
            b = pose_to_point(pred)
            if a and b:
                traj = [a, b]
            elif a:
                y0 = a.get("y_cm") or 0.0
                d = as_float(signed_d)
                y1 = y0 - abs(d or as_float(dist) or 3.0)
                traj = [a, {"x_cm": a.get("x_cm"), "y_cm": y1, "heading_deg": a.get("heading_deg")}]
        return {
            "cmd": cmd,
            "ste": as_float(ste),
            "distance_cm": as_float(dist),
            "signed_distance_cm": as_float(signed_d),
            "score": as_float(first_present(raw.get("score"), raw.get("final_score"), raw.get("cost"), get_path(raw, "scoring_terms", "final_score"))),
            "status": status,
            "hard_block": hard_block,
            "block_reason": str(first_present(raw.get("block_reason"), raw.get("reject_reason"), raw.get("reason"), "ok")),
            "predicted_pose": pred,
            "trajectory": traj,
            "kinematics_source": str(first_present(raw.get("kinematics_source"), raw.get("source"), "")),
            "reason": str(first_present(raw.get("reason"), raw.get("score_reason"), "")),
        }


class Ring:
    def __init__(self, n: int = 1200) -> None:
        self.lines: deque[str] = deque(maxlen=n)
        self.lock = threading.Lock()

    def add(self, line: str) -> None:
        with self.lock:
            self.lines.append(line.rstrip("\r\n"))

    def add_text(self, prefix: str, text: str) -> None:
        for line in (text or "").splitlines():
            self.add(prefix + line)

    def tail(self, n: int = 200) -> List[str]:
        with self.lock:
            return list(self.lines)[-n:]


class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.proc: Optional[subprocess.Popen[str]] = None
        self.lock = threading.Lock()
        self.output = Ring()
        self.last_log_jsonl: Optional[str] = None
        self.last_returncode: Optional[int] = None
        self.last_error: Optional[str] = None
        self.last_command_safe: str = ""
        self.parking_log_tail = ParkingLogTail(getattr(args, "parking_log_jsonl", "") or os.environ.get("PARKING_DASHBOARD_LOG_JSONL", ""))
        RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

    def py(self) -> str:
        return sys.executable

    def redact(self, cmd: List[str]) -> str:
        out: List[str] = []
        hide = False
        for x in cmd:
            if hide:
                out.append("****")
                hide = False
                continue
            out.append(x)
            if x in ("--password", "--board-password"):
                hide = True
        return " ".join(q(x) for x in out)

    def board_cmd(self, remote: str, timeout: int = 30, risk: bool = False) -> List[str]:
        cmd = [
            self.py(), str(BOARD_AUTO_SSH), "run",
            "--host", self.args.board_host,
            "--user", self.args.board_user,
            "--password", self.args.board_password,
            "--command-timeout", str(timeout),
        ]
        if risk:
            cmd.append("--allow-risk")
        cmd.append(remote)
        return cmd

    def local_run(self, cmd: List[str], timeout: int = 20) -> Tuple[int, str]:
        try:
            cp = subprocess.run(
                cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            return cp.returncode, cp.stdout or ""
        except subprocess.TimeoutExpired as e:
            out = e.stdout if isinstance(e.stdout, str) else ""
            return 124, out + "\nTIMEOUT"
        except Exception as e:
            return 1, f"{type(e).__name__}: {e}"

    def running(self) -> bool:
        with self.lock:
            if self.proc is None:
                return False
            rc = self.proc.poll()
            if rc is None:
                return True
            self.last_returncode = rc
            self.proc = None
            return False

    def start(self) -> Dict[str, Any]:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return {"ok": False, "error": "parking_already_running"}
            remote_log = f"/tmp/parking_web_line_follow_{stamp()}.jsonl"
            local_log = RUN_LOG_DIR / (Path(remote_log).stem + ".stdout.log")
            remote = build_remote_parking_command(remote_log)
            cmd = self.board_cmd(remote, timeout=260, risk=True)
            self.last_log_jsonl = remote_log
            self.last_command_safe = self.redact(cmd)
            self.output.add(f"[web] start parking log={remote_log}")
            self.output.add(f"[web] command={self.last_command_safe}")
            try:
                f = open(local_log, "a", encoding="utf-8", errors="replace")
                p = subprocess.Popen(
                    cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                )
                self.proc = p
                self.last_returncode = None
                threading.Thread(target=self._read_proc, args=(p, f), daemon=True).start()
                return {"ok": True, "running": True, "log_jsonl": remote_log,
                        "command": self.last_command_safe, "local_runtime_log": str(local_log)}
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.output.add("[web] start failed: " + self.last_error)
                return {"ok": False, "error": self.last_error}

    def _read_proc(self, p: subprocess.Popen[str], f: Any) -> None:
        try:
            if p.stdout is not None:
                for line in p.stdout:
                    self.output.add(line)
                    try:
                        f.write(line)
                        f.flush()
                    except Exception:
                        pass
            rc = p.wait()
            with self.lock:
                self.last_returncode = rc
                if self.proc is p:
                    self.proc = None
            self.output.add(f"[web] parking process exited rc={rc}")
        finally:
            try:
                f.close()
            except Exception:
                pass

    def stop(self) -> Dict[str, Any]:
        cmd = [
            self.py(), str(STM32_SEND),
            "--host", self.args.board_host,
            "--user", self.args.board_user,
            "--password", self.args.board_password,
            "--cmd", "STOP",
            "--read-sec", "1.0",
        ]
        safe = self.redact(cmd)
        self.output.add("[web] STOP requested: " + safe)
        rc, out = self.local_run(cmd, timeout=20)
        self.output.add_text("[STOP] ", out)
        return {"ok": rc == 0, "returncode": rc, "output": out, "command": safe}

    def readonly_board_status(self) -> Dict[str, Any]:
        remote = (
            "ps w | grep -E 'yolo|board_parking_controller' | grep -v grep || true; "
            "if test -e /tmp/parking_armed; then echo ARM_FILE=1; else echo ARM_FILE=0; fi; "
            "ls -t /tmp/parking_web_line_follow_*.jsonl /tmp/parking_button_autopark/button_autopark_*.jsonl "
            "/tmp/parking_button_autopark/manual_line_follow_*.jsonl /tmp/parking_web_h1_lattice_*.jsonl "
            "/tmp/parking_h1_lattice_terminal_fast_*.jsonl /tmp/parking_h1_lattice_mpc_*.jsonl "
            "2>/dev/null | head -1 | sed 's/^/LATEST_LOG=/'"
        )
        rc, out = self.local_run(self.board_cmd(remote, timeout=15), timeout=20)
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        latest = None
        for line in lines:
            if line.startswith("LATEST_LOG="):
                latest = line.split("=", 1)[1].strip() or None
        if latest and not self.last_log_jsonl:
            self.last_log_jsonl = latest
        return {
            "reachable": rc == 0,
            "arm_file_exists": any(x == "ARM_FILE=1" for x in lines),
            "yolo_running": any("yolo" in x.lower() for x in lines),
            "controller_running": any("board_parking_controller" in x for x in lines),
            "latest_log": latest,
            "tail": lines[-10:],
        }

    def stm32_status(self, skip: bool) -> Dict[str, Any]:
        if skip:
            return {"stat_ok": False, "imu": "UNKNOWN", "reason": "parking_running_skip_stat"}
        cmd = [
            self.py(), str(STM32_SEND),
            "--host", self.args.board_host,
            "--user", self.args.board_user,
            "--password", self.args.board_password,
            "--cmd", "STAT",
            "--read-sec", "0.8",
        ]
        rc, out = self.local_run(cmd, timeout=15)
        stat = ""
        for line in out.splitlines():
            if line.strip().startswith("STAT"):
                stat = line.strip()
        parsed = parse_stat(stat)
        parsed.update({"stat_ok": bool(rc == 0 and stat), "raw": stat, "returncode": rc})
        return parsed

    def status(self) -> Dict[str, Any]:
        run = self.running()
        b = self.readonly_board_status()
        s = self.stm32_status(skip=run)
        summary = self.latest_summary()
        return {
            "board_host": self.args.board_host,
            "board_reachable": b["reachable"],
            "arm_file_exists": b["arm_file_exists"],
            "stm32": s,
            "yolo": {"process_running": b["yolo_running"], "listen_port": 24580},
            "parking": {
                "running": run,
                "last_log_jsonl": self.last_log_jsonl or summary.get("log_jsonl"),
                "last_stop_reason": summary.get("final_stop_reason"),
                "last_success": summary.get("success"),
                "last_pose": summary.get("last_pose"),
                "last_planning_timing": summary.get("last_planning_timing"),
                "last_returncode": self.last_returncode,
                "last_error": self.last_error,
            },
            "raw_board_status_tail": b.get("tail", []),
        }

    def latest_summary(self) -> Dict[str, Any]:
        rc, out = self.local_run(self.board_cmd(summary_remote_script(self.last_log_jsonl), timeout=25), timeout=30)
        text = extract_json(out)
        if not text:
            return {"ok": False, "error": "no_summary_json", "returncode": rc, "raw_tail": out[-1000:]}
        try:
            obj = json.loads(text)
        except Exception as e:
            return {"ok": False, "error": "json_parse_failed:" + str(e), "returncode": rc, "raw_tail": out[-1000:]}
        if obj.get("log_jsonl"):
            self.last_log_jsonl = obj["log_jsonl"]
        obj["ok"] = bool(rc == 0 and not obj.get("error"))
        obj["returncode"] = rc
        return obj

    def parking_log_state(self) -> Dict[str, Any]:
        return self.parking_log_tail.snapshot()

    def parking_log_events(self) -> Dict[str, Any]:
        return self.parking_log_tail.recent_events()


def build_remote_parking_command(log_path: str) -> str:
    return " ".join([
        "cd", "/opt/parking/autopark", "&&",
        "echo", f"LOG={log_path}", ";",
        "/usr/local/bin/python3", "/opt/parking/autopark/board_parking_controller.py",
        "--strategy", "diy_first_frame_path_parking",
        "--diy-path-profile", "h1_structured_phase_parking",
        "--diy-path-structured-decision", "rollout_optimizer",
        "--diy-path-max-total-cm", "150",
        "--arm",
        "--arm-file", "/tmp/parking_armed",
        "--listen-host", "127.0.0.1",
        "--listen-port", str(YOLO_PORT),
        "--stable-frames", "1",
        "--target-wait-sec", "0.25",
        "--settle-sec", "0.20",
        "--diy-path-fast-stop-response-enable",
        "--diy-path-terminal-shuffle-enable",
        "--diy-path-rollout-optimizer-config-json", "/opt/parking/autopark/parking_rollout_optimizer_h1.json",
        "--diy-path-effective-target-y-cm", "1.5",
        "--diy-path-success-lateral-tol-cm", "2.0",
        "--diy-path-success-heading-tol-deg", "3.0",
        "--diy-path-side-clearance-target-cm", "3.0",
        "--diy-path-side-clearance-min-cm", "2.0",
        "--diy-path-side-clearance-hard-block-cm", "1.0",
        "--diy-path-side-clearance-weight", "16.0",
        "--diy-path-near-side-min-clearance-cm", "3.0",
        "--diy-path-near-side-clearance-weight", "22.0",
        "--diy-path-bottom-depth-success-y-cm", "2.0",
        "--diy-path-terminal-shuffle-heading-trigger-deg", "3.0",
        "--diy-path-bottom-depth-success-heading-relax-cap-deg", "3.0",
        "--diy-path-terminal-shuffle-forward-kinematics-json", "/opt/parking/autopark/terminal_shuffle_forward_kinematics.json",
        "--chassis-kinematics-json", "/opt/parking/autopark/chassis_kinematics.json",
        "--chassis-signs-json", "/opt/parking/autopark/chassis_signs.json",
        "--require-fusion-signs",
        "--perception-filter-json", "/opt/parking/autopark/perception_filter.json",
        "--log-jsonl", log_path,
    ])


def extract_json(text: str) -> str:
    start = text.find('{"summary_schema"')
    if start < 0:
        start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start:end + 1]
    return ""


def summary_remote_script(preferred: Optional[str]) -> str:
    pref = json.dumps(preferred or "")
    return r'''python3 - <<'PY'
import glob,json,os
preferred=''' + pref + r'''
patterns=[
 '/tmp/parking_web_line_follow_*.jsonl',
 '/tmp/parking_button_autopark/button_autopark_*.jsonl',
 '/tmp/parking_button_autopark/manual_line_follow_*.jsonl',
 '/tmp/parking_web_h1_lattice_*.jsonl',
 '/tmp/parking_h1_lattice_terminal_fast_*.jsonl',
 '/tmp/parking_h1_lattice_mpc_successfix_*.jsonl',
 '/tmp/parking_h1_lattice_mpc_*.jsonl',
]
logs=[]
if preferred and os.path.exists(preferred): logs.append(preferred)
for p in patterns: logs += glob.glob(p)
logs=sorted(set(logs),key=lambda p: os.path.getmtime(p),reverse=True)
if not logs:
 print(json.dumps({'summary_schema':'parking_web_log_summary.v1','error':'no_logs'},ensure_ascii=False)); raise SystemExit(0)
log=logs[0]; steps=[]; last_pose=None; last_plan=None; stop_reason=None; success=False
def pose(o):
 for k in ('estimated_pose_after_correction','estimated_pose_after_odom','estimated_pose_after','pose'):
  v=o.get(k)
  if isinstance(v,dict): return {x:v.get(x) for x in ('y_dist_cm','lateral_cm','heading_deg')}
 return None
def timing(p):
 if not isinstance(p,dict): return None
 t=(p.get('search') or {}).get('planning_timing') or None
 if not t: return None
 return {k:t.get(k) for k in ('total_ms','terminal_fast_active','effective_horizon','effective_beam_width','effective_candidate_limit','candidate_eval_count')}
with open(log,'r',errors='ignore') as f:
 for line in f:
  try: o=json.loads(line)
  except Exception: continue
  ev=o.get('event')
  if ev in ('diy_path_plan_built','diy_path_replan','diy_path_terminal_shuffle_plan'):
   t=timing(o.get('plan') or o.get('new_plan') or o.get('shuffle_plan'))
   if t: last_plan=t
  elif ev=='diy_path_step':
   ch=o.get('chosen_action') or {}; od=o.get('odom_delta') or {}; p=pose(o)
   if p: last_pose=p
   steps.append({'step':o.get('steps'),'step_index':o.get('step_index'),'cmd':ch.get('cmd'),'ste':ch.get('ste'),'distance_cm':ch.get('distance_cm'),'y_dist_cm':None if not p else p.get('y_dist_cm'),'lateral_cm':None if not p else p.get('lateral_cm'),'heading_deg':None if not p else p.get('heading_deg'),'progress_cm':od.get('progress_cm'),'yaw_delta_deg':od.get('yaw_delta_deg'),'planning_total_ms':None if not last_plan else last_plan.get('total_ms'),'terminal_fast_active':None if not last_plan else last_plan.get('terminal_fast_active')})
   steps=steps[-200:]
  elif ev=='diy_path_success':
   success=True
   p=pose(o)
   if p: last_pose=p
  elif ev=='diy_path_stop':
   stop_reason=o.get('reason')
   if (o.get('stop_review') or {}).get('success'): success=True
   st=o.get('state') or {}; p=st.get('pose') or (o.get('stop_review') or {}).get('pose')
   if isinstance(p,dict): last_pose={x:p.get(x) for x in ('y_dist_cm','lateral_cm','heading_deg')}
print(json.dumps({'summary_schema':'parking_web_log_summary.v1','log_jsonl':log,'steps':steps,'final_stop_reason':stop_reason,'success':bool(success or stop_reason in ('parked','terminal_observed_success')),'last_pose':last_pose,'last_planning_timing':last_plan,'step_count':len(steps)},ensure_ascii=False,separators=(',',':')))
PY'''


HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>H1 Parking Console</title>
<style>
:root{--bg:#101317;--panel:#181d24;--panel2:#202733;--text:#e8edf5;--muted:#9aa7b5;--green:#37d67a;--red:#ff5d5d;--yellow:#ffd166;--blue:#63a4ff;--border:#303847}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,"Microsoft YaHei",sans-serif}header{padding:18px 22px;border-bottom:1px solid var(--border);display:flex;gap:16px;align-items:center;justify-content:space-between}h1{margin:0;font-size:22px}.pill{padding:8px 14px;border-radius:999px;background:var(--panel2);font-weight:700}.READY{color:var(--blue)}.RUNNING{color:var(--yellow)}.SUCCESS{color:var(--green)}.STOPPED{color:var(--muted)}.ERROR{color:var(--red)}main{display:grid;grid-template-columns:320px 1fr;gap:16px;padding:16px}.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:14px;margin-bottom:14px}.card h2{font-size:16px;margin:0 0 12px}.row{display:flex;justify-content:space-between;gap:10px;border-bottom:1px dashed #2b3340;padding:7px 0}.row:last-child{border-bottom:0}.muted{color:var(--muted)}button{border:0;border-radius:10px;padding:11px 14px;margin:4px;cursor:pointer;color:#071015;font-weight:700;background:var(--blue)}button.secondary{background:#d5deea}button.stop{background:var(--red);color:white}button.start{background:var(--green)}button:disabled{opacity:.45}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}.console{height:360px;overflow:auto;background:#06080b;border:1px solid var(--border);border-radius:10px;padding:10px;font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap}.cmd{font-family:Consolas,monospace;font-size:12px;word-break:break-all;background:#0b0e13;border-radius:8px;padding:10px;color:#b9c7d8}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--border);padding:6px 8px;text-align:left}th{color:#b9c7d8;background:#151a21;position:sticky;top:0}.fast{color:var(--green);font-weight:700}.slow{color:var(--red);font-weight:700}.mid{color:var(--yellow);font-weight:700}@media(max-width:900px){main{grid-template-columns:1fr}.grid2{grid-template-columns:1fr}}
</style></head><body>
<header><h1>H1 / 里程碑2 本地泊车控制台</h1><div id="topState" class="pill READY">READY</div></header>
<main><section>
<div class="card"><h2>状态</h2><div id="statusCards"></div></div>
<div class="card"><h2>控制</h2><button class="secondary" onclick="refreshStatus()">Refresh Status</button><button id="startBtn" class="start" onclick="startParking()">Start Parking</button><button class="stop" onclick="sendStop()">Emergency STOP</button><button class="secondary" onclick="loadSummary()">Load Latest Log Summary</button><button class="secondary" onclick="location.href='/viewer'">Read-only Log Viewer</button></div>
<div class="card"><h2>最近命令</h2><div id="cmdBox" class="cmd muted">尚未启动</div></div>
</section><section>
<div class="grid2"><div class="card"><h2>实时输出</h2><div id="output" class="console"></div></div><div class="card"><h2>最后摘要</h2><div id="summaryBox" class="muted">尚未加载</div></div></div>
<div class="card"><h2>Step Summary</h2><div style="max-height:420px;overflow:auto"><table id="stepTable"><thead><tr><th>#</th><th>cmd</th><th>y</th><th>lat</th><th>head</th><th>progress</th><th>yawΔ</th><th>plan ms</th><th>terminal fast</th></tr></thead><tbody></tbody></table></div></div>
</section></main>
<script>
function fmt(v,d=2){return(v===null||v===undefined||isNaN(Number(v)))?'--':Number(v).toFixed(d)}
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function setTop(s){let e=document.getElementById('topState');e.className='pill '+s;e.textContent=s}
function rows(o){return Object.entries(o).map(([k,v])=>`<div class="row"><span class="muted">${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}
async function refreshStatus(){try{let s=await(await fetch('/api/status')).json(),p=s.parking||{},stm=s.stm32||{},y=s.yolo||{};let state='READY';if(p.running)state='RUNNING';else if(p.last_success)state='SUCCESS';else if(p.last_stop_reason)state='STOPPED';if(!s.board_reachable)state='ERROR';setTop(state);document.getElementById('startBtn').disabled=!!p.running;document.getElementById('statusCards').innerHTML='<div class="card"><h2>Board</h2>'+rows({host:s.board_host,reachable:s.board_reachable?'YES':'NO','arm file':s.arm_file_exists?'YES':'NO'})+'</div><div class="card"><h2>YOLO</h2>'+rows({running:y.process_running?'YES':'NO',port:y.listen_port})+'</div><div class="card"><h2>STM32 / IMU</h2>'+rows({stat:stm.stat_ok?'OK':'--',IMU:stm.imu||'UNKNOWN',yaw:fmt(stm.yaw),D:fmt(stm.d),VEL:fmt(stm.vel)})+'</div><div class="card"><h2>Parking</h2>'+rows({running:p.running?'YES':'NO',log:p.last_log_jsonl||'--',stop:p.last_stop_reason||'--',success:p.last_success?'YES':'NO'})+'</div>'}catch(e){setTop('ERROR')}}
async function startParking(){if(!confirm('小车将真实运动，确认周围无障碍物/电线，是否继续？'))return;let j=await(await fetch('/api/start_parking',{method:'POST'})).json();if(!j.ok){alert('启动失败: '+(j.error||'unknown'));return}document.getElementById('cmdBox').textContent=j.command||'';setTop('RUNNING');refreshOutput();refreshStatus()}
async function sendStop(){let j=await(await fetch('/api/stop',{method:'POST'})).json();alert('STOP 已发送，返回码: '+j.returncode);refreshOutput();refreshStatus()}
function cls(ms){if(ms===null||ms===undefined)return'';if(ms>3000)return'slow';if(ms>1000)return'mid';return'fast'}
async function loadSummary(){let j=await(await fetch('/api/latest_log_summary')).json();if(!j.ok&&j.error){document.getElementById('summaryBox').textContent='加载失败: '+j.error;return}let p=j.last_pose||{},t=j.last_planning_timing||{};document.getElementById('summaryBox').innerHTML=rows({log:j.log_jsonl||'--',success:j.success?'YES':'NO',stop:j.final_stop_reason||'--',steps:j.step_count||0,y:fmt(p.y_dist_cm),lateral:fmt(p.lateral_cm),heading:fmt(p.heading_deg),'last plan ms':fmt(t.total_ms,1),'terminal fast':t.terminal_fast_active?'YES':'NO'});let tb=document.querySelector('#stepTable tbody');tb.innerHTML='';(j.steps||[]).forEach((s,i)=>{let tr=document.createElement('tr'),c=cls(s.planning_total_ms);tr.innerHTML=`<td>${esc(s.step??i+1)}</td><td>${esc(s.cmd)}</td><td>${fmt(s.y_dist_cm)}</td><td>${fmt(s.lateral_cm)}</td><td>${fmt(s.heading_deg)}</td><td>${fmt(s.progress_cm)}</td><td>${fmt(s.yaw_delta_deg)}</td><td class="${c}">${fmt(s.planning_total_ms,1)}</td><td class="${s.terminal_fast_active?'fast':''}">${s.terminal_fast_active?'YES':'NO'}</td>`;tb.appendChild(tr)})}
async function refreshOutput(){try{let j=await(await fetch('/api/output')).json(),e=document.getElementById('output');e.textContent=(j.lines||[]).join('\n');e.scrollTop=e.scrollHeight;if(j.running)setTop('RUNNING')}catch(e){}}
setInterval(refreshOutput,1000);setInterval(refreshStatus,4000);refreshStatus();refreshOutput();loadSummary();
</script></body></html>"""


VIEWER_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parking Log Viewer - Read Only</title>
<style>
:root{--bg:#0b1017;--panel:#141b25;--panel2:#1c2633;--text:#e9f1fb;--muted:#9baabd;--border:#2d3949;--green:#32d583;--red:#ff6b6b;--yellow:#ffd166;--blue:#5aa7ff;--gray:#778394}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#152033 0,#0b1017 55%);color:var(--text);font-family:Segoe UI,Arial,"Microsoft YaHei",sans-serif}
header{padding:16px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:20px;margin:0}.badge{border:1px solid #3a495e;border-radius:999px;padding:7px 12px;background:#0f1620;color:var(--green);font-weight:800}.muted{color:var(--muted)}
main{display:grid;grid-template-columns:minmax(340px,1.3fr) minmax(320px,.8fr);gap:14px;padding:14px}.panel{background:rgba(20,27,37,.94);border:1px solid var(--border);border-radius:16px;padding:14px;box-shadow:0 12px 30px rgba(0,0,0,.22)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:10px}.card{background:var(--panel2);border:1px solid var(--border);border-radius:12px;padding:10px}.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:20px;font-weight:800;margin-top:5px}
svg{width:100%;height:min(62vh,620px);background:#081019;border:1px solid #263345;border-radius:12px}.legend{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;margin-top:8px}.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:5px}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid var(--border);padding:6px 7px;text-align:left;vertical-align:top}th{color:#c8d4e4;background:#111923;position:sticky;top:0}.scroll{max-height:48vh;overflow:auto}
.selected{color:var(--green);font-weight:800}.blocked{color:var(--red);font-weight:800}.terminal{color:var(--yellow);font-weight:800}.state{font-weight:900}.ok{color:var(--green)}.warn{color:var(--yellow)}.bad{color:var(--red)}
@media(max-width:900px){main{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,1fr)}svg{height:460px}}
</style></head><body>
<header><div><h1>候选轨迹 / 规划可解释</h1><div class="muted">只读读取泊车 JSONL；不提供任何控制命令</div></div><div class="badge">READ ONLY</div></header>
<main>
<section class="panel">
  <div class="grid" id="cards"></div>
  <svg id="map" viewBox="0 0 760 520" role="img" aria-label="parking top down map"></svg>
  <div class="legend">
    <span><i class="dot" style="background:#32d583"></i>selected</span>
    <span><i class="dot" style="background:#5aa7ff"></i>candidate</span>
    <span><i class="dot" style="background:#ff6b6b"></i>blocked/rejected</span>
    <span><i class="dot" style="background:#ffd166"></i>terminal/shuffle</span>
    <span class="muted">坐标约定：x=lateral_cm，y=y_dist_cm</span>
  </div>
</section>
<aside class="panel">
  <h2 style="margin:0 0 10px">候选动作</h2>
  <div class="scroll"><table id="cand"><thead><tr><th>status</th><th>cmd</th><th>score</th><th>pred y/lat/head</th><th>reason</th></tr></thead><tbody></tbody></table></div>
  <h2 style="margin:18px 0 10px">安全 / 传感状态</h2>
  <div id="safety"></div>
  <h2 style="margin:18px 0 10px">日志源</h2>
  <div id="source" class="muted"></div>
</aside>
</main>
<script>
function num(v){let n=Number(v);return Number.isFinite(n)?n:null}
function fmt(v,d=2){let n=num(v);return n===null?'N/A':n.toFixed(d)}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function card(k,v,cls=''){return `<div class="card"><div class="k">${esc(k)}</div><div class="v ${cls}">${esc(v)}</div></div>`}
function color(c){let st=String(c.status||'candidate').toLowerCase(),cmd=String(c.cmd||'').toLowerCase();if(st.includes('selected'))return '#32d583';if(st.includes('block')||st.includes('reject')||c.hard_block)return '#ff6b6b';if(cmd.includes('shuffle')||String(c.reason||'').includes('terminal'))return '#ffd166';return '#5aa7ff'}
function cls(c){let st=String(c.status||'candidate').toLowerCase();if(st.includes('selected'))return 'selected';if(st.includes('block')||st.includes('reject')||c.hard_block)return 'blocked';if(String(c.cmd||'').toLowerCase().includes('shuffle'))return 'terminal';return ''}
function xy(p){let x=num(p.x_cm),y=num(p.y_cm);if(x===null||y===null)return null;return [380+x*8,470-y*7]}
function line(svg,x1,y1,x2,y2,stroke,w=1,op=1,dash=''){let e=document.createElementNS('http://www.w3.org/2000/svg','line');e.setAttribute('x1',x1);e.setAttribute('y1',y1);e.setAttribute('x2',x2);e.setAttribute('y2',y2);e.setAttribute('stroke',stroke);e.setAttribute('stroke-width',w);e.setAttribute('opacity',op);if(dash)e.setAttribute('stroke-dasharray',dash);svg.appendChild(e)}
function text(svg,x,y,t,fill='#cfd8e3',size=12){let e=document.createElementNS('http://www.w3.org/2000/svg','text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('fill',fill);e.setAttribute('font-size',size);e.textContent=t;svg.appendChild(e)}
function drawPose(svg,pose,label,fill){if(!pose)return;let p=xy({x_cm:pose.lateral_cm,y_cm:pose.y_dist_cm});if(!p)return;let h=num(pose.heading_deg)||0,r=18,a=(-90+h)*Math.PI/180;let g=document.createElementNS('http://www.w3.org/2000/svg','g');let c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',p[0]);c.setAttribute('cy',p[1]);c.setAttribute('r',6);c.setAttribute('fill',fill);g.appendChild(c);let x2=p[0]+Math.cos(a)*r,y2=p[1]+Math.sin(a)*r;let ar=document.createElementNS('http://www.w3.org/2000/svg','line');ar.setAttribute('x1',p[0]);ar.setAttribute('y1',p[1]);ar.setAttribute('x2',x2);ar.setAttribute('y2',y2);ar.setAttribute('stroke',fill);ar.setAttribute('stroke-width',3);g.appendChild(ar);svg.appendChild(g);text(svg,p[0]+8,p[1]-8,label,fill,12)}
function draw(st){let svg=document.getElementById('map');svg.innerHTML='';for(let x=-30;x<=30;x+=10){let p1=xy({x_cm:x,y_cm:-5}),p2=xy({x_cm:x,y_cm:65});line(svg,p1[0],p1[1],p2[0],p2[1],'#263345',1,.55)}for(let y=0;y<=60;y+=10){let p1=xy({x_cm:-35,y_cm:y}),p2=xy({x_cm:35,y_cm:y});line(svg,p1[0],p1[1],p2[0],p2[1],'#263345',1,.55)}
let a=xy({x_cm:-12.25,y_cm:0}),b=xy({x_cm:12.25,y_cm:48});let rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('x',a[0]);rect.setAttribute('y',b[1]);rect.setAttribute('width',b[0]-a[0]);rect.setAttribute('height',a[1]-b[1]);rect.setAttribute('fill','rgba(255,209,102,.08)');rect.setAttribute('stroke','#ffd166');rect.setAttribute('stroke-width',2);svg.appendChild(rect);line(svg,380,25,380,500,'#75849a',1,.75,'5 5');text(svg,20,28,'slot frame / ground cm','#9baabd',13);
(st.candidates||[]).forEach(c=>{let pts=(c.trajectory||[]).map(xy).filter(Boolean);if(pts.length<2)return;let pl=document.createElementNS('http://www.w3.org/2000/svg','polyline');pl.setAttribute('points',pts.map(p=>p.join(',')).join(' '));pl.setAttribute('fill','none');pl.setAttribute('stroke',color(c));pl.setAttribute('stroke-width',String(c.status==='selected'?5:3));pl.setAttribute('opacity',String(c.hard_block?.45:.8));svg.appendChild(pl)});
drawPose(svg,st.locked_initial_pose,'initial','#a78bfa');drawPose(svg,st.current_pose,'current','#32d583');let target={y_dist_cm:5,lateral_cm:0,heading_deg:0};drawPose(svg,target,'target','#ffd166')}
function rows(o){return Object.entries(o).map(([k,v])=>`<div class="card" style="margin-bottom:8px"><span class="muted">${esc(k)}</span><br><b>${esc(v??'N/A')}</b></div>`).join('')}
async function refresh(){let st=await(await fetch('/api/parking-log/state',{cache:'no-store'})).json();let p=st.current_pose||{},stm=st.stm32||{},ch=st.chosen_action||{};let status=st.status||'WAITING';let sc=status==='SUCCESS'?'ok':(status==='ERROR'||status==='VISION_LOST'?'bad':'warn');document.getElementById('cards').innerHTML=[
card('state',status,'state '+sc),card('y_dist_cm',fmt(p.y_dist_cm)),card('lateral_cm',fmt(p.lateral_cm)),card('heading_deg',fmt(p.heading_deg)),
card('step',st.step_index??'N/A'),card('total_reverse_cm',fmt(st.total_reverse_cm)),card('confidence',fmt(st.confidence,3)),card('chosen',ch.cmd||'N/A')
].join('');document.getElementById('safety').innerHTML=rows({line_risk:st.line_risk,effective_line_risk:st.effective_line_risk,IMU:stm.imu,DROP:stm.drop,odom_progress_cm:fmt(stm.odom_progress_cm),yaw_delta_deg:fmt(stm.yaw_delta_deg),stop_reason:st.stop_reason,success_reason:st.success_reason,radar:'N/A'});
document.getElementById('source').innerHTML=rows({log_path:st.log_path||'N/A',reason:st.reason||'N/A',updated_at:st.updated_at||'N/A',decode_errors:st.decode_errors??0,notice:'READ ONLY / no control commands available'});
let tb=document.querySelector('#cand tbody');tb.innerHTML='';(st.candidates||[]).forEach(c=>{let p=c.predicted_pose||{};let tr=document.createElement('tr');tr.innerHTML=`<td class="${cls(c)}">${esc(c.status||'candidate')}</td><td>${esc(c.cmd||'')}</td><td>${fmt(c.score,2)}</td><td>y=${fmt(p.y_dist_cm)}<br>lat=${fmt(p.lateral_cm)}<br>head=${fmt(p.heading_deg)}</td><td>${esc(c.block_reason||c.reason||'ok')}</td>`;tb.appendChild(tr)});draw(st)}
setInterval(refresh,500);refresh().catch(e=>{document.getElementById('source').textContent='API error: '+e});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ParkingWebMVP/0.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), fmt % args))

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            send_html(self, HTML)
        elif path in ("/viewer", "/dashboard/log"):
            send_html(self, VIEWER_HTML)
        elif path == "/api/status":
            send_json(self, self.app.status())
        elif path == "/api/output":
            send_json(self, {"running": self.app.running(), "lines": self.app.output.tail(200)})
        elif path == "/api/latest_log_summary":
            send_json(self, self.app.latest_summary())
        elif path == "/api/parking-log/state":
            send_json(self, self.app.parking_log_state())
        elif path == "/api/parking-log/events":
            send_json(self, self.app.parking_log_events())
        else:
            send_text(self, "not found", 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/start_parking":
            send_json(self, self.app.start())
        elif path == "/api/stop":
            send_json(self, self.app.stop())
        else:
            send_text(self, "not found", 404)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Local browser console for H1 parking")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--board-host", default=DEFAULT_BOARD_HOST)
    ap.add_argument("--board-user", default=DEFAULT_BOARD_USER)
    ap.add_argument("--board-password", default=DEFAULT_BOARD_PASSWORD)
    ap.add_argument(
        "--parking-log-jsonl",
        default=os.environ.get("PARKING_DASHBOARD_LOG_JSONL", ""),
        help="Optional local JSONL log path for the read-only viewer; can also use PARKING_DASHBOARD_LOG_JSONL.",
    )
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.host == "0.0.0.0":
        print("Refusing 0.0.0.0; use 127.0.0.1 for the local console.", file=sys.stderr)
        return 2
    app = App(args)

    def warn_running() -> None:
        if app.running():
            print("Parking process still running; use Emergency STOP first if needed.", file=sys.stderr)

    atexit.register(warn_running)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.app = app  # type: ignore[attr-defined]
    print(f"Parking web console: http://{args.host}:{args.port}", flush=True)
    print("Local-only by default. Start Parking uses a browser confirmation.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web console", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
