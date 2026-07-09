# Autopark Stage 1 Observation - 2026-06-12

## Goal

Stage 1 implements the observation layer for the new architecture:

```text
YOLO slot polygon -> slot_relative_state
```

This stage does not solve control yet. Its purpose is to produce a stable,
auditable state that the future action-template replanner can score.

## Implemented Files

- `tools/board_parking_controller.py`
  - Added `slot_relative_state(info, args, stability=None)`.
  - Candidate JSONL events now include `slot_relative_state`.

- `tools/parking_slot_state_analyzer.py`
  - New offline analyzer.
  - Recomputes `slot_relative_state` from older logs that only contain
    `slot_polygon_px`.
  - Writes summary JSON and row CSV for stability inspection.

## State Schema

Top-level fields:

- `schema`
- `confidence`
- `stable_frames`
- `required_stable_frames`
- `pose_quality`
- `phase_hint`
- `image`
- `corridor`
- `ground_estimate`
- `gates`

Important planner-facing fields:

- `corridor.slot_x_err_px`
- `corridor.slot_entry_x_err_px`
- `corridor.left_margin_px`
- `corridor.right_margin_px`
- `corridor.min_margin_px`
- `corridor.line_risk`
- `image.slot_heading_err_deg`
- `image.closeness`
- `ground_estimate.slot_y_dist_cm`
- `ground_estimate.slot_lateral_cm`
- `gates.stable_enough`
- `gates.line_margin_ok`
- `gates.heading_ok`
- `gates.lateral_ok`

## Validation

Historical logs:

```text
artifacts/autopark_baseline/parking_probe_left_20260612.jsonl
artifacts/autopark_baseline/parking_corridor_servo_steering_instrumented_20260612.jsonl
```

Summary:

```text
candidate_rows = 10
state_rows = 10
stable_state_rows = 4
phase_counts = approach_entry:3, align_in_corridor:7
parse_errors = 0
```

New board dry-run:

```text
artifacts/autopark_baseline/parking_slot_state_dryrun_20260612.jsonl
artifacts/autopark_baseline/slot_state_dryrun_summary_20260612.json
artifacts/autopark_baseline/slot_state_dryrun_rows_20260612.csv
```

Dry-run summary:

```text
candidate_rows = 33
state_rows = 33
stable_state_rows = 31
phase_counts = approach_entry:33
line_risk_rows = 0
motion_candidate_rows = 0
```

Stable-state jitter in the current scene:

```text
slot_x_err_px: mean 76.313, stdev 0.542
slot_entry_x_err_px: mean 73.843, stdev 0.429
slot_heading_err_deg: mean -3.532, stdev 0.177
min_margin_px: mean 93.098, stdev 0.576
slot_y_dist_cm: mean 48.331, stdev 0.017
slot_lateral_cm: mean -3.947, stdev 0.052
pose_quality: mean 0.938, stdev 0.002
```

Conclusion:

```text
Stage 1 observation is implemented and stable enough for Stage 2 software work.
```

## Current Scene Interpretation

The current board dry-run scene is:

```text
phase_hint = approach_entry
slot_x_err_px ~= 76 px
slot_lateral_cm ~= -3.95 cm
min_margin_px ~= 93 px
slot_heading_err_deg ~= -3.5 deg
```

This means the vehicle/slot observation is stable, but not centered enough for
blind or fixed-sequence motion. It is a good input for action-template scoring.

## Next Stage

Stage 2 should implement the software side of the action-template library:

1. Define bounded actions.
2. Store measured response records.
3. Add an offline one-step scorer.
4. Replay candidate actions over `slot_relative_state` rows.
5. Only after dry-run scoring is sane, run more one-step real calibration.
