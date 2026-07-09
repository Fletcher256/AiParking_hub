#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for read-only demo-video material generation.

This module intentionally has no board/STM32 side effects.  It only reads JSONL
logs and local image files, then writes derived visualization assets.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SLOT_HALF_WIDTH_CM = 12.25
SLOT_Y_NEAR_CM = 0.0
SLOT_Y_FAR_CM = 48.0
TARGET_POSE = {"y_dist_cm": 5.0, "lateral_cm": 0.0, "heading_deg": 0.0}


def as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def get_path(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def parse_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    data = Path(path).read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    for line in text.splitlines():
        line = line.strip("\ufeff\r\n\t ")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def compact_pose(obj: Any) -> Optional[dict[str, Optional[float]]]:
    if not isinstance(obj, dict):
        return None
    y = first_present(obj.get("y_dist_cm"), obj.get("y_cm"), obj.get("slot_y_dist_cm"), obj.get("lon"))
    lateral = first_present(obj.get("lateral_cm"), obj.get("x_cm"), obj.get("slot_lateral_cm"), obj.get("lat"))
    heading = first_present(obj.get("heading_deg"), obj.get("yaw_deg"), obj.get("theta_deg"), obj.get("head"))
    if y is None and lateral is None and heading is None:
        return None
    return {"y_dist_cm": as_float(y), "lateral_cm": as_float(lateral), "heading_deg": as_float(heading)}


def find_pose(obj: Any) -> Optional[dict[str, Optional[float]]]:
    if not isinstance(obj, dict):
        return None
    direct = compact_pose(obj)
    if direct:
        return direct
    for key in (
        "estimated_pose_before",
        "estimated_pose",
        "current_pose",
        "estimated_pose_after_odom",
        "estimated_pose_after_correction",
        "estimated_pose_after",
        "pose",
        "predicted_pose",
        "visual_pose",
        "locked_initial_pose",
    ):
        pose = compact_pose(obj.get(key))
        if pose:
            return pose
    state = obj.get("state")
    if isinstance(state, dict):
        pose = compact_pose(state.get("pose"))
        if pose:
            return pose
    stop_review = obj.get("stop_review")
    if isinstance(stop_review, dict):
        pose = compact_pose(stop_review.get("pose"))
        if pose:
            return pose
    ground = get_path(obj, "slot_relative_state", "ground_estimate")
    if isinstance(ground, dict):
        return compact_pose({
            "y_dist_cm": ground.get("slot_y_dist_cm"),
            "lateral_cm": ground.get("slot_lateral_cm"),
            "heading_deg": ground.get("slot_axis_heading_deg"),
        })
    return None


def parse_cmd_bits(cmd: Any) -> dict[str, Optional[float]]:
    text = str(cmd or "")
    out: dict[str, Optional[float]] = {"ste": None, "signed_distance_cm": None, "distance_cm": None}
    m = re.search(r"\bSTE=([-+]?\d+(?:\.\d+)?)", text, re.I)
    if m:
        out["ste"] = as_float(m.group(1))
    m = re.search(r"\bD=([-+]?\d+(?:\.\d+)?)", text, re.I)
    if m:
        out["signed_distance_cm"] = as_float(m.group(1))
        if out["signed_distance_cm"] is not None:
            out["distance_cm"] = abs(out["signed_distance_cm"] or 0.0)
    return out


def score_value(raw: dict[str, Any]) -> Optional[float]:
    for key in ("score", "final_score", "cost", "plan_score", "total_cost"):
        v = as_float(raw.get(key))
        if v is not None:
            return v
    step_cost = raw.get("step_cost")
    if isinstance(step_cost, dict):
        for key in ("total", "score", "cost", "final_score"):
            v = as_float(step_cost.get(key))
            if v is not None:
                return v
    return None


def normalize_point(p: Any) -> Optional[dict[str, Optional[float]]]:
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


def normalize_polygon(points: Any) -> list[list[float]]:
    out: list[list[float]] = []
    if not isinstance(points, list):
        return out
    for item in points:
        if isinstance(item, dict):
            x = as_float(first_present(item.get("x"), item.get("u"), item.get("px"), item.get("x_px")))
            y = as_float(first_present(item.get("y"), item.get("v"), item.get("py"), item.get("y_px")))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x = as_float(item[0])
            y = as_float(item[1])
        else:
            continue
        if x is not None and y is not None:
            out.append([float(x), float(y)])
    return out


def find_first_key(obj: Any, keys: set[str], max_depth: int = 5) -> Any:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, [], {}):
                return obj[key]
        for value in obj.values():
            found = find_first_key(value, keys, max_depth - 1)
            if found not in (None, [], {}):
                return found
    elif isinstance(obj, list):
        for value in obj[:20]:
            found = find_first_key(value, keys, max_depth - 1)
            if found not in (None, [], {}):
                return found
    return None


