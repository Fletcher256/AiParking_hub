# Autopark Reset Guide - 2026-06-12

## Purpose

`tools/parking_reset_guide.py` gives a numeric guide for manually resetting the
car to the same calibration start pose.

It compares the current no-motion YOLO state against the baseline window:

```text
slot_x_err_px ~= 70.621
slot_y_dist_cm ~= 48.068
slot_heading_err_deg ~= -0.913
phase_hint = approach_entry
```

This is a reset aid, not a motion controller.

## Offline Check

Compare an existing no-motion reset log:

```powershell
.venv\Scripts\python tools\parking_reset_guide.py `
  --current-log artifacts\autopark_baseline\parking_probe_reverse_right_hard_6_20260612_ste120_r2_reset.jsonl `
  --out artifacts\autopark_baseline\parking_reset_guide_r2_report.json
```

Observed r2 result:

```text
stable rows: current=12 target_min=10 [OK]
slot_x_err_px: current=15.481 target=70.621 delta=-55.14 [ADJUST]
slot_y_dist_cm: current=30.024 target=48.068 delta=-18.044 [ADJUST]
heading_deg: current=-1.453 target=-0.913 delta=-0.54 [OK]
phase: current=straighten_or_enter target=approach_entry
ready_for_t5_gate: NO
recommended_close: NO
```

Interpretation:

```text
change slot_x_err_px by +55.140 px
change slot_y_dist_cm by +18.044 cm
hold heading
```

The script intentionally reports numeric deltas. Physical left/right movement
depends on camera mounting and slot geometry, so the safe workflow is:

```text
adjust a little
run the guide again
keep deltas moving toward zero
```

## Live No-Motion Guide

Live mode runs the board controller in:

```text
--strategy action_replanner --replanner-dry-run
```

It does not open STM32 and does not send motion commands, but it does start a
board process and writes `/tmp` JSONL logs, so it still requires explicit
approval before running.

Command after approval:

```powershell
.venv\Scripts\python tools\parking_reset_guide.py `
  --execute `
  --allow-risk `
  --iterations 5 `
  --capture-sec 8 `
  --delay-sec 1
```

For a human-operated continuous loop, use `--iterations 0 --stop-when-ready`.
When running through an agent session, prefer a finite `--iterations` value so
the command cannot outlive the tool timeout.

```powershell
.venv\Scripts\python tools\parking_reset_guide.py `
  --execute `
  --allow-risk `
  --iterations 0 `
  --capture-sec 8 `
  --delay-sec 1 `
  --stop-when-ready
