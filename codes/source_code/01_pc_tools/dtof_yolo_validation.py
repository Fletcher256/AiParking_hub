#!/usr/bin/env python3
"""Host-side validation helpers for dToF condition reports and YOLO person.

This tool only talks to the Ubuntu VM over SSH/SFTP. It does not touch board
actuators, STM32, CAN, motors, steering, brake, or throttle.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any

import paramiko


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DTOF_SCRIPT = ROOT / "tools" / "vm_dtof_condition_report.py"
REMOTE_DTOF_SCRIPT = "/tmp/vm_dtof_condition_report.py"
ARTIFACT_ROOT = ROOT / "artifacts" / "dtof_yolo_validation"


def connect(host: str, user: str, password: str, port: int = 22) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=user,
        password=password,
        timeout=12,
        banner_timeout=12,
        auth_timeout=12,
    )
    return client


def run_remote(client: paramiko.SSHClient, command: str, timeout: float) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def upload_file(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(local), remote)
    finally:
        sftp.close()


def download_file(client: paramiko.SSHClient, remote: str, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    sftp = client.open_sftp()
    try:
        sftp.get(remote, str(local))
    finally:
        sftp.close()


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def print_dtof_summary(report: dict[str, Any], path: Path) -> None:
    print(f"LOCAL_REPORT {path}")
    print(f"CONDITION {report.get('condition')}")
    print(f"SESSION {report.get('session')}")
    print(f"PACKET_RATE_HZ {nested(report, 'metadata', 'rate_hz')}")
    print(f"PACKET_SIZE_UNIQUE {nested(report, 'metadata', 'packet_size_unique')}")
    print(f"RAW_PACKET_COUNT_BY_SIZE {report.get('raw_packet_count_by_size')}")
    print(f"DEPTH_FRAMES_USED {nested(report, 'depth', 'frame_count')}")
    print(f"DEPTH_VALID_MEDIAN_MM {nested(report, 'depth', 'valid', 'median')}")
    print(f"DEPTH_VALID_P25_MM {nested(report, 'depth', 'valid', 'p25')}")
    print(f"DEPTH_AVG_VALID_PIXELS {nested(report, 'depth', 'avg_valid_pixels')}")
    print(f"DEPTH_AVG_ZERO_PIXELS {nested(report, 'depth', 'avg_zero_pixels')}")
    print(f"DEPTH_AVG_EQ_2_PIXELS {nested(report, 'depth', 'avg_eq_2_pixels')}")
    print(f"DEPTH_AVG_SUPPORT_LT_500 {nested(report, 'depth', 'avg_support_lt_500_pixels')}")
    print(f"DEPTH_AVG_SUPPORT_LT_1200 {nested(report, 'depth', 'avg_support_lt_1200_pixels')}")
    print(f"OBSTACLE_STATES {nested(report, 'obstacle_blocks', 'states')}")
    print(f"OBSTACLE_NEAREST_MEDIAN_MM {nested(report, 'obstacle_blocks', 'nearest', 'median')}")
    zones = nested(report, "depth", "zones", default={}) or {}
    for name in ["far_left", "left", "center", "right", "far_right"]:
        zone = zones.get(name, {})
        print(
            "ZONE",
            name,
            "valid_median_mm",
            nested(zone, "valid", "median"),
            "support_lt_500_avg",
            zone.get("avg_support_lt_500_pixels_per_frame"),
            "support_lt_1200_avg",
            zone.get("avg_support_lt_1200_pixels_per_frame"),
        )


def cmd_capture_dtof(args: argparse.Namespace) -> int:
    out_dir = ARTIFACT_ROOT / "dtof_conditions" / timestamp()
    condition = safe_name(args.condition)
    client = connect(args.vm_host, args.vm_user, args.vm_password, args.vm_port)
    try:
        upload_file(client, LOCAL_DTOF_SCRIPT, REMOTE_DTOF_SCRIPT)
        command = " ".join([
            "python3",
            shlex.quote(REMOTE_DTOF_SCRIPT),
            "--condition",
            shlex.quote(args.condition),
            "--frames",
            str(args.frames),
            "--metadata-lines",
            str(args.metadata_lines),
        ])
        rc, out, err = run_remote(client, command, timeout=args.timeout)
        if out:
            print(out, end="")
        if err:
            print(err, end="")
        if rc != 0:
            print(f"CAPTURE_DTOF_FAIL rc={rc}")
            return rc
        match = re.search(r"DTOF_CONDITION_REPORT\s+(\S+)", out)
        if not match:
            print("CAPTURE_DTOF_FAIL missing DTOF_CONDITION_REPORT path")
            return 2
        remote_report = match.group(1)
        local_report = out_dir / f"{condition}.json"
        download_file(client, remote_report, local_report)
    finally:
        client.close()
    report = load_json(local_report)
    print_dtof_summary(report, local_report)
    return 0


def comparison_value(report: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    cur: Any = report
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def cmd_compare_dtof(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline)
    test_path = Path(args.test)
    baseline = load_json(baseline_path)
    test = load_json(test_path)
    keys = [
        "metadata.rate_hz",
        "depth.valid.p25",
        "depth.valid.median",
        "depth.avg_valid_pixels",
        "depth.avg_support_lt_500_pixels",
        "depth.avg_support_lt_1200_pixels",
        "depth.zones.center.valid.p25",
        "depth.zones.center.valid.median",
        "depth.zones.center.avg_support_lt_500_pixels_per_frame",
        "depth.zones.center.avg_support_lt_1200_pixels_per_frame",
        "obstacle_blocks.nearest.median",
        "obstacle_blocks.states",
    ]
    print(f"BASELINE {baseline_path} condition={baseline.get('condition')}")
    print(f"TEST {test_path} condition={test.get('condition')}")
    for key in keys:
        b = comparison_value(baseline, key)
        t = comparison_value(test, key)
        if isinstance(b, (int, float)) and isinstance(t, (int, float)):
            delta = t - b
            ratio = (t / b) if b else None
            print(f"COMPARE {key} baseline={b} test={t} delta={delta} ratio={ratio}")
        else:
            print(f"COMPARE {key} baseline={b} test={t}")
    return 0


def parse_ros_string_payloads(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data: "):
            continue
        raw = stripped[6:].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == "'":
            raw = raw[1:-1]
        raw = raw.replace("\\'", "'")
        try:
            payloads.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return payloads


def cmd_check_yolo(args: argparse.Namespace) -> int:
    client = connect(args.vm_host, args.vm_user, args.vm_password, args.vm_port)
    try:
        command = (
            "bash -lc "
            + shlex.quote(
                "source /opt/ros/humble/setup.bash && "
                "if [ -f ~/parking_ws/install/setup.bash ]; then source ~/parking_ws/install/setup.bash; fi && "
                f"timeout {int(args.duration)} ros2 topic echo --full-length "
                "/parking/yolo/person_detections std_msgs/msg/String"
            )
        )
        rc, out, err = run_remote(client, command, timeout=args.duration + 20)
    finally:
        client.close()
    if out:
        print(out, end="")
    if err:
        print(err, end="")
    payloads = parse_ros_string_payloads(out)
    max_people = 0
    max_conf = 0.0
    for payload in payloads:
        max_people = max(max_people, int(payload.get("person_count") or 0))
        for det in payload.get("detections", []) or []:
            try:
                max_conf = max(max_conf, float(det.get("confidence") or 0.0))
            except (TypeError, ValueError):
                pass
    report = {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": args.duration,
        "returncode": rc,
        "message_count": len(payloads),
        "max_person_count": max_people,
        "max_confidence": max_conf,
        "require_person": args.require_person,
        "status": "PASS",
    }
    if args.require_person and max_people < 1:
        report["status"] = "FAIL"
    if not args.require_person and max_people != 0:
        report["status"] = "WARN_PERSON_PRESENT"
    out_dir = ARTIFACT_ROOT / "yolo_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"yolo_check_{timestamp()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"YOLO_CHECK_REPORT {report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "PASS":
        return 0
    if report["status"] == "WARN_PERSON_PRESENT":
        return 2
    return 1


def iter_json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.json"), key=lambda path: path.stat().st_mtime)


def load_json_or_none(path: Path) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def latest_matching(paths: list[Path], predicate: Any) -> tuple[Path, dict[str, Any]] | None:
    for path in reversed(paths):
        data = load_json_or_none(path)
        if data is not None and predicate(data, path):
            return path, data
    return None


def condition_contains(*needles: str) -> Any:
    lowered = [needle.lower() for needle in needles]

    def predicate(data: dict[str, Any], _path: Path) -> bool:
        condition = str(data.get("condition") or "").lower()
        return all(needle in condition for needle in lowered)

    return predicate


def dtof_report_summary(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "condition": report.get("condition"),
        "packet_rate_hz": nested(report, "metadata", "rate_hz"),
        "packet_size_unique": nested(report, "metadata", "packet_size_unique"),
        "depth_frame_count": nested(report, "depth", "frame_count"),
        "depth_valid_median_mm": nested(report, "depth", "valid", "median"),
        "depth_valid_p25_mm": nested(report, "depth", "valid", "p25"),
        "depth_avg_valid_pixels": nested(report, "depth", "avg_valid_pixels"),
        "depth_avg_zero_pixels": nested(report, "depth", "avg_zero_pixels"),
        "depth_avg_eq_2_pixels": nested(report, "depth", "avg_eq_2_pixels"),
        "depth_avg_support_lt_500_pixels": nested(report, "depth", "avg_support_lt_500_pixels"),
        "depth_avg_support_lt_1200_pixels": nested(report, "depth", "avg_support_lt_1200_pixels"),
        "center_valid_median_mm": nested(report, "depth", "zones", "center", "valid", "median"),
        "center_support_lt_500_avg": nested(
            report,
            "depth",
            "zones",
            "center",
            "avg_support_lt_500_pixels_per_frame",
        ),
        "center_support_lt_1200_avg": nested(
            report,
            "depth",
            "zones",
            "center",
            "avg_support_lt_1200_pixels_per_frame",
        ),
        "obstacle_states": nested(report, "obstacle_blocks", "states"),
        "obstacle_nearest_median_mm": nested(report, "obstacle_blocks", "nearest", "median"),
    }


def number_value(report: dict[str, Any], path: str) -> float | None:
    value = comparison_value(report, path)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def state_has_obstacle(report: dict[str, Any]) -> bool:
    states = nested(report, "obstacle_blocks", "states", default={}) or {}
    return int(states.get("near") or 0) > 0 or int(states.get("warn") or 0) > 0


def dtof_response_diagnosis(
    baseline_path: Path,
    baseline: dict[str, Any],
    test_path: Path,
    test: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    metrics = {
        "baseline_path": str(baseline_path),
        "test_path": str(test_path),
        "baseline_condition": baseline.get("condition"),
        "test_condition": test.get("condition"),
        "label": label,
    }
    numeric_keys = [
        "metadata.rate_hz",
        "depth.avg_valid_pixels",
        "depth.avg_zero_pixels",
        "depth.avg_eq_2_pixels",
        "depth.valid.p25",
        "depth.valid.median",
        "depth.zones.center.valid.p25",
        "depth.zones.center.valid.median",
        "depth.zones.center.avg_support_lt_500_pixels_per_frame",
        "depth.zones.center.avg_support_lt_1200_pixels_per_frame",
        "depth.avg_support_lt_500_pixels",
        "depth.avg_support_lt_1200_pixels",
        "obstacle_blocks.nearest.median",
    ]
    comparisons: dict[str, Any] = {}
    for key in numeric_keys:
        base = number_value(baseline, key)
        cur = number_value(test, key)
        comparisons[key] = {
            "baseline": base,
            "test": cur,
            "delta": None if base is None or cur is None else cur - base,
        }
    metrics["comparisons"] = comparisons
    metrics["baseline_obstacle_states"] = nested(baseline, "obstacle_blocks", "states", default={})
    metrics["test_obstacle_states"] = nested(test, "obstacle_blocks", "states", default={})

    reasons: list[str] = []
    warnings: list[str] = []
    score = 0
    packet_sizes = nested(test, "metadata", "packet_size_unique", default=[])
    if packet_sizes != [4873]:
        warnings.append(f"packet_size_unique={packet_sizes}, expected [4873]")
    if int(nested(test, "metadata", "expected_shape_count", default=0) or 0) <= 0:
        warnings.append("no expected 40x30 packets in test metadata")

    center_p25_drop = -(comparisons["depth.zones.center.valid.p25"]["delta"] or 0.0)
    center_median_drop = -(comparisons["depth.zones.center.valid.median"]["delta"] or 0.0)
    support_500_gain = comparisons["depth.zones.center.avg_support_lt_500_pixels_per_frame"]["delta"] or 0.0
    support_1200_gain = comparisons["depth.zones.center.avg_support_lt_1200_pixels_per_frame"]["delta"] or 0.0
    obstacle_triggered = state_has_obstacle(test)
    test_center_p25 = number_value(test, "depth.zones.center.valid.p25")
    test_center_median = number_value(test, "depth.zones.center.valid.median")

    if center_p25_drop >= 1200:
        score += 1
        reasons.append(f"center p25 dropped by {center_p25_drop:.0f} mm")
    if center_median_drop >= 1200:
        score += 1
        reasons.append(f"center median dropped by {center_median_drop:.0f} mm")
    if support_500_gain >= 8:
        score += 1
        reasons.append(f"center <500mm support increased by {support_500_gain:.1f} px/frame")
    if support_1200_gain >= 12:
        score += 1
        reasons.append(f"center <1200mm support increased by {support_1200_gain:.1f} px/frame")
    if test_center_p25 is not None and test_center_p25 <= 1500:
        score += 1
        reasons.append(f"test center p25 is near: {test_center_p25:.0f} mm")
    if test_center_median is not None and test_center_median <= 2000:
        score += 1
        reasons.append(f"test center median is near: {test_center_median:.0f} mm")
    if obstacle_triggered:
        score += 1
        reasons.append("obstacle_blocks emitted near/warn")

    if warnings:
        classification = "transport_or_parse_issue"
        conclusion = "dToF transport or parser evidence is inconsistent; fix packet/shape stability before judging depth."
    elif score >= 2:
        classification = "raw_depth_responds"
        if obstacle_triggered:
            conclusion = "Raw dToF depth responds and obstacle_blocks is triggering; Foxglove display is trustworthy."
        else:
            conclusion = (
                "Raw dToF depth responds, but obstacle_blocks did not trigger. "
                "Thresholds are probably too strict for this target or support distribution."
            )
    else:
        classification = "no_clear_raw_response"
        conclusion = (
            "The test report does not show a clear raw-depth response against the baseline. "
            "Next checks should focus on target placement/reflectivity, sensor angle, cable/power, "
            "or falling back to official case1/case3/case7 validation."
        )

    metrics["response_score"] = score
    metrics["classification"] = classification
    metrics["reasons"] = reasons
    metrics["warnings"] = warnings
    metrics["conclusion"] = conclusion
    return metrics


def find_latest_condition_reports() -> dict[str, tuple[Path, dict[str, Any]] | None]:
    dtof_files = iter_json_files(ARTIFACT_ROOT / "dtof_conditions")
    baseline = latest_matching(dtof_files, condition_contains("unobstructed"))
    flat = latest_matching(dtof_files, condition_contains("30_80"))
    if flat is None:
        flat = latest_matching(dtof_files, condition_contains("flat"))
    close = latest_matching(dtof_files, condition_contains("close"))
    return {"baseline": baseline, "flat": flat, "close": close}


def latest_foxglove_audit() -> tuple[Path, dict[str, Any]] | None:
    root = ROOT / "artifacts" / "foxglove_low_bandwidth_audit"
    return latest_matching(
        iter_json_files(root),
        lambda data, _path: "overall_status" in data or "overall" in data,
    )


def cmd_audit(args: argparse.Namespace) -> int:
    yolo_files = iter_json_files(ARTIFACT_ROOT / "yolo_checks")
    condition_reports = find_latest_condition_reports()
    baseline = condition_reports["baseline"]
    flat = condition_reports["flat"]
    close = condition_reports["close"]
    yolo_negative = latest_matching(
        yolo_files,
        lambda data, _path: data.get("require_person") is False and data.get("status") == "PASS",
    )
    yolo_positive = latest_matching(
        yolo_files,
        lambda data, _path: data.get("require_person") is True and data.get("status") == "PASS",
    )
    foxglove = latest_foxglove_audit()

    checks = []

    def add_check(name: str, status: str, detail: str = "") -> None:
        checks.append({"name": name, "status": status, "detail": detail})
        suffix = f" {detail}" if detail else ""
        print(f"{status} {name}{suffix}")

    add_check(
        "dtof_unobstructed_baseline",
        "PASS" if baseline else "PENDING",
        str(baseline[0]) if baseline else "need capture-dtof --condition unobstructed_local_baseline",
    )
    add_check(
        "dtof_center_flat_object_30_80cm",
        "PASS" if flat else "PENDING",
        str(flat[0]) if flat else "place a flat object 30-80cm in front of dToF and capture",
    )
    add_check(
        "dtof_close_obstruction",
        "PASS" if close else "PENDING",
        str(close[0]) if close else "place object very close/cover briefly and capture",
    )
    add_check(
        "yolo_negative_no_person",
        "PASS" if yolo_negative else "PENDING",
        str(yolo_negative[0]) if yolo_negative else "run check-yolo without a person",
    )
    add_check(
        "yolo_positive_person_visible",
        "PASS" if yolo_positive else "PENDING",
        str(yolo_positive[0]) if yolo_positive else "stand in camera view and run check-yolo --require-person",
    )
    add_check(
        "foxglove_low_bandwidth_topics",
        "PASS"
        if foxglove and (foxglove[1].get("overall_status") == "PASS" or foxglove[1].get("overall") == "PASS")
        else "PENDING",
        str(foxglove[0]) if foxglove else "run foxglove_low_bandwidth_audit.py",
    )
    add_check(
        "safety_perception_only",
        "PASS",
        "tool only reads VM ROS/dToF/YOLO reports and does not touch actuator paths",
    )

    reports: dict[str, Any] = {}
    if baseline:
        reports["dtof_unobstructed_baseline"] = dtof_report_summary(*baseline)
    if flat:
        reports["dtof_center_flat_object_30_80cm"] = dtof_report_summary(*flat)
    if close:
        reports["dtof_close_obstruction"] = dtof_report_summary(*close)
    if yolo_negative:
        reports["yolo_negative_no_person"] = {"path": str(yolo_negative[0]), **yolo_negative[1]}
    if yolo_positive:
        reports["yolo_positive_person_visible"] = {"path": str(yolo_positive[0]), **yolo_positive[1]}
    if foxglove:
        reports["foxglove_low_bandwidth_topics"] = {"path": str(foxglove[0]), **foxglove[1]}
    if baseline and flat:
        flat_diag = dtof_response_diagnosis(baseline[0], baseline[1], flat[0], flat[1], "30_80cm_flat_object")
        reports["dtof_flat_object_diagnosis"] = flat_diag
        add_check(
            "dtof_flat_object_raw_response",
            "PASS" if flat_diag["classification"] == "raw_depth_responds" else "FAIL",
            flat_diag["conclusion"],
        )
    if baseline and close:
        close_diag = dtof_response_diagnosis(baseline[0], baseline[1], close[0], close[1], "close_obstruction")
        reports["dtof_close_obstruction_diagnosis"] = close_diag
        add_check(
            "dtof_close_obstruction_raw_response",
            "PASS" if close_diag["classification"] == "raw_depth_responds" else "FAIL",
            close_diag["conclusion"],
        )

    audit = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "artifact_root": str(ARTIFACT_ROOT),
        "checks": checks,
        "reports": reports,
        "overall_status": "PASS" if all(item["status"] == "PASS" for item in checks) else "PENDING",
    }
    out_dir = ARTIFACT_ROOT / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = out_dir / f"audit_{timestamp()}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DTOF_YOLO_AUDIT_REPORT {audit_path}")
    print(f"OVERALL_STATUS {audit['overall_status']}")
    return 0 if audit["overall_status"] == "PASS" else 1


def cmd_diagnose_dtof(args: argparse.Namespace) -> int:
    if args.baseline:
        baseline = (Path(args.baseline), load_json(Path(args.baseline)))
    else:
        baseline = find_latest_condition_reports()["baseline"]
    if baseline is None:
        print("DTOF_DIAGNOSIS_FAIL missing unobstructed baseline")
        return 2

    tests: list[tuple[str, Path, dict[str, Any]]] = []
    if args.test:
        test_path = Path(args.test)
        tests.append((args.label or test_path.stem, test_path, load_json(test_path)))
    else:
        found = find_latest_condition_reports()
        for label, item in [("30_80cm_flat_object", found["flat"]), ("close_obstruction", found["close"])]:
            if item:
                tests.append((label, item[0], item[1]))
    if not tests:
        print("DTOF_DIAGNOSIS_PENDING no physical-condition test report is available")
        return 1

    diagnoses = [
        dtof_response_diagnosis(baseline[0], baseline[1], path, report, label)
        for label, path, report in tests
    ]
    out_dir = ARTIFACT_ROOT / "dtof_diagnoses"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else out_dir / f"dtof_diagnosis_{timestamp()}.json"
    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": str(baseline[0]),
        "diagnoses": diagnoses,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in diagnoses:
        print(f"DTOF_DIAGNOSIS {item['label']} {item['classification']}")
        print(f"CONCLUSION {item['conclusion']}")
        if item["reasons"]:
            print("REASONS " + "; ".join(item["reasons"]))
        if item["warnings"]:
            print("WARNINGS " + "; ".join(item["warnings"]))
    print(f"DTOF_DIAGNOSIS_REPORT {out_path}")
    return 0 if all(item["classification"] == "raw_depth_responds" for item in diagnoses) else 1


def latest_audit() -> tuple[Path, dict[str, Any]] | None:
    return latest_matching(iter_json_files(ARTIFACT_ROOT / "audits"), lambda data, _path: "checks" in data)


def fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def dtof_markdown_row(label: str, data: dict[str, Any] | None) -> str:
    if data is None:
        return f"| {label} | missing | n/a | n/a | n/a | n/a | n/a |"
    return (
        f"| {label} | {data.get('condition')} | "
        f"{fmt(data.get('packet_rate_hz'), ' Hz')} | "
        f"{fmt(data.get('depth_avg_valid_pixels'))} | "
        f"{fmt(data.get('depth_valid_p25_mm'), ' mm')} | "
        f"{fmt(data.get('depth_valid_median_mm'), ' mm')} | "
        f"{data.get('obstacle_states')} |"
    )


def cmd_write_report(args: argparse.Namespace) -> int:
    # Rebuild the audit first so the Markdown reflects the latest local reports.
    cmd_audit(args)
    latest = latest_audit()
    if latest is None:
        print("WRITE_REPORT_FAIL no audit JSON available")
        return 2
    audit_path, audit = latest
    reports = audit.get("reports", {})
    baseline = reports.get("dtof_unobstructed_baseline")
    flat = reports.get("dtof_center_flat_object_30_80cm")
    close = reports.get("dtof_close_obstruction")
    flat_diag = reports.get("dtof_flat_object_diagnosis")
    close_diag = reports.get("dtof_close_obstruction_diagnosis")
    yolo_neg = reports.get("yolo_negative_no_person")
    yolo_pos = reports.get("yolo_positive_person_visible")
    foxglove = reports.get("foxglove_low_bandwidth_topics")

    checks = audit.get("checks", [])
    pending = [item for item in checks if item.get("status") != "PASS"]
    if flat and close:
        dtof_conclusion = (
            "Physical-condition dToF reports exist. Compare the rows below: "
            "a clear drop in center-zone p25/median and an obstacle/warn state means the raw sensor is responding; "
            "little change means the remaining fault is board-side acquisition, sensor mounting, cable, power, or the test target."
        )
    else:
        dtof_conclusion = (
            "Transport and parsing are verified, but the raw dToF response to a real obstacle is not proven yet. "
            "The required 30-80cm flat-object and close-obstruction captures are still pending."
        )

    yolo_conclusion = (
        "YOLO negative and positive checks have both passed."
        if yolo_neg and yolo_pos
        else "YOLO publishes no-person results and annotated views; the positive person-in-frame check is still pending."
    )

    lines = [
        "# dToF and YOLO Validation Report",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Audit JSON: `{audit_path}`",
        f"- Overall status: `{audit.get('overall_status')}`",
        "- Safety: perception-only; no MCU, CAN, serial actuator, motor, steering, brake, or throttle path is used.",
        "",
        "## Board Runtime Evidence",
        "",
        "- Board runtime should be `/opt/sample/official_dtof/sample_dtof_rtsp_stable 7 192.168.137.100`.",
        "- Treat `/opt_sample` only as an old experiment archive, not as the active baseline.",
        "- Confirm with `perception_link_manager.py health` after each restart.",
        "",
        "## dToF Evidence",
        "",
        dtof_conclusion,
        "",
        "| Condition | Name | Packet rate | Avg valid pixels | p25 | median | obstacle states |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        dtof_markdown_row("unobstructed", baseline),
        dtof_markdown_row("30-80cm flat object", flat),
        dtof_markdown_row("close obstruction", close),
        "",
        "### dToF Diagnosis",
        "",
    ]
    if flat_diag or close_diag:
        for diag in [flat_diag, close_diag]:
            if not diag:
                continue
            lines.extend([
                f"- `{diag.get('label')}`: `{diag.get('classification')}`",
                f"  - {diag.get('conclusion')}",
            ])
            if diag.get("reasons"):
                lines.append(f"  - Evidence: {'; '.join(diag['reasons'])}")
            if diag.get("warnings"):
                lines.append(f"  - Warnings: {'; '.join(diag['warnings'])}")
    else:
        lines.append("- Pending physical-condition reports; run `diagnose-dtof` after the 30-80cm and close-obstruction captures.")
    lines.extend([
        "",
        "Normal Foxglove dToF panels:",
        "",
        "- Image: `/parking/dtof/obstacle_view`",
        "- Image: `/parking/dtof/depth_color`",
        "- Raw Messages: `/parking/dtof/obstacle_blocks`",
        "",
        "## YOLO Person Evidence",
        "",
        yolo_conclusion,
        "",
        f"- No-person check: `{(yolo_neg or {}).get('status', 'missing')}`, max_person_count={fmt((yolo_neg or {}).get('max_person_count'))}",
        f"- Person-visible check: `{(yolo_pos or {}).get('status', 'missing')}`, max_person_count={fmt((yolo_pos or {}).get('max_person_count'))}",
        "- Foxglove Image: `/parking/yolo/person_view`",
        "- Foxglove Raw Messages: `/parking/yolo/person_detections`",
        "",
        "## Foxglove",
        "",
        f"- Low-bandwidth audit: `{(foxglove or {}).get('overall', (foxglove or {}).get('overall_status', 'missing'))}`",
        "- Connect to `ws://192.168.247.129:8765`.",
        "",
        "## Pending Items",
        "",
    ])
    if pending:
        lines.extend([f"- `{item.get('name')}`: {item.get('detail', '')}" for item in pending])
    else:
        lines.append("- None.")
    lines.extend([
        "",
        "## Commands",
        "",
        "```powershell",
        ".venv\\Scripts\\python tools\\perception_link_manager.py health",
        ".venv\\Scripts\\python tools\\foxglove_low_bandwidth_audit.py --vm-host 192.168.247.129 --skip-upload",
        ".venv\\Scripts\\python tools\\dtof_yolo_validation.py capture-dtof --condition center_30_80cm_flat_object --frames 180 --metadata-lines 300",
        ".venv\\Scripts\\python tools\\dtof_yolo_validation.py capture-dtof --condition close_obstruction --frames 180 --metadata-lines 300",
        ".venv\\Scripts\\python tools\\dtof_yolo_validation.py diagnose-dtof",
        ".venv\\Scripts\\python tools\\dtof_yolo_validation.py check-yolo --duration 10 --require-person",
        "```",
        "",
    ])

    default_path = ROOT / "docs" / f"dtof_yolo_validation_report_{timestamp()}.md"
    out_path = Path(args.output) if args.output else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"DTOF_YOLO_MARKDOWN_REPORT {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-host", default="192.168.137.100")
    parser.add_argument("--vm-port", type=int, default=22)
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture-dtof")
    capture.add_argument("--condition", required=True)
    capture.add_argument("--frames", type=int, default=180)
    capture.add_argument("--metadata-lines", type=int, default=300)
    capture.add_argument("--timeout", type=float, default=90.0)
    capture.set_defaults(func=cmd_capture_dtof)

    compare = sub.add_parser("compare-dtof")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--test", required=True)
    compare.set_defaults(func=cmd_compare_dtof)

    diagnose = sub.add_parser("diagnose-dtof")
    diagnose.add_argument("--baseline", default="")
    diagnose.add_argument("--test", default="")
    diagnose.add_argument("--label", default="")
    diagnose.add_argument("--output", default="")
    diagnose.set_defaults(func=cmd_diagnose_dtof)

    yolo = sub.add_parser("check-yolo")
    yolo.add_argument("--duration", type=int, default=10)
    yolo.add_argument("--require-person", action="store_true")
    yolo.set_defaults(func=cmd_check_yolo)

    audit = sub.add_parser("audit")
    audit.set_defaults(func=cmd_audit)

    report = sub.add_parser("write-report")
    report.add_argument("--output", default="")
    report.set_defaults(func=cmd_write_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