def pose_to_point(pose: Optional[dict[str, Any]]) -> Optional[dict[str, Optional[float]]]:
    if not isinstance(pose, dict):
        return None
    x = as_float(pose.get("lateral_cm"))
    y = as_float(pose.get("y_dist_cm"))
    if x is None or y is None:
        return None
    return {"x_cm": x, "y_cm": y, "heading_deg": as_float(pose.get("heading_deg"))}


def candidate_cmd(raw: dict[str, Any]) -> str:
    action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
    return str(first_present(raw.get("cmd"), raw.get("command"), action.get("cmd"), action.get("command"), ""))


def normalize_candidate(raw: dict[str, Any], current_pose: Optional[dict[str, Any]] = None,
                        selected_cmd: Optional[str] = None, selected: bool = False) -> dict[str, Any]:
    action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
    cmd = candidate_cmd(raw)
    bits = parse_cmd_bits(cmd)
    ste = first_present(raw.get("ste"), raw.get("servo"), raw.get("candidate_ste"), action.get("ste"), action.get("servo"), bits["ste"])
    signed_distance = first_present(raw.get("signed_distance_cm"), action.get("signed_distance_cm"), bits["signed_distance_cm"])
    distance = first_present(raw.get("distance_cm"), raw.get("candidate_distance_cm"), action.get("distance_cm"), bits["distance_cm"], abs(signed_distance) if isinstance(signed_distance, (int, float)) else None)
    predicted_pose = compact_pose(raw.get("predicted_pose")) or compact_pose(raw.get("pose_after")) or compact_pose(raw.get("end_pose"))
    hard_block = bool(first_present(raw.get("hard_block"), raw.get("blocked"), raw.get("rejected"), False))
    status = str(raw.get("status") or ("selected" if selected or (selected_cmd and cmd == selected_cmd) else ("blocked" if hard_block else "candidate")))
    if selected or (selected_cmd and cmd == selected_cmd):
        status = "selected"
    traj: list[dict[str, Optional[float]]] = []
    raw_traj = first_present(raw.get("trajectory"), raw.get("path"), raw.get("samples"))
    if isinstance(raw_traj, list):
        traj = [pt for pt in (normalize_point(x) for x in raw_traj) if pt]
    if not traj:
        a = pose_to_point(current_pose)
        b = pose_to_point(predicted_pose)
        if a and b:
            traj = [a, b]
        elif a:
            d = as_float(signed_distance, as_float(distance, 4.0)) or 4.0
            traj = [a, {"x_cm": a["x_cm"], "y_cm": (a["y_cm"] or 0.0) - abs(d), "heading_deg": a.get("heading_deg")}]
    return {
        "cmd": cmd,
        "ste": as_float(ste),
        "distance_cm": as_float(distance),
        "signed_distance_cm": as_float(signed_distance),
        "score": score_value(raw),
        "status": status,
        "hard_block": hard_block,
        "block_reason": str(first_present(raw.get("block_reason"), raw.get("reject_reason"), raw.get("reason"), "ok")),
        "predicted_pose": predicted_pose,
        "trajectory": traj,
        "kinematics_source": str(first_present(raw.get("kinematics_source"), raw.get("source"), "")),
        "reason": str(first_present(raw.get("reason"), raw.get("score_reason"), "")),
    }


