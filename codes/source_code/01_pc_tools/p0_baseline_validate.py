#!/usr/bin/env python3
"""P0 stable-baseline validator for the current parking control chain.

This script is deliberately local/offline only: it does not open COM11, SSH to
the VM, start YOLO, or send STM32 commands.  It checks that the repository state
contains the agreed rollout_optimizer baseline and then runs the offline regression
tests that protect that baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "configs/active_parking_control_chain.json",
    "configs/chassis_kinematics.json",
    "configs/chassis_signs.json",
    "configs/parking_success_criteria.json",
    "configs/perception_filter.json",
    "configs/parking_rollout_optimizer_h1.json",
    "docs/active_parking_control_chain_20260707.md",
    "docs/controller_modularization_20260707.md",
    "docs/parking_line_follow_decision_20260704.md",
    "tools/board_parking_controller.py",
    "tools/parking_controller_core.py",
    "tools/parking_line_follow_decision.py",
    "tools/parking_rollout_optimizer.py",
    "tools/parking_fusion.py",
    "tools/parking_line_accumulator.py",
    "tools/parking_kinematic_lattice.py",
    "tools/board_stm32_button_autopark.py",
    "tools/parking_web_controller.py",
    "tools/run_recorded_line_follow_demo.py",
    "tools/test_parking_controller_core.py",
    "tools/test_parking_line_follow_decision.py",
    "tools/test_parking_rollout_optimizer.py",
    "tools/test_h1_line_follow_integration.py",
    "tools/test_perception_filter.py",
    "tools/test_parking_line_accumulator.py",
]

PY_COMPILE_FILES = [
    "tools/board_parking_controller.py",
    "tools/parking_controller_core.py",
    "tools/parking_line_follow_decision.py",
    "tools/parking_rollout_optimizer.py",
    "tools/parking_fusion.py",
    "tools/parking_line_accumulator.py",
    "tools/parking_kinematic_lattice.py",
    "tools/board_stm32_button_autopark.py",
    "tools/parking_web_controller.py",
    "tools/run_recorded_line_follow_demo.py",
    "tools/test_parking_controller_core.py",
    "tools/test_parking_line_follow_decision.py",
    "tools/test_parking_rollout_optimizer.py",
    "tools/test_h1_line_follow_integration.py",
    "tools/test_perception_filter.py",
    "tools/test_parking_line_accumulator.py",
]

UNITTEST_MODULES = [
    "tools.test_parking_controller_core",
    "tools.test_parking_line_follow_decision",
    "tools.test_parking_rollout_optimizer",
    "tools.test_h1_line_follow_integration",
    "tools.test_perception_filter",
    "tools.test_parking_line_accumulator",
]

FORBIDDEN_DEFAULT_CHAIN_TOKENS = [
    "h1_lattice_mpc",
    "path_template_planner",
]


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace(os.sep, "/")


def add_check(checks: list[dict], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def check_required_files(checks: list[dict]) -> None:
    for item in REQUIRED_FILES:
        path = REPO_ROOT / item
        add_check(checks, f"required_file:{item}", path.exists(), item)


def check_active_chain(checks: list[dict]) -> dict:
    path = REPO_ROOT / "configs/active_parking_control_chain.json"
    try:
        cfg = load_json(path)
    except Exception as exc:  # noqa: BLE001 - report all parse/read failures.
        add_check(checks, "active_config:load", False, str(exc))
        return {}

    argv = list(cfg.get("argv") or [])
    argv_text = "\n".join(str(x) for x in argv)

    add_check(
        checks,
        "active_config:schema",
        cfg.get("schema") == "parking.active_control_chain.v1",
        str(cfg.get("schema")),
    )
    add_check(
        checks,
        "active_config:chain_id_rollout_optimizer",
        cfg.get("active_chain_id") == "rollout_optimizer",
        str(cfg.get("active_chain_id")),
    )
    add_check(
        checks,
        "active_config:strategy",
        "--strategy" in argv and "diy_first_frame_path_parking" in argv,
        " ".join(argv[:8]),
    )
    add_check(
        checks,
        "active_config:structured_decision_rollout_optimizer",
        "--diy-path-structured-decision" in argv and "rollout_optimizer" in argv,
        "--diy-path-structured-decision rollout_optimizer",
    )
    add_check(
        checks,
        "active_config:rollout_optimizer_config",
        "--diy-path-rollout-optimizer-config-json" in argv
        and "/opt/parking/autopark/parking_rollout_optimizer_h1.json" in argv,
        "--diy-path-rollout-optimizer-config-json",
    )
    def _argv_float(name):
        try:
            return float(argv[argv.index(name) + 1])
        except Exception:  # noqa: BLE001 - validation should report missing/bad values.
            return None

    target_y_value = _argv_float("--diy-path-effective-target-y-cm")
    lateral_tol_value = _argv_float("--diy-path-success-lateral-tol-cm")
    heading_tol_value = _argv_float("--diy-path-success-heading-tol-deg")
    bottom_y_value = _argv_float("--diy-path-bottom-depth-success-y-cm")
    shuffle_heading_trigger_value = _argv_float("--diy-path-terminal-shuffle-heading-trigger-deg")
    relax_cap_value = _argv_float("--diy-path-bottom-depth-success-heading-relax-cap-deg")
    add_check(
        checks,
        "active_config:target_y_1p5cm",
        target_y_value == 1.5,
        str(target_y_value),
    )
    add_check(
        checks,
        "active_config:success_lateral_tol_2cm",
        lateral_tol_value == 2.0,
        str(lateral_tol_value),
    )
    add_check(
        checks,
        "active_config:success_heading_tol_3deg",
        heading_tol_value == 3.0,
        str(heading_tol_value),
    )
    add_check(
        checks,
        "active_config:bottom_depth_y_2cm",
        bottom_y_value == 2.0,
        str(bottom_y_value),
    )
    add_check(
        checks,
        "active_config:terminal_shuffle_heading_trigger_3deg",
        shuffle_heading_trigger_value == 3.0,
        str(shuffle_heading_trigger_value),
    )
    add_check(
        checks,
        "active_config:final_heading_relax_cap_3deg",
        relax_cap_value == 3.0,
        str(relax_cap_value),
    )
    add_check(
        checks,
        "active_config:yolo_udp",
        (cfg.get("yolo_udp") or {}).get("host") == "127.0.0.1"
        and int((cfg.get("yolo_udp") or {}).get("port", -1)) == 24580,
        json.dumps(cfg.get("yolo_udp"), ensure_ascii=False),
    )
    add_check(
        checks,
        "active_config:stm32_button_trigger",
        (cfg.get("stm32") or {}).get("button_trigger") == "CTR_PK",
        json.dumps(cfg.get("stm32"), ensure_ascii=False),
    )
    for token in FORBIDDEN_DEFAULT_CHAIN_TOKENS:
        add_check(
            checks,
            f"active_config:forbidden_default_absent:{token}",
            token not in argv_text and cfg.get("active_chain_id") != token,
            token,
        )
    deprecated = {str(row.get("chain_id")) for row in cfg.get("deprecated_for_default_start") or []}
    for token in FORBIDDEN_DEFAULT_CHAIN_TOKENS:
        add_check(
            checks,
            f"active_config:deprecated_declared:{token}",
            token in deprecated,
            ",".join(sorted(deprecated)),
        )
    return cfg


def check_docs(checks: list[dict]) -> None:
    active_doc = (REPO_ROOT / "docs/active_parking_control_chain_20260707.md").read_text(
        encoding="utf-8", errors="replace"
    )
    line_doc = (REPO_ROOT / "docs/parking_line_follow_decision_20260704.md").read_text(
        encoding="utf-8", errors="replace"
    )
    add_check(
        checks,
        "docs:active_mentions_rollout_optimizer",
        "rollout_optimizer" in active_doc,
        "docs/active_parking_control_chain_20260707.md",
    )
    add_check(
        checks,
        "docs:modular_dependency_documented",
        "parking_controller_core.py" in active_doc and "新增硬依赖" in active_doc,
        "docs/active_parking_control_chain_20260707.md",
    )
    add_check(
        checks,
        "docs:line_follow_deploy_list_has_core",
        "parking_controller_core.py" in line_doc,
        "docs/parking_line_follow_decision_20260704.md",
    )


def check_py_compile(checks: list[dict]) -> None:
    for item in PY_COMPILE_FILES:
        path = REPO_ROOT / item
        if not path.exists():
            add_check(checks, f"py_compile:{item}", False, "missing")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            add_check(checks, f"py_compile:{item}", False, str(exc))
        else:
            add_check(checks, f"py_compile:{item}", True, item)


def run_unittests(checks: list[dict]) -> dict:
    cmd = [sys.executable, "-m", "unittest", *UNITTEST_MODULES]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    output = proc.stdout.strip()
    add_check(
        checks,
        "offline_unittest_suite",
        proc.returncode == 0,
        output.splitlines()[-1] if output else "no output",
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "output": output,
    }


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["stamp"]
    stamped = output_dir / f"p0_baseline_validation_{stamp}.json"
    latest = output_dir / "latest_p0_baseline_validation.json"
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    stamped.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return stamped, latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Only run structural/config checks; skip unittest subprocess.",
    )
    parser.add_argument(
        "--no-write-report",
        action="store_true",
        help="Do not write artifacts/p0_baseline/*.json report files.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/p0_baseline",
        help="Directory for validation reports when writing is enabled.",
    )
    args = parser.parse_args(argv)

    checks: list[dict] = []
    started = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S")

    check_required_files(checks)
    active_config = check_active_chain(checks)
    check_docs(checks)
    check_py_compile(checks)
    unittest_result = None
    if not args.skip_tests:
        unittest_result = run_unittests(checks)

    ok = all(item["ok"] for item in checks)
    report = {
        "schema": "parking.p0_baseline_validation.v1",
        "stamp": stamp,
        "repo_root": str(REPO_ROOT),
        "duration_sec": round(time.time() - started, 3),
        "ok": ok,
        "summary": {
            "checks_total": len(checks),
            "checks_passed": sum(1 for item in checks if item["ok"]),
            "checks_failed": sum(1 for item in checks if not item["ok"]),
            "active_chain_id": active_config.get("active_chain_id"),
            "active_updated": active_config.get("updated"),
            "tests_skipped": bool(args.skip_tests),
        },
        "checks": checks,
        "unittest": unittest_result,
    }

    if not args.no_write_report:
        stamped, latest = write_report(report, REPO_ROOT / args.output_dir)
        report["written_reports"] = [rel(stamped), rel(latest)]

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not ok:
        print("\nFAILED CHECKS:")
        for item in checks:
            if not item["ok"]:
                print(f"- {item['name']}: {item['detail']}")
    elif not args.no_write_report:
        print("\nReports:")
        for item in report["written_reports"]:
            print(f"- {item}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
