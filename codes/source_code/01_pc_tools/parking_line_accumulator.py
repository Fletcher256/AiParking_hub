from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any, Iterable

EDGE_TYPES = ("left_edge", "right_edge", "entrance_edge", "back_edge")

DEFAULT_LINE_ACCUMULATOR_CONFIG: dict[str, Any] = {
    "enabled": False,
    "use_for_planning": False,
    "motion_capture": False,
    "min_track_weight": 3.0,
    "max_track_age_sec": 8.0,
    "decay_per_sec": 0.85,
    "moving_weight_scale": 0.7,
    "merge_angle_deg": 8.0,
    "merge_distance_cm": 5.0,
    "merge_overlap_ratio": 0.35,
    "require_edges_for_fused": list(EDGE_TYPES),
    "require_recent_raw_detection_sec": 0.7,
}


def merged_line_accumulator_config(config: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_LINE_ACCUMULATOR_CONFIG)
    for key, value in (config or {}).items():
        if value is not None:
            out[key] = value
    return out


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point(p: Iterable[Any]) -> tuple[float, float]:
    a = list(p)
    return float(a[0]), float(a[1])


def _edge(edge: Iterable[Iterable[Any]]) -> tuple[tuple[float, float], tuple[float, float]]:
    e = list(edge)
    return _point(e[0]), _point(e[1])


def _edge_len(edge: tuple[tuple[float, float], tuple[float, float]]) -> float:
    return math.hypot(edge[1][0] - edge[0][0], edge[1][1] - edge[0][1])


