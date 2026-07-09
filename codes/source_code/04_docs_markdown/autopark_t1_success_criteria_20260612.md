# Autopark T1 Success Criteria - 2026-06-12

## Goal

Implement configurable parking success and abort gates before real motion
commands are sent.

This is T1 from `docs/autopark_codex_execution_plan_20260612.md`.

## Implemented Files

- `configs/parking_success_criteria.json`
- `tools/board_parking_controller.py`
- `tools/parking_success_criteria_check.py`

## Criteria

Done:

```json
{
  "slot_x_err_px_abs_max": 15,
  "slot_heading_err_deg_abs_max": 4.0,
  "slot_y_dist_cm_max": 10.0,
  "min_margin_px_min": 60,
  "required_stable_frames": 3
}
```

Abort:

```json
{
  "min_margin_px_floor": 40,
  "vision_lost_sec": 0.5,
  "max_total_cm": 60,
  "max_steps": 12,
  "divergence_x_err_px": 200
}
```

## Controller Behavior

The controller now loads:

```text
--success-criteria-json /opt/parking/autopark/parking_success_criteria.json
```

If a stable `slot_relative_state` meets done criteria:

```text
state = PARKED_BY_CRITERIA
cmd = STOP
verdict = parked
exit_code = 0
```

If a stable state trips abort criteria:

```text
state = ABORT_BY_CRITERIA
cmd = STOP
verdict = aborted
exit_code = 6
```

All candidate JSONL rows now include:

```text
parking_criteria
verdict
```

## Validation

Local self-test:

```text
done -> parked
continue -> continue
abort -> aborted
```

Artifact:

```text
artifacts/autopark_baseline/parking_success_criteria_check_20260612.json
```

Current board dry-run:

```text
artifacts/autopark_baseline/parking_success_criteria_dryrun_20260612.jsonl
```

Result:

```text
candidate_rows = 17
verdict_counts = {"continue": 17}
```

Board status after validation:

```text
/tmp/parking_armed absent
no board_parking_controller residual motion process
YOLO perception process still running
```

## Conclusion

T1 is complete. The controller has configurable success and abort gates, and
the current scene does not falsely satisfy them.