def extract_candidate_list(obj: dict[str, Any], current_pose: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    for path in (("new_plan", "planned_actions"), ("plan", "planned_actions"), ("planned_actions",), ("candidates",), ("candidate_scores",)):
        v = get_path(obj, *path)
        if isinstance(v, list):
            raw_items.extend(v)
    chosen = first_present(obj.get("chosen_action"), obj.get("selected_action"), get_path(obj, "new_plan", "chosen_action"), get_path(obj, "plan", "chosen_action"))
    selected_cmd = candidate_cmd(chosen) if isinstance(chosen, dict) else None
    if isinstance(chosen, dict):
        raw_items.insert(0, chosen)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        cand = normalize_candidate(raw, current_pose, selected_cmd=selected_cmd)
        sig = f"{cand.get('cmd')}|{cand.get('score')}|{cand.get('status')}|{cand.get('block_reason')}"
        if sig in seen:
            continue
        seen.add(sig)
        out.append(cand)
    return out


def extract_visual(obj: dict[str, Any]) -> dict[str, Any]:
    visual_review = obj.get("visual_review") if isinstance(obj.get("visual_review"), dict) else {}
    visual_state = obj.get("visual_state") if isinstance(obj.get("visual_state"), dict) else {}
    return {
        "visual_pose": compact_pose(obj.get("visual_pose")) or compact_pose(visual_review.get("visual_pose")),
        "confidence": first_present(obj.get("confidence"), visual_review.get("confidence"), visual_state.get("confidence")),
        "min_margin_px": first_present(obj.get("min_margin_px"), visual_review.get("min_margin_px"), visual_state.get("min_margin_px")),
        "line_risk": first_present(obj.get("line_risk"), visual_review.get("line_risk"), visual_state.get("line_risk")),
        "effective_line_risk": first_present(obj.get("effective_line_risk"), visual_review.get("effective_line_risk"), visual_state.get("effective_line_risk")),
    }


def extract_yolo_overlay(obj: dict[str, Any]) -> dict[str, Any]:
    """Extract camera-domain polygon/edge data for offline YOLO overlay rendering."""
    raw_poly = normalize_polygon(find_first_key(obj, {"mask_polygon", "yolo_mask_polygon"}, 4))
    slot_poly = normalize_polygon(find_first_key(obj, {"slot_polygon_px", "control_mask_polygon_px", "visualization_polygon"}, 5))
    clean_poly = normalize_polygon(find_first_key(obj, {"sanitized_mask_polygon_px", "cleaned_polygon_px"}, 5))
    edges = find_first_key(obj, {"slot_edges_px"}, 4)
    out: dict[str, Any] = {
        "image_size": [640, 640],
        "raw_mask_polygon_px": raw_poly,
        "slot_polygon_px": slot_poly,
        "cleaned_polygon_px": clean_poly,
        "slot_edges_px": edges if isinstance(edges, dict) else {},
    }
    return {k: v for k, v in out.items() if v not in (None, [], {}) or k == "image_size"}


def extract_stm32(obj: dict[str, Any]) -> dict[str, Any]:
    stm = obj.get("stm32_result") if isinstance(obj.get("stm32_result"), dict) else {}
    odom = obj.get("odom_delta") if isinstance(obj.get("odom_delta"), dict) else {}
    stat_after = first_present(obj.get("stat_after"), stm.get("stat_after"), stm.get("stat"))
    imu = first_present(stm.get("imu"), obj.get("imu"))
    drop = first_present(stm.get("drop"), obj.get("drop"))
    if isinstance(stat_after, str):
        m = re.search(r"\bIMU=([^\s]+)", stat_after)
        if m and imu is None:
            imu = m.group(1)
        m = re.search(r"\bDROP=([^\s]+)", stat_after)
        if m and drop is None:
            drop = m.group(1)
    return {
        "ack": first_present(stm.get("ack"), stm.get("ack_seen"), obj.get("ack")),
        "done": first_present(stm.get("done"), stm.get("done_seen"), obj.get("done")),
        "stat_raw": stat_after,
        "odom_progress_cm": first_present(obj.get("odom_progress_cm"), stm.get("odom_progress_cm"), odom.get("progress_cm")),
        "yaw_delta_deg": first_present(obj.get("yaw_delta_deg"), stm.get("yaw_delta_deg"), odom.get("yaw_delta_deg")),
        "imu": imu,
        "drop": drop,
        "motion_events": stm.get("motion_events") or obj.get("motion_events"),
    }


def build_steps_from_log(log_path: Path, pose_label: str = "pose_A") -> dict[str, Any]:
    events = list(parse_jsonl(log_path))
    event_counts: dict[str, int] = {}
    for obj in events:
        ev = str(obj.get("event") or "NOEVENT")
        event_counts[ev] = event_counts.get(ev, 0) + 1

    steps_by_index: dict[int, dict[str, Any]] = {}
    pending_plan: Optional[dict[str, Any]] = None
    locked_initial_pose = None
    stop_reason = None
    success_reason = None
    final_pose = None

    def get_step(idx: int) -> dict[str, Any]:
        if idx not in steps_by_index:
            steps_by_index[idx] = {
                "step_index": idx,
                "event_time": None,
                "time_unix": None,
                "current_pose": None,
                "pose_after": None,
                "locked_initial_pose": locked_initial_pose,
                "visual_pose": None,
                "confidence": None,
                "min_margin_px": None,
                "line_risk": None,
                "effective_line_risk": None,
                "chosen_action": None,
                "candidate_actions": [],
                "yolo_overlay": {},
                "stm32_result": {},
                "stop_reason": None,
                "success_reason": None,
            }
        return steps_by_index[idx]

    for obj in events:
        ev = str(obj.get("event") or "")
        if locked_initial_pose is None:
            locked_initial_pose = compact_pose(obj.get("locked_initial_pose")) or compact_pose(get_path(obj, "new_plan", "initial_locked_pose")) or compact_pose(get_path(obj, "plan", "initial_locked_pose"))
        if ev in ("diy_path_replan", "replanner_step", "candidate"):
            pending_plan = obj
            idx = int(first_present(obj.get("step_index"), obj.get("steps"), len(steps_by_index) + 1) or (len(steps_by_index) + 1))
            step = get_step(idx)
            step["event_time"] = obj.get("timestamp") or obj.get("time")
            step["time_unix"] = obj.get("time_unix")
            pose = find_pose(obj)
            if pose:
                step["current_pose"] = pose
            step["locked_initial_pose"] = locked_initial_pose
            step["candidate_actions"] = extract_candidate_list(obj, step.get("current_pose"))
            step.update({k: v for k, v in extract_visual(obj).items() if v is not None})
            overlay = extract_yolo_overlay(obj)
            if overlay:
                step["yolo_overlay"] = {**(step.get("yolo_overlay") or {}), **overlay}
        elif ev == "diy_path_step":
            idx = int(first_present(obj.get("step_index"), obj.get("steps"), len(steps_by_index) + 1) or (len(steps_by_index) + 1))
            step = get_step(idx)
            step["event_time"] = obj.get("timestamp") or obj.get("time")
            step["time_unix"] = obj.get("time_unix")
            before = compact_pose(obj.get("estimated_pose_before")) or find_pose(obj)
            after = compact_pose(obj.get("estimated_pose_after_correction")) or compact_pose(obj.get("estimated_pose_after_odom")) or compact_pose(obj.get("estimated_pose_after"))
            if before:
                step["current_pose"] = before
            if after:
                step["pose_after"] = after
                final_pose = after
            chosen = obj.get("chosen_action") if isinstance(obj.get("chosen_action"), dict) else {}
            step["chosen_action"] = normalize_candidate(chosen, before, selected=True) if chosen else None
            if not step.get("candidate_actions") and pending_plan:
                step["candidate_actions"] = extract_candidate_list(pending_plan, before)
            if step.get("chosen_action"):
                if not any(c.get("status") == "selected" for c in step.get("candidate_actions") or []):
                    step.setdefault("candidate_actions", []).insert(0, step["chosen_action"])
            step["locked_initial_pose"] = locked_initial_pose or compact_pose(obj.get("locked_initial_pose"))
            step.update({k: v for k, v in extract_visual(obj).items() if v is not None})
            overlay = extract_yolo_overlay(obj)
            if not overlay and pending_plan:
                overlay = extract_yolo_overlay(pending_plan)
            if overlay:
                step["yolo_overlay"] = {**(step.get("yolo_overlay") or {}), **overlay}
            step["stm32_result"] = extract_stm32(obj)
        elif ev == "diy_path_stop":
            stop_reason = first_present(obj.get("reason"), obj.get("stop_reason"), get_path(obj, "stop_review", "reason"))
            final_pose = compact_pose(get_path(obj, "state", "pose")) or compact_pose(get_path(obj, "stop_review", "pose")) or final_pose
        elif ev == "diy_path_success":
            success_reason = first_present(obj.get("reason"), obj.get("success_reason"), get_path(obj, "success_review", "reason"))
            final_pose = find_pose(obj) or final_pose

    steps = [steps_by_index[k] for k in sorted(steps_by_index)]
    for step in steps:
        if step.get("locked_initial_pose") is None:
            step["locked_initial_pose"] = locked_initial_pose
        if step.get("stop_reason") is None:
            step["stop_reason"] = stop_reason
        if step.get("success_reason") is None:
            step["success_reason"] = success_reason
    return {
        "schema": "demo_video_steps.v1",
        "pose_label": pose_label,
        "source_log": str(log_path),
        "event_counts": event_counts,
        "locked_initial_pose": locked_initial_pose,
        "final_pose": final_pose,
        "stop_reason": stop_reason,
        "success_reason": success_reason,
        "step_count": len(steps),
        "steps": steps,
    }


def load_steps(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def ensure_dir(path: Path) -> Path:
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc") if bold else Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0]), int(box[3] - box[1])


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont,
                 fill: str, max_width: int, line_gap: int = 5, max_lines: Optional[int] = None) -> int:
    x, y = xy
    lines: list[str] = []
    for para in str(text).splitlines() or [""]:
        current = ""
        for ch in para:
            test = current + ch
            if text_size(draw, test, font)[0] <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip("…") + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += text_size(draw, line, font)[1] + line_gap
    return y


def fmt_num(v: Any, digits: int = 2) -> str:
    f = as_float(v)
    return "N/A" if f is None else f"{f:.{digits}f}"


def list_images(directory: Optional[Path]) -> list[Path]:
    if not directory:
        return []
    d = Path(directory)
    if not d.exists():
        return []
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    return sorted([p for p in d.iterdir() if p.is_file() and p.suffix.lower() in exts])


def placeholder_image(size: tuple[int, int], title: str, subtitle: str = "") -> Image.Image:
    img = Image.new("RGB", size, "#111827")
    draw = ImageDraw.Draw(img)
    font_big = load_font(34, bold=True)
    font = load_font(22)
    draw.rectangle([0, 0, size[0]-1, size[1]-1], outline="#374151", width=3)
    w, h = text_size(draw, title, font_big)
    draw.text(((size[0]-w)//2, size[1]//2-h-20), title, font=font_big, fill="#d1d5db")
    if subtitle:
        w2, h2 = text_size(draw, subtitle, font)
        draw.text(((size[0]-w2)//2, size[1]//2+20), subtitle, font=font, fill="#9ca3af")
    return img


def fit_image(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#0b1220")
    canvas.paste(img, ((size[0] - img.width)//2, (size[1] - img.height)//2))
    return canvas


def candidate_color(candidate: dict[str, Any]) -> str:
    status = str(candidate.get("status") or "candidate").lower()
    cmd = str(candidate.get("cmd") or "").lower()
    reason = str(candidate.get("reason") or "").lower()
    if "selected" in status:
        return "#22c55e"
    if candidate.get("hard_block") or "block" in status or "reject" in status:
        return "#ef4444"
    if "shuffle" in cmd or "terminal" in reason:
        return "#facc15"
    return "#60a5fa"


# Intentional: no board/STM32 command helpers in this file.
