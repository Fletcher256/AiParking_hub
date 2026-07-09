# C2 Steering Response Model - 2026-06-13

## Purpose

Convert the one-step steering calibration runs into the planner response model.
This is software-only after the real single-step samples were collected.

## Inputs

```text
artifacts/autopark_baseline/c2_arc_calib_ste120_20260613.json
artifacts/autopark_baseline/c2_arc_calib_ste120_repeat_20260613.json
artifacts/autopark_baseline/c2_arc_calib_ste105_repeat_20260613.json
artifacts/autopark_baseline/c2_arc_calib_ste75_20260613.json
artifacts/autopark_baseline/c2_arc_calib_ste60_20260613.json
artifacts/autopark_baseline/c2_steering_response_summary_20260613.json
artifacts/autopark_baseline/c2_steering_response_summary_20260613.csv
```

## Clean Samples

```text
STE=120: right strong arc, TLM R_eff about 86-90cm, STAT R_eff about 97-104cm
STE=105: right weak arc, STAT R_eff about 260cm
STE=75:  left medium arc, STAT R_eff about 147cm
STE=60:  left strong arc, STAT R_eff about 79cm
```

The steering response is nonlinear. STE=105 is much weaker than STE=120, and
STE=60 is much stronger than STE=75.

## Response Model Update

Generated combined logs so the existing updater could reuse the same response
model logic:

```text
artifacts/autopark_baseline/parking_arc_calib_ste105_combined_20260613.jsonl
artifacts/autopark_baseline/parking_arc_calib_ste75_combined_20260613.jsonl
artifacts/autopark_baseline/parking_arc_calib_ste60_combined_20260613.jsonl
```

Updated:

```text
configs/parking_action_response_model.json
configs/parking_action_library.json
```

New measured bucket records:

```text
reverse_right_soft_6 / STE=105:
  bucket: straighten_or_enter, x_err +, 0-40px, heading -8-0
  verdict: worsened from this pose

reverse_left_soft_6 / STE=75:
  bucket: align_in_corridor, x_err -, 0-40px, heading 0-8
  verdict: worsened from this pose

reverse_left_hard_6 / STE=60:
  bucket: align_in_corridor, x_err -, 40-120px, heading 0-8
  verdict: improved from this pose
```

Important: a steering action is not globally good or bad. It depends on the
state bucket. The planner must prefer exact bucket matches, then cautious
neighbors, and avoid treating steering as a simple linear mapping.

## Verification

JSON validation:

```powershell
.venv\Scripts\python -m json.tool configs\parking_action_library.json
.venv\Scripts\python -m json.tool configs\parking_action_response_model.json
```

T4 replay after C2 update:

```text
Report: artifacts/autopark_baseline/parking_replay_planner_after_c2_final_20260613.json
CSV:    artifacts/autopark_baseline/parking_replay_planner_after_c2_final_20260613.csv

state_rows: 33
stable_actionable_rows: 31
stable_top_action_counts: reverse_right_soft_6 = 31
action_switch_count_stable: 0
direction_review_pass: true
acceptance_pass: true
```

Latest real-pose dry-run score after STE=60:

```text
Input: artifacts/autopark_baseline/parking_arc_calib_ste60_post_dryrun_20260613.jsonl
Best action: reverse_straight_6 / MOVE D=-6.0 V=1
Reason: current state is near center and phase is straighten_or_enter.
```

## Next Step

Deploy these updated config files to the board, then run a no-motion
`action_replanner` dry-run against live YOLO. If the live ranking is stable and
the first planned command is reasonable, run one confirmed real action.
