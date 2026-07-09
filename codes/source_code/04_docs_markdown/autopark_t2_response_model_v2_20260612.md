# Autopark T2 Response Model v2 - 2026-06-12

## Goal

Implement the v2 response model and update tool from
`docs/autopark_codex_execution_plan_20260612.md`.

T2 is software-only. It does not start motion or connect to STM32.

## Implemented Files

- `tools/parking_response_model_updater.py`
- `configs/parking_action_response_model.json`
- `tools/parking_action_scorer.py`

## Response Model Schema

The response model is now:

```text
parking_action_response_model.v2
```

It stores measured action response by state bucket:

```text
phase
x_err_sign
x_err_bin
heading_bin
```

Each record contains:

```text
action_id
command
bucket
samples
mean_delta
n
confidence = n / (n + 2)
verdict_counts
dominant_verdict
```

The updater is idempotent by `sample_id`, so rerunning it on the same log
replaces the old sample rather than duplicating it.

## Existing Probe Migration

Input:

```text
artifacts/autopark_baseline/parking_probe_left_20260612.jsonl
```

Command:

```powershell
.venv\Scripts\python tools\parking_response_model_updater.py artifacts\autopark_baseline\parking_probe_left_20260612.jsonl --model configs\parking_action_response_model.json --library configs\parking_action_library.json
```

Generated v2 record:

```text
action_id = reverse_left_hard_6
command = ARC D=-6.0 STE=60 V=1
bucket = approach_entry / x_err_sign=+ / x_err_bin=0-40 / heading_bin=0-8
n = 1
confidence = 0.333
dominant_verdict = worsened
```

Measured delta:

```text
slot_y_dist_cm: -2.593
slot_x_err_px: +28.0
slot_entry_x_err_px: +28.0
slot_lateral_cm: -1.713
slot_heading_err_deg: 0.0
min_margin_px: -24.0
left_margin_px: -24.0
right_margin_px: +32.0
```

This matches the earlier manual conclusion:

```text
STE=60 worsened x error, lateral error, and line margin.
```

## Scorer Compatibility

`tools/parking_action_scorer.py` now supports v2 records:

1. exact same bucket -> `origin=measured`
2. same phase and x-error sign -> `origin=measured_neighbor`, confidence halved
3. action-only fallback -> `origin=measured_neighbor`, confidence quartered
4. no measured record -> action prior

Current scorer result on the latest dry-run state:

```text
top_action_counts = reverse_right_hard_6:5
latest_best = ARC D=-6.0 STE=120 V=1
origin = prior
confidence = 0.25
```

Full latest ranking:

```text
1. reverse_right_hard_6   ARC D=-6.0 STE=120 V=1   prior
2. reverse_right_soft_6   ARC D=-6.0 STE=105 V=1   prior
3. reverse_straight_6     MOVE D=-6.0 V=1          prior
4. reverse_left_soft_6    ARC D=-6.0 STE=75 V=1    prior
5. reverse_left_hard_6    ARC D=-6.0 STE=60 V=1    measured_neighbor, verdict=worsened
```

Artifact:

```text
artifacts/autopark_baseline/parking_action_scores_stage2_v2_20260612.json
```

## Conclusion

T2 is complete. The project now has a bucketed measured response model and a
tool to update it from one-step probe logs.

The next real calibration target remains:

```text
ARC D=-6.0 STE=120 V=1
```

After that probe, rerun `parking_response_model_updater.py` on the new log to
add the first `reverse_right_hard_6` measured record.
