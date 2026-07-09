#!/usr/bin/env python3
"""Aggregate perception-only evidence for the current parking bring-up goal.

This script runs read-only/status checks from the Windows workspace. It does
not start or stop board, VM, MCU, CAN, serial actuator, motor, steering, brake,
or throttle processes.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
ARTIFACT_DIR = ROOT / "artifacts" / "perception_goal_audit"


def run_step(name: str, parts: list[str], timeout: float, allowed_rc: set[int] | None = None) -> dict[str, Any]:
    allowed = allowed_rc if allowed_rc is not None else {0}
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        result = subprocess.run(
            parts,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = result.stdout
        rc = int(result.returncode)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\nTIMEOUT\n"
        rc = 124
    status = "PASS" if rc in allowed else "FAIL"
    print(f"{status} {name} rc={rc}")
    return {
        "name": name,
        "started_at": started,
        "returncode": rc,
        "status": status,
        "stdout": output,
    }


def latest_json(root: Path, pattern: str = "*.json") -> tuple[Path, dict[str, Any]] | None:
    if not root.exists():
        return None
    files = sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime)
    for path in reversed(files):
        try:
            return path, json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def contains_all(text: str, needles: list[str]) -> bool:
    return all(needle in text for needle in needles)


def derive_checks(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_name = {step["name"]: step for step in steps}
    health = by_name.get("perception_link_health", {}).get("stdout", "")
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add(
        "board_official_case7_running",
        "PASS" if contains_all(health, ["BOARD_CASE7_RUNNING yes", "BOARD_CASE7_BINARY ./sample_dtof_rtsp_stable"]) else "FAIL",
        "board health reports /opt/sample/official_dtof stable case7 runtime",
    )
    add(
        "vm_ros_running",
        "PASS" if "VM_PARKING_ROS_RUNNING yes" in health else "FAIL",
        "VM ROS2 parking receiver is running",
    )
    add(
        "vm_camera_and_dtof_ok",
        "PASS" if contains_all(health, ["VM_LAST_CAMERA_OK True", "VM_LAST_DTOF_OK True", "VM_ANY_BOTH_OK True"]) else "FAIL",
        "VM receives OS08A20 RTSP and SS-LD-AS01 UDP together",
    )
    add(
        "stm32_disabled",
        "PASS" if "VM_STM32_SESSION_COUNT 0" in health else "FAIL",
        "no STM32 session is active in the perception session root",
    )
    add(
        "direct_udp_route",
        "PASS" if "HOST_FORWARDER_SKIPPED_DIRECT_ROUTE yes" in health else "FAIL",
        "wired mode uses board -> VM 192.168.137.100:2368 directly",
    )

    dtof_audit = latest_json(ROOT / "artifacts" / "dtof_yolo_validation" / "audits")
    if dtof_audit:
        path, data = dtof_audit
        audit_checks = {item.get("name"): item.get("status") for item in data.get("checks", [])}
        add(
            "dtof_unobstructed_baseline",
            "PASS" if audit_checks.get("dtof_unobstructed_baseline") == "PASS" else "PENDING",
            str(path),
        )
        add(
            "dtof_physical_conditions",
            "PASS"
            if audit_checks.get("dtof_center_flat_object_30_80cm") == "PASS"
            and audit_checks.get("dtof_close_obstruction") == "PASS"
            else "PENDING",
            "needs 30-80cm flat-object and close-obstruction captures",
        )
        add(
            "yolo_negative",
            "PASS" if audit_checks.get("yolo_negative_no_person") == "PASS" else "PENDING",
            str(path),
        )
        add(
            "yolo_positive",
            "PASS" if audit_checks.get("yolo_positive_person_visible") == "PASS" else "PENDING",
            "needs person visible in OS08A20 frame",
        )
    else:
        add("dtof_yolo_audit", "PENDING", "no dtof_yolo_validation audit JSON found")

    fox = latest_json(ROOT / "artifacts" / "foxglove_low_bandwidth_audit")
    if fox:
        path, data = fox
        add(
            "foxglove_low_bandwidth_topics",
            "PASS" if data.get("overall") == "PASS" or data.get("overall_status") == "PASS" else "FAIL",
            str(path),
        )
    else:
        add("foxglove_low_bandwidth_topics", "PENDING", "no Foxglove audit JSON found")
    return checks


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Perception Goal Audit",
        "",
        f"- Generated: {report['created_at']}",
        f"- Overall: `{report['overall_status']}`",
        "- Safety: perception-only; no actuator control path is started by this audit.",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        lines.append(f"| {check['name']} | {check['status']} | {check['detail']} |")
    lines.extend([
        "",
        "## Remaining Physical Actions",
        "",
        "- Place a flat object 30-80cm in front of the dToF, centered, and hold still for 10 seconds.",
        "- Then perform a close-obstruction capture.",
        "- Stand in the OS08A20 camera frame for the YOLO positive check.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    steps = [
        run_step(
            "perception_link_health",
            [str(PYTHON), "tools\\perception_link_manager.py", "health"],
            timeout=180.0,
        ),
        run_step(
            "dtof_yolo_audit",
            [str(PYTHON), "tools\\dtof_yolo_validation.py", "audit"],
            timeout=60.0,
            allowed_rc={0, 1},
        ),
        run_step(
            "foxglove_low_bandwidth_audit",
            [str(PYTHON), "tools\\foxglove_low_bandwidth_audit.py", "--vm-host", "192.168.247.129", "--skip-upload"],
            timeout=120.0,
        ),
    ]
    checks = derive_checks(steps)
    hard_fail = any(check["status"] == "FAIL" for check in checks)
    pending = any(check["status"] == "PENDING" for check in checks)
    overall = "FAIL" if hard_fail else ("PENDING" if pending else "PASS")
    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_status": overall,
        "checks": checks,
        "steps": steps,
    }
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = ARTIFACT_DIR / f"perception_goal_audit_{stamp}.json"
    md_path = ARTIFACT_DIR / f"perception_goal_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(f"PERCEPTION_GOAL_AUDIT_JSON {json_path}")
    print(f"PERCEPTION_GOAL_AUDIT_MD {md_path}")
    print(f"PERCEPTION_GOAL_AUDIT_OVERALL {overall}")
    return 0 if overall == "PASS" else (2 if overall == "PENDING" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
