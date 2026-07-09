# Autopark Status Report - 2026-06-12

## Goal

Implement board-side autonomous parking without computer participation during the final run, using the camera/YOLO/STM32 loop. Current work shifted from full-run attempts to measured multi-stage reverse parking.

## Verified

- Board SSH online: `192.168.137.2`, user `root`.
- VM SSH online: `192.168.137.100`, user `ebaina`.
- Board `/opt/parking/autopark` exists.
- Board `board_parking_controller.py` has been updated and passes `py_compile`.
- Board `parking_response_analyzer.py` and `autopark_multistage_plan.json` have been deployed.
- Board `/tmp/parking_armed` is absent, so parking motion is not armed by default.
- No persistent YOLO/ROS/parking process was observed during the health check.
- Latest static servo chain was previously verified by `PWM_STAT`; the latest real motion log also confirmed pre-steer PWM for `STE=69`.

## Key Finding

The latest real step executed:

```text
ARC D=-6.0 STE=69 V=1
```

Observed result:

```text
corridor_x_err_px: 119.91 -> 124.56
lat_cm: -6.51 -> -6.71
```

Offline response analysis:

```text
executed_motion_count = 1
servo_left_of_center = worsened
score_sum = -2
```

Conclusion: do not continue full parking with the current corridor controller. The next step must be steering-response calibration.

## Software Changes

- Updated `tools/board_parking_controller.py`.
  - `send_to_stm32` now means the candidate is expected to actually execute.
  - Added `motion_gate_open`, `cap_would_stop`, `lateral_would_stop`, and `will_execute_motion` fields.

- Added `tools/parking_response_analyzer.py`.
  - Pairs each executed STM32 command with pre/post visual candidates.
  - Scores whether the primitive improved or worsened the path metrics.

- Added `configs/autopark_multistage_plan.json`.
  - Defines safety gates, calibration primitives, and staged reverse parking logic.

- Added `docs/autopark_multistage_plan_20260612.md`.
  - Contains research-based control plan and staged parking strategy.

## Next Test Sequence

Run only one primitive per reset pose. Do not run full closed-loop parking yet.

### Probe 1: left arc

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 60 --allow-risk "/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --strategy primitive_probe --primitive-command 'ARC D=-6.0 STE=60 V=1' --primitive-max-command-abs-d-cm 8 --arm --target-wait-sec 1 --settle-sec 0.5 --move-read-sec 8 --stable-frames 3 --pixel-vision-lost-stop-sec 0.5 --max-motion-steps 1 --max-total-cm 8 --log-stm32-detail --pre-steer-settle-sec 0.5 --log-jsonl /tmp/parking_probe_left_20260612.jsonl"
```

### Probe 2: right arc

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 60 --allow-risk "/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --strategy primitive_probe --primitive-command 'ARC D=-6.0 STE=120 V=1' --primitive-max-command-abs-d-cm 8 --arm --target-wait-sec 1 --settle-sec 0.5 --move-read-sec 8 --stable-frames 3 --pixel-vision-lost-stop-sec 0.5 --max-motion-steps 1 --max-total-cm 8 --log-stm32-detail --pre-steer-settle-sec 0.5 --log-jsonl /tmp/parking_probe_right_20260612.jsonl"
```

### Analyze

```powershell
.venv\Scripts\python tools\parking_response_analyzer.py artifacts\autopark_baseline\parking_probe_left_20260612.jsonl artifacts\autopark_baseline\parking_probe_right_20260612.jsonl --out artifacts\autopark_baseline\parking_probe_compare_20260612.json
```

Only the steering side that improves error and preserves line margin should be promoted to 12 cm, then later 20 cm.

## Probe Result: STE=60, 6 cm

Executed on 2026-06-12:

```text
ARC D=-6.0 STE=60 V=1
```

STM32 evidence:

```text
pre-steer PWM: ANG=60.0 PULSE=1333 CCR2=1333
motion: ACK/DONE ARC
final: MODE=IDLE RUN=STANDBY ANG=90.0
```

Visual response:

```text
lon_cm: 34.11 -> 31.70
lat_cm: -0.01 -> -1.68
corridor_x_err_px: 18.0 -> 46.0
corridor_min_margin_px: 186.0 -> 162.0
```

Verdict:

```text
STE=60 worsened corridor error, lateral error, and line margin.
Do not use STE=60 as the entry arc direction from this pose.
Next calibration should reset to the same initial pose and test STE=120 for 6 cm.
```
