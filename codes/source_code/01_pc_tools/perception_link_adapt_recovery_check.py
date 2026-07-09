#!/usr/bin/env python3
"""Verify that the perception link recovers from stale IP configuration.

This check is perception-only. It intentionally overwrites the local
artifacts/current_link_config.json with bogus addresses, then runs the normal
one-command perception_link_manager adapt path. Passing this check proves that
the active path re-discovers board/VM/host IPs instead of trusting stale manual
IP values.

It starts/stops only the camera+dToF sensing stack through
perception_link_manager.py. It does not start MCU, CAN, serial actuator, motor,
steering, brake, throttle, or chassis-control commands.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
MANAGER = ROOT / "tools" / "perception_link_manager.py"
DEFAULT_CONFIG = ROOT / "artifacts" / "current_link_config.json"
REPORT_ROOT = ROOT / "artifacts" / "perception_link_adapt_recovery"

STALE_BOARD_IP = "10.255.10.2"
STALE_HOST_IP = "10.255.10.1"
STALE_VM_IP = "10.255.20.100"


def run(parts: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    print(f"RUN {' '.join(parts)}", flush=True)
    proc = subprocess.run(
        parts,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    print(proc.stdout, end="", flush=True)
    print(f"EXIT_CODE {proc.returncode}", flush=True)
    return proc


def manager(args: argparse.Namespace, action: str) -> subprocess.CompletedProcess[str]:
    cmd = [str(PYTHON), str(MANAGER), action, "--config", str(args.config)]
    if args.vm_host:
        cmd.extend(["--vm-host", args.vm_host])
    if action in {"adapt", "start", "stop"}:
        cmd.append("--allow-risk")
    return run(cmd, args.manager_timeout)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def write_stale_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = {
        "schema_version": 1,
        "generated_at_unix": time.time(),
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "safety": {
            "perception_only": True,
            "actuator_control_allowed": False,
            "notes": "Intentional stale config for adapt recovery validation.",
        },
        "board_ip": STALE_BOARD_IP,
        "vm_ip": STALE_VM_IP,
        "host_forward_ip": STALE_HOST_IP,
        "rtsp_url": f"rtsp://{STALE_BOARD_IP}:554/live0",
        "dtof_udp_route": {
            "mode": "host_forwarder",
            "board_udp_target_ip": STALE_HOST_IP,
            "listen_port": 2368,
            "forward_target": f"{STALE_VM_IP}:2368",
            "target": f"{STALE_HOST_IP}:2368 -> {STALE_VM_IP}:2368",
        },
        "foxglove_ws_url": f"ws://{STALE_VM_IP}:8765",
        "issues": ["intentional_stale_config"],
    }
    path.write_text(json.dumps(stale, ensure_ascii=False, indent=2), encoding="utf-8")


def trim(text: str, limit: int = 60000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[trimmed]...\n" + text[-half:]


def extract_bool(text: str, key: str) -> bool | None:
    match = re.search(rf"^{re.escape(key)}\s+(\w+)", text, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).lower()
    if value in {"true", "yes", "1"}:
        return True
    if value in {"false", "no", "0"}:
        return False
    return None


def add_check(checks: list[dict[str, str]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})


def write_report(report: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"adapt_recovery_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--vm-host", default="")
    parser.add_argument("--manager-timeout", type=float, default=300.0)
    parser.add_argument("--skip-adapt", action="store_true", help="Only prove discover rewrites stale config.")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "safety": {
            "perception_only": True,
            "actuator_control_allowed": False,
            "stm32_enabled": False,
        },
        "steps": {},
        "checks": [],
    }

    original_text = args.config.read_text(encoding="utf-8", errors="replace") if args.config.exists() else ""
    original = load_json(args.config)
    report["original_config_summary"] = {
        "board_ip": original.get("board_ip", ""),
        "host_forward_ip": original.get("host_forward_ip", ""),
        "vm_ip": original.get("vm_ip", ""),
        "rtsp_url": original.get("rtsp_url", ""),
        "foxglove_ws_url": original.get("foxglove_ws_url", ""),
    }

    write_stale_config(args.config)
    report["steps"]["write_stale_config"] = {
        "returncode": 0,
        "stdout": f"stale board={STALE_BOARD_IP} host={STALE_HOST_IP} vm={STALE_VM_IP}",
    }

    try:
        action = "discover" if args.skip_adapt else "adapt"
        adapt = manager(args, action)
        report["steps"][action] = {"returncode": adapt.returncode, "stdout": trim(adapt.stdout)}

        health = manager(args, "health")
        report["steps"]["health"] = {"returncode": health.returncode, "stdout": trim(health.stdout)}

        current = load_json(args.config)
        report["final_config_summary"] = {
            "board_ip": current.get("board_ip", ""),
            "host_forward_ip": current.get("host_forward_ip", ""),
            "vm_ip": current.get("vm_ip", ""),
            "rtsp_url": current.get("rtsp_url", ""),
            "dtof_udp_route": current.get("dtof_udp_route", {}),
            "foxglove_ws_url": current.get("foxglove_ws_url", ""),
            "issues": current.get("issues", []),
        }

        stale_values = {STALE_BOARD_IP, STALE_HOST_IP, STALE_VM_IP}
        final_values = {
            str(current.get("board_ip", "")),
            str(current.get("host_forward_ip", "")),
            str(current.get("vm_ip", "")),
            str(current.get("rtsp_url", "")),
            str(current.get("foxglove_ws_url", "")),
            str(current.get("dtof_udp_route", {}).get("target", "")),
        }
        checks = report["checks"]
        add_check(checks, "adapt_or_discover_exit_code", adapt.returncode == 0, f"exit_code={adapt.returncode}")
        add_check(checks, "health_exit_code", health.returncode == 0, f"exit_code={health.returncode}")
        add_check(checks, "stale_values_removed", not any(value in field for value in stale_values for field in final_values), str(final_values))
        add_check(checks, "board_ip_present", bool(current.get("board_ip")), str(current.get("board_ip", "")))
        add_check(checks, "vm_ip_present", bool(current.get("vm_ip")), str(current.get("vm_ip", "")))
        add_check(checks, "host_forward_ip_present", bool(current.get("host_forward_ip")), str(current.get("host_forward_ip", "")))
        add_check(checks, "rtsp_uses_board_ip", str(current.get("board_ip", "")) in str(current.get("rtsp_url", "")), str(current.get("rtsp_url", "")))
        add_check(checks, "foxglove_uses_vm_ip", str(current.get("vm_ip", "")) in str(current.get("foxglove_ws_url", "")), str(current.get("foxglove_ws_url", "")))
        add_check(checks, "camera_ok", extract_bool(health.stdout, "VM_LAST_CAMERA_OK") is True, "VM_LAST_CAMERA_OK")
        add_check(checks, "dtof_ok", extract_bool(health.stdout, "VM_LAST_DTOF_OK") is True, "VM_LAST_DTOF_OK")
        add_check(checks, "udp_forwarder_no_errors", '"errors": 0' in health.stdout, "host UDP forwarder errors=0")
        add_check(checks, "stm32_disabled", "VM_STM32_SESSION_COUNT 0" in health.stdout, "STM32 not part of this check")

        report["overall"] = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    finally:
        if report.get("overall") != "PASS" and original_text:
            args.config.write_text(original_text, encoding="utf-8")
            report["restored_original_config_after_failure"] = True

    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = write_report(report)
    print(f"PERCEPTION_LINK_ADAPT_RECOVERY {report.get('overall', 'FAIL')}")
    for item in report["checks"]:
        print(f"{item['status']:4} {item['name']} - {item['detail']}")
    print(f"PERCEPTION_LINK_ADAPT_RECOVERY_REPORT {path}")
    return 0 if report.get("overall") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

