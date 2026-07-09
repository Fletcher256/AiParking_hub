#!/usr/bin/env python3
"""Run the VM RTSP quality/latency audit through the current perception link config."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python"
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
VM_AUDIT = ROOT / "tools" / "vm_rtsp_quality_latency_audit.py"
DEFAULT_CONFIG = ROOT / "artifacts" / "current_link_config.json"
REPORT_ROOT = ROOT / "artifacts" / "rtsp_quality_latency_audit"


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


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--vm-host", default="")
    parser.add_argument("--vm-user", default="ebaina")
    parser.add_argument("--vm-password", default="ebaina")
    parser.add_argument("--rtsp-url", default="")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--vm-timeout", type=float, default=180.0)
    args = parser.parse_args()

    config = load_config(args.config)
    vm_host = args.vm_host or str(config.get("vm_ip") or "")
    rtsp_url = args.rtsp_url or str(config.get("rtsp_url") or "")
    if not vm_host or not rtsp_url:
        print("RTSP_QUALITY_LATENCY_AUDIT FAIL")
        print(f"missing vm_host={vm_host!r} rtsp_url={rtsp_url!r}")
        return 2

    base = [
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        vm_host,
        "--user",
        args.vm_user,
        "--password",
        args.vm_password,
    ]
    upload = run(base + ["--allow-risk", "put-text", str(VM_AUDIT), "/tmp/vm_rtsp_quality_latency_audit.py"], args.vm_timeout)
    audit_cmd = (
        "python3 /tmp/vm_rtsp_quality_latency_audit.py "
        f"--url {rtsp_url!r} --seconds {int(args.seconds)}"
    )
    audit = run(base + ["--timeout", str(args.vm_timeout), "--allow-risk", "run", audit_cmd], args.vm_timeout + 20)

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_ROOT / f"rtsp_quality_latency_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vm_host": vm_host,
        "rtsp_url": rtsp_url,
        "config": str(args.config),
        "upload": {"returncode": upload.returncode, "stdout": upload.stdout},
        "audit": {"returncode": audit.returncode, "stdout": audit.stdout},
        "overall": "PASS" if upload.returncode == 0 and audit.returncode == 0 and "RTSP_QUALITY_LATENCY_AUDIT PASS" in audit.stdout else "FAIL",
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"RTSP_QUALITY_LATENCY_HOST_REPORT {report_path}")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
