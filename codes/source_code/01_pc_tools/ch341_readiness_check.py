#!/usr/bin/env python3
"""Read-only readiness check for a proper CH340/CH341 board driver path."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VM_TOOL = ROOT / "tools" / "vm_ssh_run.py"
PYTHON = ROOT / ".venv" / "Scripts" / "python"


def run(parts: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        parts,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def vm_readonly(args: argparse.Namespace, command: str) -> str:
    result = run([
        str(PYTHON),
        str(VM_TOOL),
        "--host",
        args.host,
        "--user",
        args.user,
        "--password",
        args.password,
        "--timeout",
        str(args.timeout),
        "run",
        command,
    ], timeout=args.timeout + 15)
    return result.stdout


def find_files(name: str) -> list[str]:
    roots = [ROOT / "vendor", ROOT / "board_files"]
    matches: list[str] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob(name):
            if path.is_file():
                matches.append(str(path.relative_to(ROOT)))
    return sorted(matches)


def find_matching_kernel_inputs() -> list[str]:
    roots = [ROOT / "vendor", ROOT / "board_files"]
    markers = {
        "include/generated/utsrelease.h",
        "include/generated/autoconf.h",
        "Module.symvers",
    }
    matches: list[str] = []
    for base in roots:
        if not base.exists():
            continue
        for marker in markers:
            for path in base.rglob(Path(marker).name):
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT)
                text = ""
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
                if "4.19.90" in text or path.name == "Module.symvers":
                    matches.append(str(rel))
    return sorted(set(matches))


def count_patch_lines(pattern: str) -> int:
    count = 0
    for base in (ROOT / "vendor", ROOT / "board_files"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".patch", ".config", ".txt", ".md"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            count += text.count(pattern)
    return count


def defconfig_ch341_settings() -> list[dict[str, str]]:
    settings: list[dict[str, str]] = []
    current = ""
    for base in (ROOT / "vendor", ROOT / "board_files"):
        if not base.exists():
            continue
        for path in base.rglob("*.patch"):
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines, start=1):
                if line.startswith("diff --git a/arch/arm64/configs/"):
                    current = line.split("diff --git a/arch/arm64/configs/", 1)[1].split()[0]
                if "CONFIG_USB_SERIAL_CH341" not in line:
                    continue
                value = "unknown"
                if "CONFIG_USB_SERIAL_CH341=y" in line:
                    value = "y"
                elif "# CONFIG_USB_SERIAL_CH341 is not set" in line:
                    value = "not_set"
                settings.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "line": str(index),
                        "defconfig": current or "unknown",
                        "value": value,
                    }
                )
    return settings


def parse_key_values(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.100")
    parser.add_argument("--user", default="ebaina")
    parser.add_argument("--password", default="ebaina")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    vm_output = vm_readonly(
        args,
        "bash -lc '"
        "echo AARCH64_GNU=$(command -v aarch64-linux-gnu-gcc || true); "
        "echo AARCH64_MIX210=$(command -v aarch64-mix210-linux-gcc || true); "
        "echo MAKE=$(command -v make || true); "
        "echo HOME_LINUX=$(test -d ~/linux && echo yes || echo no); "
        "echo HOME_KERNEL=$(test -d ~/kernel && echo yes || echo no); "
        "echo MODULES_41990=$(test -d /lib/modules/4.19.90 && echo yes || echo no); "
        "echo HEADERS_41990=$(test -d /usr/src/linux-headers-4.19.90 && echo yes || echo no)'",
    )
    vm = parse_key_values(vm_output)

    ch341_sources = find_files("ch341.c")
    ch341_modules = find_files("ch341.ko")
    ch343_sources = find_files("ch343.c")
    matching_kernel_inputs = find_matching_kernel_inputs()
    enabled_count = count_patch_lines("CONFIG_USB_SERIAL_CH341=y")
    disabled_count = count_patch_lines("# CONFIG_USB_SERIAL_CH341 is not set")
    defconfig_settings = defconfig_ch341_settings()
    ss928_emmc_settings = [
        item for item in defconfig_settings
        if item["defconfig"].endswith("ss928v100_emmc_defconfig")
    ]
    has_conflicting_defconfigs = bool(
        {item["value"] for item in defconfig_settings if item["value"] in {"y", "not_set"}} - {"unknown"}
    ) and len({item["value"] for item in defconfig_settings if item["value"] in {"y", "not_set"}}) > 1

    result: dict[str, Any] = {
        "vm": vm,
        "local": {
            "ch341_c_files": ch341_sources,
            "ch341_ko_files": ch341_modules,
            "ch343_c_files": ch343_sources,
            "matching_4_19_90_kernel_input_markers": matching_kernel_inputs,
            "defconfig_ch341_settings": defconfig_settings,
            "ss928v100_emmc_ch341_settings": ss928_emmc_settings,
            "has_conflicting_defconfig_ch341_settings": has_conflicting_defconfigs,
            "config_ch341_enabled_count": enabled_count,
            "config_ch341_disabled_count": disabled_count,
        },
    }
    has_toolchain = bool(vm.get("AARCH64_GNU") or vm.get("AARCH64_MIX210")) and bool(vm.get("MAKE"))
    has_matching_kernel = (
        vm.get("MODULES_41990") == "yes"
        or vm.get("HEADERS_41990") == "yes"
        or bool(matching_kernel_inputs)
    )
    has_driver_source = bool(ch341_sources)
    has_ready_module = bool(ch341_modules)
    result["assessment"] = {
        "has_cross_toolchain": has_toolchain,
        "has_official_ch341_driver_source": has_driver_source,
        "has_matching_kernel_inputs": has_matching_kernel,
        "has_ready_ch341_module": has_ready_module,
        "can_build_or_install_now": has_toolchain and (has_matching_kernel or has_ready_module),
        "recommended_next": (
            "obtain matching 4.19.90 board kernel tree/headers or an image with CONFIG_USB_SERIAL_CH341=y"
        ),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("CH341_READINESS")
        print(f"has_cross_toolchain={has_toolchain}")
        print(f"has_official_ch341_driver_source={has_driver_source}")
        print(f"has_matching_kernel_inputs={has_matching_kernel}")
        print(f"has_ready_ch341_module={has_ready_module}")
        print(f"can_build_or_install_now={result['assessment']['can_build_or_install_now']}")
        print(f"ch341_c_files={len(ch341_sources)}")
        print(f"ch341_ko_files={len(ch341_modules)}")
        print(f"ch343_c_files={len(ch343_sources)}")
        print(f"matching_4_19_90_kernel_input_markers={len(matching_kernel_inputs)}")
        for item in defconfig_settings:
            print(
                "defconfig_ch341_setting="
                f"{item['defconfig']}:{item['value']}:{item['path']}:{item['line']}"
            )
        print(f"config_ch341_enabled_count={enabled_count}")
        print(f"config_ch341_disabled_count={disabled_count}")
        print(f"recommended_next={result['assessment']['recommended_next']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
