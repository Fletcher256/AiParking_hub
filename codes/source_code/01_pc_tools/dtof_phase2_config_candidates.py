#!/usr/bin/env python3
"""Generate local-only Phase2 dtof.ini candidates.

The generated files are not deployed to the board. They are ordered from lower
risk to higher risk and should only be used after Phase1 indicates that
DtofProcess/post-processing is dropping a near object.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "vendor" / "SS928V100_SDK_V2.0.2.2_MPP_Sample-master" / "src" / "dtof" / "dtof.ini"
DEFAULT_OUT_ROOT = ROOT / "artifacts" / "dtof_phase2_config_candidates"


Variant = dict[str, object]


VARIANTS: list[Variant] = [
    {
        "name": "01_modeswitch_only",
        "purpose": "Enable vendor near/far dynamic mode switching without changing filters.",
        "risk": "Low. If the official switch logic is correct, it should select 500ps for near scenes.",
        "changes": {("ModeSwitch", "configSwitchFlag"): "true"},
    },
    {
        "name": "02_modeswitch_low_time_weight",
        "purpose": "Keep mode switching on and reduce temporal inertia so a new near object is not averaged away.",
        "risk": "Low-medium. Depth may become noisier but should respond faster.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("TimeFilter", "weight"): "1.0",
            ("TimeFilter", "timeFilterFlag"): "true",
        },
    },
    {
        "name": "03_modeswitch_no_time_filter",
        "purpose": "Disable time filtering to check whether strong temporal smoothing is hiding near returns.",
        "risk": "Medium. Output can become noisy and less stable.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("TimeFilter", "timeFilterFlag"): "false",
        },
    },
    {
        "name": "04_modeswitch_relaxed_components",
        "purpose": "Relax connected-component filtering so sparse close returns are not removed as noise.",
        "risk": "Medium. More isolated noise and flying pixels can pass through.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("DepthDomain", "comFilterThreshold"): "1",
            ("DepthDomain", "maxDistanceClose"): "2000",
            ("DepthDomain", "maxPixelCountClose"): "1",
            ("DepthDomain", "maxPixelCountFar"): "1",
        },
    },
    {
        "name": "05_modeswitch_spatial_filters_off",
        "purpose": "Temporarily disable spatial cleanup to prove whether filtering is killing near pixels.",
        "risk": "Medium-high. Useful as diagnosis only; not a final parking config.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("DepthDomain", "depthDomainFlag"): "false",
            ("KillFlyingPixels", "killFlyingFlag"): "false",
        },
    },
    {
        "name": "06_modeswitch_first_echo_probe",
        "purpose": "Probe whether multi-echo ordering selects the far/background echo instead of the near object.",
        "risk": "Medium-high. echoOrderType semantics are vendor-library dependent.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("HistoProc", "echoOrderType"): "0",
        },
    },
    {
        "name": "07_single_echo_probe",
        "purpose": "Force a single echo candidate to check if dual-echo handling is selecting the wrong range.",
        "risk": "High. Can reduce robustness and should only be used as a short diagnostic.",
        "changes": {
            ("ModeSwitch", "configSwitchFlag"): "true",
            ("HistoProc", "echoNum"): "1",
            ("HistoProc", "echoOrderType"): "0",
        },
    },
    {
        "name": "08_debug_logging_only",
        "purpose": "Increase vendor logging if library-side logs become useful during a board run.",
        "risk": "Low for data interpretation, but may add runtime log volume.",
        "changes": {("LogEvent", "logEvent"): "1"},
    },
]


def split_assignment(line: str) -> tuple[str, str] | None:
    if "=" not in line or line.lstrip().startswith(("#", ";")):
        return None
    key, rest = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, rest


def replace_value(line: str, value: str) -> str:
    key, rest = line.split("=", 1)
    newline = "\n" if line.endswith("\n") else ""
    rest = rest[:-1] if newline else rest
    if ";" in rest:
        _, comment = rest.split(";", 1)
        return f"{key}={value};{comment}{newline}"
    return f"{key}={value}{newline}"


def apply_changes(lines: Iterable[str], changes: dict[tuple[str, str], str]) -> tuple[list[str], list[str]]:
    section = ""
    pending = set(changes)
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            section = stripped[1 : stripped.index("]")]
            output.append(line)
            continue

        assignment = split_assignment(line)
        if assignment is None:
            output.append(line)
            continue

        key, _ = assignment
        change_key = (section, key)
        if change_key in changes:
            output.append(replace_value(line, str(changes[change_key])))
            pending.remove(change_key)
        else:
            output.append(line)

    missing = [f"{section}.{key}" for section, key in sorted(pending)]
    return output, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    baseline = Path(args.baseline)
    if not baseline.exists():
        raise SystemExit(f"baseline not found: {baseline}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_lines = baseline.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    (out_dir / "dtof.ini.baseline").write_text("".join(baseline_lines), encoding="utf-8")

    manifest: dict[str, object] = {
        "baseline": str(baseline),
        "out_dir": str(out_dir),
        "safety": "Local-only candidates. Do not deploy until Phase1 proves post-processing is the likely fault.",
        "variants": [],
    }

    md_lines = [
        "# Phase2 dtof.ini candidates",
        "",
        "These files are generated locally only. They are not deployed to the board.",
        "Use them only after Phase1 shows that raw data changes with a near target but DtofProcess/UDP output remains wrong.",
        "",
    ]

    for variant in VARIANTS:
        changes = variant["changes"]
        assert isinstance(changes, dict)
        output_lines, missing = apply_changes(baseline_lines, changes)
        name = str(variant["name"])
        path = out_dir / f"dtof_{name}.ini"
        path.write_text("".join(output_lines), encoding="utf-8")
        manifest["variants"].append(
            {
                "name": name,
                "path": str(path),
                "purpose": variant["purpose"],
                "risk": variant["risk"],
                "changes": {f"{section}.{key}": value for (section, key), value in changes.items()},
                "missing": missing,
            }
        )
        md_lines.extend(
            [
                f"## {name}",
                "",
                f"Purpose: {variant['purpose']}",
                "",
                f"Risk: {variant['risk']}",
                "",
                "Changes:",
                *[f"- {section}.{key} = {value}" for (section, key), value in changes.items()],
                "",
            ]
        )
        if missing:
            md_lines.extend(["Missing keys:", *[f"- {item}" for item in missing], ""])

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