def _unit_dir(edge: tuple[tuple[float, float], tuple[float, float]]) -> tuple[float, float]:
    dx = edge[1][0] - edge[0][0]
    dy = edge[1][1] - edge[0][1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 1.0, 0.0
    return dx / length, dy / length


def _theta_deg(edge: tuple[tuple[float, float], tuple[float, float]]) -> float:
    ux, uy = _unit_dir(edge)
    angle = math.degrees(math.atan2(uy, ux)) % 180.0
    return angle


def _angle_diff_180(a: float, b: float) -> float:
    d = abs((a - b + 90.0) % 180.0 - 90.0)
    return d


def _project_interval(edge: tuple[tuple[float, float], tuple[float, float]], unit: tuple[float, float]) -> tuple[float, float]:
    vals = [p[0] * unit[0] + p[1] * unit[1] for p in edge]
    return min(vals), max(vals)


def _overlap_ratio(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    unit = _unit_dir(a)
    a0, a1 = _project_interval(a, unit)
    b0, b1 = _project_interval(b, unit)
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    denom = max(1e-6, min(a1 - a0, b1 - b0))
    return max(0.0, min(1.0, overlap / denom))


def _line_distance_cm(
    base: tuple[tuple[float, float], tuple[float, float]],
    other: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    ux, uy = _unit_dir(base)
    nx, ny = -uy, ux
    bx, by = base[0]
    return sum(abs((p[0] - bx) * nx + (p[1] - by) * ny) for p in other) / 2.0


def _polygon_area(points: list[list[float]] | list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        area += float(p[0]) * float(q[1]) - float(q[0]) * float(p[1])
    return area * 0.5


def _invert_3x3(m: list[list[float]]) -> list[list[float]]:
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError("homography is singular")
    inv_det = 1.0 / det
    return [
        [(e * i - f * h) * inv_det, (c * h - b * i) * inv_det, (b * f - c * e) * inv_det],
        [(f * g - d * i) * inv_det, (a * i - c * g) * inv_det, (c * d - a * f) * inv_det],
        [(d * h - e * g) * inv_det, (b * g - a * h) * inv_det, (a * e - b * d) * inv_det],
    ]


def _apply_h(m: list[list[float]], x: float, y: float) -> tuple[float, float]:
    a = m[0][0] * x + m[0][1] * y + m[0][2]
    b = m[1][0] * x + m[1][1] * y + m[1][2]
    w = m[2][0] * x + m[2][1] * y + m[2][2]
    if abs(w) < 1e-12:
        return float("nan"), float("nan")
    return a / w, b / w


def _line_intersection(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float] | None:
    x1, y1 = a[0]
    x2, y2 = a[1]
    x3, y3 = b[0]
    x4, y4 = b[1]
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return px, py


def transform_point_vehicle_to_anchor(point: tuple[float, float], pose: dict[str, Any]) -> tuple[float, float]:
    """Transform a point from current vehicle frame to local parking anchor frame.

    Frame convention matches the controller homography output: +x is reverse/toward
    the slot and +y is left. yaw_deg is clockwise-positive.
    """
    x, y = point
    yaw = math.radians(_num(pose.get("yaw_deg"), 0.0))
    c = math.cos(yaw)
    s = math.sin(yaw)
    return (
        _num(pose.get("x_cm"), 0.0) + c * x + s * y,
        _num(pose.get("y_cm"), 0.0) - s * x + c * y,
    )


def transform_point_anchor_to_vehicle(point: tuple[float, float], pose: dict[str, Any]) -> tuple[float, float]:
    dx = point[0] - _num(pose.get("x_cm"), 0.0)
    dy = point[1] - _num(pose.get("y_cm"), 0.0)
    yaw = math.radians(_num(pose.get("yaw_deg"), 0.0))
    c = math.cos(yaw)
    s = math.sin(yaw)
    return c * dx - s * dy, s * dx + c * dy


def transform_edge_vehicle_to_anchor(edge: tuple[tuple[float, float], tuple[float, float]], pose: dict[str, Any]):
    return transform_point_vehicle_to_anchor(edge[0], pose), transform_point_vehicle_to_anchor(edge[1], pose)


def transform_edge_anchor_to_vehicle(edge: tuple[tuple[float, float], tuple[float, float]], pose: dict[str, Any]):
    return transform_point_anchor_to_vehicle(edge[0], pose), transform_point_anchor_to_vehicle(edge[1], pose)


@dataclass
class LineTrack:
    edge_type: str
    p1_anchor: tuple[float, float]
    p2_anchor: tuple[float, float]
    weight: float
    first_seen_t: float
    last_seen_t: float
    last_decay_t: float | None = None
    hits: int = 1
    source_conf_sum: float = 0.0
    moving_hits: int = 0

    @property
    def edge(self) -> tuple[tuple[float, float], tuple[float, float]]:
        return self.p1_anchor, self.p2_anchor

    @property
    def theta_deg(self) -> float:
        return _theta_deg(self.edge)

    @property
    def source_conf_mean(self) -> float:
        return self.source_conf_sum / max(1, self.hits)

    def decay(self, now: float, decay_per_sec: float) -> None:
        # Decay exactly once per elapsed interval while preserving last_seen_t as
        # observation age. diagnostics()/best_tracks() may call decay repeatedly.
        base_t = self.last_decay_t if self.last_decay_t is not None else self.last_seen_t
        dt = max(0.0, now - base_t)
        self.weight *= float(decay_per_sec) ** dt
        self.last_decay_t = now

    def is_match(self, edge: tuple[tuple[float, float], tuple[float, float]], cfg: dict[str, Any]) -> tuple[bool, dict[str, float]]:
        angle = _angle_diff_180(self.theta_deg, _theta_deg(edge))
        dist = _line_distance_cm(self.edge, edge)
        overlap = _overlap_ratio(self.edge, edge)
        ok = (
            angle <= float(cfg["merge_angle_deg"]) and
            dist <= float(cfg["merge_distance_cm"]) and
            overlap >= float(cfg["merge_overlap_ratio"])
        )
        return ok, {"angle_deg": round(angle, 3), "distance_cm": round(dist, 3), "overlap_ratio": round(overlap, 4)}

    def update(self, edge: tuple[tuple[float, float], tuple[float, float]], weight: float,
               confidence: float, now: float, moving: bool) -> None:
        old_edge = self.edge
        old_unit = _unit_dir(old_edge)
        new_unit = _unit_dir(edge)
        p1, p2 = edge
        if old_unit[0] * new_unit[0] + old_unit[1] * new_unit[1] < 0.0:
            p1, p2 = p2, p1
        total = max(1e-9, self.weight + weight)
        self.p1_anchor = (
            (self.p1_anchor[0] * self.weight + p1[0] * weight) / total,
            (self.p1_anchor[1] * self.weight + p1[1] * weight) / total,
        )
        self.p2_anchor = (
            (self.p2_anchor[0] * self.weight + p2[0] * weight) / total,
            (self.p2_anchor[1] * self.weight + p2[1] * weight) / total,
        )
        self.weight = total
        self.last_seen_t = now
        self.last_decay_t = now
        self.hits += 1
        self.source_conf_sum += confidence
        if moving:
            self.moving_hits += 1

    def summary(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        return {
            "edge_type": self.edge_type,
            "p1_anchor": [round(self.p1_anchor[0], 3), round(self.p1_anchor[1], 3)],
            "p2_anchor": [round(self.p2_anchor[0], 3), round(self.p2_anchor[1], 3)],
            "theta_deg": round(self.theta_deg, 3),
            "weight": round(self.weight, 4),
            "hits": self.hits,
            "moving_hits": self.moving_hits,
            "age_sec": round(max(0.0, now - self.last_seen_t), 3),
            "source_conf_mean": round(self.source_conf_mean, 4),
        }


@dataclass
class LineAccumulatorPoseTracker:
    reverse_odom_d_sign: float = 1.0
    yaw_to_cw_sign: float = 1.0
    x_cm: float = 0.0
    y_cm: float = 0.0
    yaw_deg: float = 0.0
    last_yaw_deg: float | None = None
    last_d_cm: float | None = None
    tlm_count: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def from_chassis_signs(cls, signs: Any | None) -> "LineAccumulatorPoseTracker":
        if signs is None:
            return cls()
        reverse = -1.0 if bool(getattr(signs, "odom_d_reverse_negative", False)) else 1.0
        yaw = 1.0 if bool(getattr(signs, "yaw_cw_positive", True)) else -1.0
        return cls(reverse_odom_d_sign=reverse, yaw_to_cw_sign=yaw)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "x_cm": self.x_cm,
                "y_cm": self.y_cm,
                "yaw_deg": self.yaw_deg,
                "tlm_count": self.tlm_count,
            }

    def reset(self) -> None:
        with self.lock:
            self.x_cm = 0.0
            self.y_cm = 0.0
            self.yaw_deg = 0.0
            self.last_yaw_deg = None
            self.last_d_cm = None
            self.tlm_count = 0

    def ingest_tlm(self, tlm: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            yaw = _num(tlm.get("yaw"), None)
            d = _num(tlm.get("d"), None)
            if yaw is None or d is None:
                return self.snapshot()
            if self.last_yaw_deg is None or self.last_d_cm is None:
                self.last_yaw_deg = yaw
                self.last_d_cm = d
                self.tlm_count += 1
                return self.snapshot()
            raw_d_delta = d - self.last_d_cm
            raw_yaw_delta = (yaw - self.last_yaw_deg + 180.0) % 360.0 - 180.0
            ds = self.reverse_odom_d_sign * raw_d_delta
            dpsi = self.yaw_to_cw_sign * raw_yaw_delta
            yaw_mid = math.radians(self.yaw_deg + dpsi * 0.5)
            self.x_cm += ds * math.cos(yaw_mid)
            self.y_cm += -ds * math.sin(yaw_mid)
            self.yaw_deg = (self.yaw_deg + dpsi + 180.0) % 360.0 - 180.0
            self.last_yaw_deg = yaw
            self.last_d_cm = d
            self.tlm_count += 1
            return self.snapshot() | {"ds_cm": round(ds, 3), "dpsi_deg": round(dpsi, 3)}


class MotionCompensatedSlotLineAccumulator:
    def __init__(self, config: dict[str, Any] | None = None,
                 pixel_to_ground_h: list[list[float]] | None = None) -> None:
        self.config = merged_line_accumulator_config(config)
        self.tracks: list[LineTrack] = []
        self.lock = threading.RLock()
        self.update_count = 0
        self.last_update_t: float | None = None
        self.ground_to_pixel_h = _invert_3x3(pixel_to_ground_h) if pixel_to_ground_h is not None else None

    def reset(self) -> None:
        with self.lock:
            self.tracks.clear()
            self.update_count = 0
            self.last_update_t = None

    def decay(self, now: float | None = None, extra_scale: float = 1.0) -> dict[str, Any]:
        now = time.time() if now is None else now
        removed = 0
        with self.lock:
            for tr in self.tracks:
                tr.decay(now, float(self.config["decay_per_sec"]))
                tr.weight *= float(extra_scale)
            keep = []
            for tr in self.tracks:
                if now - tr.last_seen_t <= float(self.config["max_track_age_sec"]) and tr.weight >= 0.05:
                    keep.append(tr)
                else:
                    removed += 1
            self.tracks = keep
        return {"removed_tracks": removed, "track_count": len(self.tracks), "extra_scale": round(extra_scale, 4)}

    def update_from_slot_info(self, slot_info: dict[str, Any], pose: dict[str, Any] | None = None,
                              timestamp: float | None = None, moving: bool = False) -> dict[str, Any]:
        now = time.time() if timestamp is None else float(timestamp)
        pose = pose or {}
        with self.lock:
            self.decay(now)
            conf = max(0.0, min(1.0, _num(slot_info.get("confidence"), 0.0)))
            comp = slot_info.get("slot_completeness") or {}
            comp_score = max(0.0, min(1.0, _num(comp.get("score"), 1.0)))
            moving_scale = float(self.config["moving_weight_scale"]) if moving else 1.0
            updated = []
            for edge_type in EDGE_TYPES:
                raw_edge = slot_info.get(edge_type + "_cm")
                if not raw_edge:
                    continue
                current_edge = _edge(raw_edge)
                length_cm = _edge_len(current_edge)
                if length_cm < 1e-6:
                    continue
                length_score = max(0.05, min(1.0, length_cm / 20.0))
                weight = conf * comp_score * length_score * moving_scale
                if weight <= 0.0:
                    continue
                anchor_edge = transform_edge_vehicle_to_anchor(current_edge, pose)
                track, metrics = self._add_or_merge(edge_type, anchor_edge, weight, conf, now, moving)
                updated.append({
                    "edge_type": edge_type,
                    "weight_added": round(weight, 4),
                    "length_cm": round(length_cm, 3),
                    "track_weight": round(track.weight, 4),
                    "track_hits": track.hits,
                    "merge": metrics,
                })
            self.update_count += 1
            self.last_update_t = now
            return {
                "schema": "slot_line_accumulator_update.v1",
                "updated_edges": updated,
                "track_count": len(self.tracks),
                "update_count": self.update_count,
                "pose": {k: round(_num(v), 4) for k, v in pose.items() if k in ("x_cm", "y_cm", "yaw_deg")},
                "moving": bool(moving),
                "confidence": round(conf, 4),
                "completeness_score": round(comp_score, 4),
            }

    def _add_or_merge(self, edge_type: str, edge, weight: float, conf: float, now: float, moving: bool):
        best: tuple[LineTrack, dict[str, float]] | None = None
        best_dist = 999999.0
        for tr in self.tracks:
            if tr.edge_type != edge_type:
                continue
            ok, metrics = tr.is_match(edge, self.config)
            if ok and metrics["distance_cm"] < best_dist:
                best = (tr, metrics)
                best_dist = metrics["distance_cm"]
        if best is None:
            tr = LineTrack(
                edge_type=edge_type,
                p1_anchor=edge[0],
                p2_anchor=edge[1],
                weight=weight,
                first_seen_t=now,
                last_seen_t=now,
                last_decay_t=now,
                hits=1,
                source_conf_sum=conf,
                moving_hits=1 if moving else 0,
            )
            self.tracks.append(tr)
            return tr, {"created": True}
        tr, metrics = best
        tr.update(edge, weight, conf, now, moving)
        metrics["created"] = False
        return tr, metrics

    def best_tracks(self, now: float | None = None) -> dict[str, LineTrack]:
        now = time.time() if now is None else now
        with self.lock:
            self.decay(now)
            out: dict[str, LineTrack] = {}
            for edge_type in EDGE_TYPES:
                candidates = [
                    tr for tr in self.tracks
                    if tr.edge_type == edge_type and tr.weight >= float(self.config["min_track_weight"])
                ]
                if candidates:
                    out[edge_type] = max(candidates, key=lambda tr: tr.weight)
            return out

    def fused_detection_current(self, pose: dict[str, Any] | None = None,
                                timestamp: float | None = None) -> dict[str, Any]:
        now = time.time() if timestamp is None else float(timestamp)
        pose = pose or {}
        required = list(self.config.get("require_edges_for_fused") or EDGE_TYPES)
        with self.lock:
            tracks = self.best_tracks(now)
            missing = [edge for edge in required if edge not in tracks]
            if missing:
                return {
                    "status": "missing_required_edges",
                    "missing_edges": missing,
                    "track_count": len(self.tracks),
                    "tracks": [tr.summary(now) for tr in self.tracks],
                }
            current_edges = {
                edge_type: transform_edge_anchor_to_vehicle(tr.edge, pose)
                for edge_type, tr in tracks.items()
            }
            corners_cm = self._corners_from_edges(current_edges)
            if corners_cm is None:
                return {"status": "line_intersection_failed", "tracks": [tr.summary(now) for tr in self.tracks]}
            if abs(_polygon_area(corners_cm)) < 5.0:
                return {"status": "degenerate_cm_polygon", "corners_cm": corners_cm}
            if self.ground_to_pixel_h is None:
                return {"status": "missing_ground_to_pixel_h", "corners_cm": corners_cm}
            polygon_px = []
            for x_cm, y_cm in corners_cm:
                px, py = _apply_h(self.ground_to_pixel_h, x_cm, y_cm)
                if not math.isfinite(px) or not math.isfinite(py):
                    return {"status": "ground_to_pixel_nan", "corners_cm": corners_cm}
                polygon_px.append([px, py])
            area_px = abs(_polygon_area(polygon_px))
            if area_px < 10.0:
                return {"status": "degenerate_px_polygon", "polygon_px": polygon_px, "corners_cm": corners_cm}
            total_weight = sum(tracks[e].weight for e in required)
            conf = sum(tracks[e].source_conf_mean * tracks[e].weight for e in required) / max(1e-6, total_weight)
            diagnostics = {
                "schema": "slot_line_accumulator_fused.v1",
                "status": "ok",
                "pose": {k: round(_num(v), 4) for k, v in pose.items() if k in ("x_cm", "y_cm", "yaw_deg")},
                "required_edges": required,
                "total_weight": round(total_weight, 4),
                "tracks": [tracks[e].summary(now) for e in required],
                "corners_cm": [[round(x, 3), round(y, 3)] for x, y in corners_cm],
                "polygon_px": [[round(x, 2), round(y, 2)] for x, y in polygon_px],
                "mask_area_px": round(area_px, 2),
            }
            return {
                "status": "ok",
                "detection": {
                    "id": "line_accumulator",
                    "class_id": 0,
                    "class_name": "Parking",
                    "confidence": round(max(0.0, min(0.99, conf)), 4),
                    "mask_polygon": polygon_px,
                    "polygon_source": "line_accumulator",
                    "mask_area_px": area_px,
                    "slot_status": "line_accumulated",
                },
                "diagnostics": diagnostics,
            }

    @staticmethod
    def _corners_from_edges(edges: dict[str, tuple[tuple[float, float], tuple[float, float]]]) -> list[list[float]] | None:
        left = edges.get("left_edge")
        right = edges.get("right_edge")
        entrance = edges.get("entrance_edge")
        back = edges.get("back_edge")
        if not (left and right and entrance and back):
            return None
        pts = [
            _line_intersection(left, entrance),
            _line_intersection(right, entrance),
            _line_intersection(right, back),
            _line_intersection(left, back),
        ]
        if any(p is None for p in pts):
            return None
        return [[float(p[0]), float(p[1])] for p in pts if p is not None]

    def diagnostics(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self.lock:
            return {
                "schema": "slot_line_accumulator_state.v1",
                "track_count": len(self.tracks),
                "update_count": self.update_count,
                "last_update_age_sec": None if self.last_update_t is None else round(max(0.0, now - self.last_update_t), 3),
                "tracks": [tr.summary(now) for tr in self.tracks],
            }