```

Useful output files:

```text
artifacts/autopark_baseline/parking_reset_guide_latest.json
artifacts/autopark_baseline/parking_reset_guide_history.jsonl
artifacts/autopark_baseline/parking_reset_guide_<stamp>_<iter>.jsonl
```

## Readiness

T5 may proceed only when:

```text
stable rows >= 10
abs(slot_x_err_px - 70.621) <= 5 px
abs(slot_heading_err_deg - (-0.913)) <= 1 deg
```

For better physical repeatability, also keep:

```text
abs(slot_y_dist_cm - 48.068) <= 5 cm
phase_hint = approach_entry
```

Do not relax these gates to force a sample into the response model. A response
sample is only useful if the reset pose is comparable to the baseline pose.

## First Live Guide Run

Command run after approval:

```powershell
.venv\Scripts\python tools\parking_reset_guide.py --execute --allow-risk --iterations 0 --capture-sec 4 --delay-sec 1 --stop-when-ready
```

The agent-side command timed out after about 3 minutes and was stopped. The
remaining local guide process was terminated, and the board was checked for
residual controller processes.

Result summary:

```text
iterations captured: 34
recommended_close_count: 0
will_execute_motion true: 0
send_to_stm32 true: 0
board_parking_controller residual after cleanup: none
```

Latest pose:

```text
slot_x_err_px: -25.378
slot_y_dist_cm: 28.623
slot_heading_err_deg: -0.931
phase_hint: align_in_corridor
```

Delta from target:

```text
slot_x_delta_px: -95.999
slot_y_dist_delta_cm: -19.445
heading_delta_deg: -0.018
```

Conclusion: heading is aligned, but the car is still too close to the slot and
far from the image-space lateral reset target. Continue coarse physical reset
before attempting T5 again.

## Second Live Guide Run

After another physical reset adjustment, a finite no-motion guide run was
started. The board controller exited with
`ABORT_BY_CRITERIA min_margin_below_floor`, so the guide downloaded the remote
log and analyzed it offline.

Result summary:

```text
will_execute_motion true: 0
send_to_stm32 true: 0
board_parking_controller residual after cleanup: none
```

Latest pose:

```text
slot_x_err_px: 130.260
slot_y_dist_cm: 42.767
slot_heading_err_deg: -1.102
phase_hint: approach_entry
min_margin_px: 19.91
```

Delta from target:

```text
slot_x_delta_px: +59.639
slot_y_dist_delta_cm: -5.301
heading_delta_deg: -0.189
```

Conclusion: distance and heading are now close to the reset target, but the
image-space lateral offset overshot. Reduce `slot_x_err_px` by about 60 px and
increase `slot_y_dist_cm` by about 5 cm before the next T5 attempt.

## YOLO Restart And Third Live Guide Run

A later reset-guide run produced only `vision_lost` events because no board YOLO
process was running and UDP `24580` had no parking detections. YOLO was restarted
with the NPU runtime library path:

```text
LD_LIBRARY_PATH=/opt/lib/npu:$LD_LIBRARY_PATH
PARKING_YOLO_UDP_HOST=127.0.0.1
PARKING_YOLO_UDP_PORT=24580
```

After restart, `/tmp/parking_yolo_rtsp_live.log` showed stable `Parking`
detections at about 0.84-0.87 confidence.

The next no-motion guide run reported:

```text
slot_x_err_px: 122.000
slot_y_dist_cm: 42.258
slot_heading_err_deg: 0.000
min_margin_px: 34.000
phase_hint: approach_entry
```

Delta from target:

```text
slot_x_delta_px: +51.379
slot_y_dist_delta_cm: -5.810
heading_delta_deg: +0.913
```

Result summary:

```text
YOLO process: running
board_parking_controller residual: none
will_execute_motion true: 0
send_to_stm32 true: 0
reason: min_margin_below_floor
```

Conclusion: the perception link is restored. Position is still not acceptable
for T5 because the lateral image-space offset is too large and the margin is at
the safety floor. Reduce `slot_x_err_px` by about 51 px and increase distance by
about 6 cm.

## Edge Recovery Safety Update

The previous safety gate treated `min_margin_px < 40` as an unconditional hard
stop. That was too blunt for the current pose, because the best recovery action
is predicted to increase the margin and move away from the line.

The controller now distinguishes:

```text
min_margin_px < 30      -> hard stop
30 <= min_margin < 40   -> edge recovery zone
min_margin >= 40        -> normal planning zone
```

In the edge recovery zone, `action_replanner` may only choose actions that:

```text
predicted min_margin_px >= 40
predicted margin gain >= 5 px
predicted |slot_x_err_px| decreases
predicted line_risk is false
```

For the latest current pose:

```text
current min_margin_px: 34.0
current slot_x_err_px: 122.0
dry-run recovery action: ARC D=-6.0 STE=120 V=1
predicted min_margin_px: 46.0
predicted slot_x_err_px: 94.0
```

The updated local report is:

```text
artifacts/autopark_baseline/parking_current_pose_planner_20260612_213144.json
```

Important: real `action_replanner` motion still blocks this action because it is
prior-only and has no exact measured response. Real movement from this pose must
be an explicitly approved one-step probe or must wait until a measured response
exists.
