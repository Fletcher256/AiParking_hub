# Autonomous Parking Current Status - 2026-06-11

## Summary

The project is ready for non-motion board-only dry-run work. It is not yet
cleared for autonomous real motion.

Current verified state:

- Board SSH works at `root@192.168.137.2`.
- VM SSH works at `ebaina@192.168.137.100`; VM also has `192.168.247.129`.
- Board YOLO process is running as `sample_parking_yolo_rtsp` with PID `2026`.
- Camera RTSP capture succeeded from `rtsp://192.168.137.2:554/live0`.
- Latest captured frame:
  `artifacts/autopark_baseline/rtsp_frame_20260611_1818.jpg`.
- STM32 safety commands passed:
  - `PING` -> `DONE ... PING PONG`
  - `VER` -> `FW=SS928-CTRL-2.0 BAUD=9600 PROTO=2`
  - `STAT` -> `MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0 ... DROP=0`
  - `STOP` -> `DONE ... STOP`
- VM ROS package `parking_bridge` is installed, but no business ROS nodes are
  currently running. Topic list is only `/parameter_events` and `/rosout`.
- No board-side motion/control process was found. The only relevant active
  board process is YOLO perception.

## Verified Links

### Camera + YOLO

Board-side YOLO log showed both positive detections and later no-target frames:

```text
Parking 92.8%-94.3%
parking_yolo_live_infer ... count=1
...
parking_yolo_live_infer ... count=0
```

The latest dry-run interval had no detected target, so the controller correctly
stayed in no-target wait/stop diagnostics.

### STM32

STM32 serial communication is functional for non-motion safety commands through
the board CH340/CH341 userspace initialization path.

Current safety status from `STAT`:

```text
MODE=IDLE RUN=STANDBY DIR=1 SPD=0 ANG=90.0 VEL=0.0 DROP=0
```

No `MOVE` or `ARC` command was sent in this work.

### Board-Only Dry-Run

Updated controller:

```text
tools/board_parking_controller.py
```

Dry-run command used on the board:

```sh
/usr/local/bin/python3 /tmp/board_parking_controller.py \
  --dry-run \
  --duration-sec 30 \
  --target-wait-sec 2 \
  --settle-sec 0.2 \
  --log-jsonl /tmp/parking_dry_run_20260611.jsonl \
  --strategy template
```

Local artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_20260611.jsonl
artifacts/autopark_baseline/parking_dry_run_summary_20260611.json
artifacts/autopark_baseline/parking_dry_run_curve_20260611.csv
```

Dry-run summary:

```text
total_events=15
candidate_events=0
vision_lost_events=14
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

This proves the no-target safety behavior for the current scene. It does not
yet prove stable target tracking because the current camera scene had no target
during the dry-run window.

## Safety Gates Verified

- `board_parking_controller.py` without `--dry-run` and without arm file refuses
  to run motion.
- `stm32_send.py --cmd "MOVE D=-5 V=1"` without `--allow-motion` does not send
  the command and prints an explicit motion warning.
- `stm32_send.py --cmd "ARC D=-5 STE=200 V=1"` rejects the invalid servo value
  before hardware access.
- Dry-run JSONL events have:
  - `send_to_stm32=false`
  - `motion_enabled=false`
  - `actuator_control_allowed=false`

## Current Code Changes

Updated:

- `tools/board_parking_controller.py`

Added:

- `tools/parking_dry_run_analyze.py`
- `tools/parking_model_regression_compare.py`

The updated controller now supports:

- multi-frame stability filter
- entrance/axis yaw stability checks
- template-based small-step decisions
- bounded dry-run capture via `--duration-sec`
- structured JSONL events
- no-target wait behavior during bounded dry-run
- explicit dry-run safety fields
- configurable thresholds

## Remaining Gaps

- Need a scene where YOLO currently detects the parking slot during dry-run to
  verify stable candidate generation.
- Real vehicle motion has not been run in this work.
- `MOVE/ARC` direction, actual distance, steering sign, and turn radius still
  require physical single-step tests.
- Camera homography should be revalidated after any mount movement.
- YOLO model update should be regression-tested against baseline dry-run logs
  before enabling automatic motion.

## Continued Dry-Run - 2026-06-11 18:28

After user approval to continue, a second bounded board-only dry-run was run for
60 seconds using the persistent controller:

```sh
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --dry-run \
  --duration-sec 60 \
  --target-wait-sec 2 \
  --settle-sec 0.2 \
  --log-jsonl /tmp/parking_dry_run_continue_20260611.jsonl \
  --strategy template
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_continue_20260611.jsonl
artifacts/autopark_baseline/parking_dry_run_continue_summary_20260611.json
artifacts/autopark_baseline/parking_dry_run_continue_curve_20260611.csv
artifacts/autopark_baseline/rtsp_frame_20260611_1829.jpg
```

Result:

```text
total_events=28
candidate_events=0
vision_lost_events=27
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Interpretation:

- The no-target safety behavior is confirmed over a full 60 second dry-run.
- The current RTSP frame does not contain a clear parking-slot target, matching
  the YOLO log stream of `parking_yolo_live_infer ... count=0`.
- Candidate `MOVE/ARC` stability still needs a scene where the current model
  detects the parking slot.

## Detected-Target Dry-Run - 2026-06-11 18:45

After the camera/vehicle angle was adjusted, YOLO started detecting the parking
slot again at about 75%-77% confidence. A full 60 second board-only dry-run was
then run with the persistent controller:

```sh
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --dry-run \
  --duration-sec 60 \
  --target-wait-sec 1 \
  --settle-sec 0.2 \
  --log-jsonl /tmp/parking_dry_run_detected_full_20260611.jsonl \
  --strategy template
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_detected_full_20260611.jsonl
artifacts/autopark_baseline/parking_dry_run_detected_full_summary_20260611.json
artifacts/autopark_baseline/parking_dry_run_detected_full_curve_20260611.csv
artifacts/autopark_baseline/rtsp_frame_detected_20260611_1846.jpg
```

Result:

```text
total_events=193
candidate_events=192
stable_candidate_events=188
unstable_candidate_events=4
vision_lost_events=0
command_family_flips=0
state=FINAL_REVERSE for all candidates
top_command="MOVE D=-7.0 V=1" count=188 stable events
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Measured dry-run stability:

```text
confidence mean=0.7679 std=0.0039 range=0.7533..0.7764
lon_cm mean=39.9449 std=0.032 range=39.87..40.03
lat_cm mean=-2.6216 std=0.1133 range=-2.84..-2.23
axis_yaw_deg mean=1.1752 std=0.2107 range=0.62..1.73
slot_center_x_cm mean=28.9926 std=0.0244
slot_center_y_cm mean=-2.0274 std=0.052
```

Interpretation:

- Current angle is good enough for stable model output.
- The no-motion board-only chain is now proven from camera + board YOLO into
  the standalone controller candidate stage.
- The template controller selected a straight reverse candidate because lateral
  error was below the 3 cm template threshold and heading error was small.
- No real movement command was sent.
- This is the first useful baseline for later YOLO model regression.

## First Real Single-Step Motion - 2026-06-11 19:12

After a short pre-motion dry-run, the controller output was stable but changed
from straight reverse to a lateral alignment template:

```text
pre-motion top_command="ARC D=-7.0 STE=80 V=1"
pre-motion confidence mean=0.9445
pre-motion lon_cm mean=42.5568
pre-motion lat_cm mean=-5.85
pre-motion head_deg mean=-0.3905
```

With explicit operator approval, one reduced-distance real command was sent:

```text
ARC D=-5 STE=80 V=1
```

STM32 returned:

```text
ACK 6729 ARC
DONE 6729 ARC
```

Immediate stop/status check:

```text
DONE 6760 STOP
STAT 6762 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-83.4 X=0.0 Y=-4.0 D=4.0 VEL=0.0 DROP=0
```

Post-motion board-only dry-run:

```text
post-motion top_command="ARC D=-7.0 STE=80 V=1"
post-motion confidence mean=0.9056
post-motion lon_cm mean=36.5408
post-motion lat_cm mean=-7.3656
post-motion head_deg mean=2.956
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_pre_move_20260611_1908.jsonl
artifacts/autopark_baseline/parking_dry_run_pre_move_20260611_1908_summary.json
artifacts/autopark_baseline/parking_dry_run_pre_move_20260611_1908_curve.csv
artifacts/autopark_baseline/parking_dry_run_after_arc_20260611_1912.jsonl
artifacts/autopark_baseline/parking_dry_run_after_arc_20260611_1912_summary.json
artifacts/autopark_baseline/parking_dry_run_after_arc_20260611_1912_curve.csv
```

Interpretation:

- The real STM32 motion chain is confirmed for one low-speed, short-distance
  ARC command.
- The vehicle stopped and reported `IDLE/STANDBY` after the command.
- The longitudinal target distance decreased, which matches reverse motion.
- The lateral error magnitude increased from about 5.9 cm to about 7.4 cm, so
  the current steering/lateral correction sign must be verified before
  repeating the same ARC direction.
- Do not continue same-direction ARC blindly; the next safe test is a reduced
  opposite-steer probe or a steering sign calibration step.

## Opposite-Steer Probe - 2026-06-11 19:15

With explicit operator approval, a smaller opposite-steer command was sent to
check the steering/lateral sign:

```text
ARC D=-3 STE=100 V=1
```

STM32 returned:

```text
ACK 7009 ARC
DONE 7009 ARC
```

Immediate stop/status check:

```text
DONE 7032 STOP
STAT 7033 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-91.2 X=0.0 Y=-1.1 D=1.2 VEL=0.0 DROP=0
```

Post-probe dry-run summary:

```text
top_command="ARC D=-7.0 STE=80 V=1"
confidence mean=0.9063
lon_cm mean=35.912
lat_cm mean=-6.9812
head_deg mean=0.6916
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_after_ste100_20260611_1915.jsonl
artifacts/autopark_baseline/parking_dry_run_after_ste100_20260611_1915_summary.json
artifacts/autopark_baseline/parking_dry_run_after_ste100_20260611_1915_curve.csv
```

Interpretation:

- The vehicle again stopped correctly and reported `IDLE/STANDBY`.
- Compared with the previous post-motion dry-run, lateral error improved from
  about `-7.37 cm` to about `-6.98 cm`.
- The improvement is small, but it suggests `STE=100` is the better correction
  direction for the current negative lateral error.
- The controller still outputs `STE=80`, so the lateral steering template sign
  should be corrected in software before continuing autonomous or repeated ARC
  tests.

## Lateral Template Sign Fix - 2026-06-11 19:18

The lateral steering template in `tools/board_parking_controller.py` was updated
so negative lateral error now maps to servo greater than center. The corrected
file was deployed to:

```text
/opt/parking/autopark/board_parking_controller.py
```

Post-fix dry-run summary:

```text
top_command="ARC D=-7.0 STE=100 V=1"
candidate_events=25
stable_candidate_events=22
vision_lost_events=0
command_family_flips=0
confidence mean=0.9153
lon_cm mean=35.76
lat_cm mean=-6.73
head_deg mean=-0.15
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_after_sign_fix_20260611_1918.jsonl
artifacts/autopark_baseline/parking_dry_run_after_sign_fix_20260611_1918_summary.json
artifacts/autopark_baseline/parking_dry_run_after_sign_fix_20260611_1918_curve.csv
```

Final safety check after the fix:

```text
running board processes: sample_parking_yolo_rtsp only; no board_parking_controller residual
STAT 7220 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-96.9 X=0.0 Y=-1.1 D=1.2 VEL=0.0 DROP=0
```

Interpretation:

- The software candidate now matches the measured better steering direction.
- The vehicle remains stopped after the probe and fix.
- The next real-motion step, if approved, should use a small corrected command
  such as `ARC D=-3 STE=100 V=1`, followed by immediate `STOP/STAT` and
  post-motion dry-run comparison.

## Second Corrected-Steer Probe - 2026-06-11 19:22

With explicit operator approval, a second corrected-steer probe was sent:

```text
ARC D=-3 STE=100 V=1
```

STM32 returned:

```text
ACK 7561 ARC
DONE 7561 ARC
```

Immediate stop/status check:

```text
DONE 7587 STOP
STAT 7589 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-107.5 X=0.0 Y=-1.1 D=1.1 VEL=0.0 DROP=0
```

Post-motion dry-run summary:

```text
top_command="ARC D=-7.0 STE=100 V=1"
candidate_events=25
stable_candidate_events=22
vision_lost_events=0
command_family_flips=0
confidence mean=0.9214
lon_cm mean=35.7284
lat_cm mean=-7.2708
head_deg mean=2.2876
motion_events=0
actuator_allowed_events=0
send_to_stm32_events=0
```

Artifacts:

```text
artifacts/autopark_baseline/parking_dry_run_after_ste100_second_20260611_1922.jsonl
artifacts/autopark_baseline/parking_dry_run_after_ste100_second_20260611_1922_summary.json
artifacts/autopark_baseline/parking_dry_run_after_ste100_second_20260611_1922_curve.csv
```

Final safety check:

```text
running board processes: sample_parking_yolo_rtsp only; no board_parking_controller residual
STAT 7660 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-109.6 X=0.0 Y=-1.1 D=1.1 VEL=0.0 DROP=0
```

Interpretation:

- The second corrected probe did not produce clear lateral convergence.
- Mean lateral error worsened from about `-6.73 cm` after the sign-fix dry-run
  to about `-7.27 cm` after the second `STE=100` motion.
- Continued repeated ARC motion is not recommended until the motion-to-vision
  response is calibrated more explicitly.
- The next safe engineering step is to add a calibration/test mode that sends
  very small probe moves and compares pre/post visual deltas, instead of using
  the parking template as the motion decision source.

## Feedback Tune Mode - 2026-06-11 20:23

A bounded feedback tuning mode was added to
`tools/board_parking_controller.py` and deployed to:

```text
/opt/parking/autopark/board_parking_controller.py
```

Purpose:

- Run repeated small reverse steps instead of manual one-command testing.
- Compare stable pre/post vision after each step.
- Accept manual feedback through `/tmp/parking_feedback` using `+`, `-`, `0`,
  or `q`.
- Optionally use visual deltas as automatic feedback.
- Update step size, steering magnitude, and lateral sign after each reward.

Safety limits implemented:

```text
--feedback-max-command-abs-d-cm default=3.0
--feedback-max-step-cm default=3.0
--feedback-max-total-cm default=18.0
per-step STOP after every real movement
requires --arm and /tmp/parking_armed for any real motion
dry-run never sends motion
```

Dry-run validation:

```text
command:
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --feedback-tune --dry-run --feedback-episodes 1 --feedback-auto \
  --feedback-step-cm 2 --feedback-max-command-abs-d-cm 3

candidate_cmd="ARC D=-3.0 STE=100 V=1"
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

Final safety check:

```text
running board processes: sample_parking_yolo_rtsp only; no board_parking_controller residual
STAT 9604 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-160.9 X=0.0 Y=-1.2 D=1.3 VEL=0.0 DROP=0
```

Interpretation:

- The requested "positive/negative feedback adjusts parameters" mechanism now
  exists in software.
- It has been deployed and dry-run tested without motion.
- Real feedback tuning should start with capped `D<=3 cm`, a small episode
  count, and operator feedback enabled.

## Keyboard Policy Learning - 2026-06-11 20:40

The feedback concept was upgraded from parameter tuning to a persistent
state-action policy learner.

Files changed:

```text
tools/board_parking_controller.py
tools/parking_keyboard_policy_trainer.py
docs/parking_keyboard_policy_training_20260611.md
```

Board deployment:

```text
/opt/parking/autopark/board_parking_controller.py
```

New board mode:

```text
--learn-policy
```

State key:

```text
lon_bucket|lat_bucket|head_bucket
example: far|right_large|yaw_pos_small
```

Original default action set:

```text
MOVE D=-3.0 V=1
ARC D=-3.0 STE=70 V=1
ARC D=-3.0 STE=80 V=1
ARC D=-3.0 STE=90 V=1
ARC D=-3.0 STE=100 V=1
ARC D=-3.0 STE=110 V=1
```

Learning:

```text
right arrow => reward +1
left arrow  => reward -1
space       => restart rollout
0           => neutral reward
q           => quit
Q <- Q + alpha * (reward - Q)
```

Persistent policy path:

```text
/opt/parking/autopark/parking_policy.json
```

Windows keyboard trainer:

```text
tools/parking_keyboard_policy_trainer.py
```

Dry-run verification:

```text
actions=6
example candidate: ARC D=-3.0 STE=90 V=1
policy update saved to /tmp/parking_policy_dryrun2.json
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

Real training command template:

```powershell
.venv\Scripts\python tools\parking_keyboard_policy_trainer.py --allow-motion --create-arm-file --episodes 80 --max-total-cm 18 --max-abs-d-cm 3
```

## Keyboard Policy Learning Update - 2026-06-11 20:52

Training was updated per operator preference:

```text
default session duration: infinite until q
space: start a new rollout, reset rollout distance and negative streak
0: neutral feedback
default command distance: D=-7.0
default action count: 10
default per-rollout total cap: 70 cm, then hold for SPACE/q
```

Expanded default action set:

```text
MOVE D=-7.0 V=1
ARC D=-7.0 STE=50 V=1
ARC D=-7.0 STE=60 V=1
ARC D=-7.0 STE=70 V=1
ARC D=-7.0 STE=80 V=1
ARC D=-7.0 STE=90 V=1
ARC D=-7.0 STE=100 V=1
ARC D=-7.0 STE=110 V=1
ARC D=-7.0 STE=120 V=1
ARC D=-7.0 STE=130 V=1
```

Real-motion trainer also installs a shell trap to remove `/tmp/parking_armed`
when the remote learner exits.

Dry-run verification:

```text
actions=10
example candidate: ARC D=-7.0 STE=120 V=1
policy update saved to /tmp/parking_policy_dryrun_7cm.json
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

Updated real training command:

```powershell
.venv\Scripts\python tools\parking_keyboard_policy_trainer.py --allow-motion --create-arm-file --max-total-cm 70 --max-abs-d-cm 7
```

## Pixel-Servo Controller - 2026-06-11 21:22

A direct pixel-space controller was added to
`tools/board_parking_controller.py`:

```text
--strategy pixel_servo
```

It uses YOLO image geometry directly:

```text
cx = parking-slot center x
x_err = cx - 320
axis_angle_px_deg = pixel approach-axis angle
bbox_h / center_y = near-stop references
```

Ground coordinates are still logged, but do not drive the `pixel_servo`
decision.

Dry-run before real motion:

```text
state=PIXEL_ALIGN_X
cx ~= 422 px
x_err ~= +103 px
angle_err ~= +2.3 deg
candidate_cmd="ARC D=-7.0 STE=102 V=1"
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

The stop condition was made conservative after an early dry-run showed that
`entrance_y` alone could trigger premature `STOP`. Current stop requires:

```text
center_y >= 560
bbox_h >= 420
abs(x_err) <= 18
abs(angle_err) <= 5
```

## Pixel-Servo Real Probe - 2026-06-11 21:23

With explicit approval, one real pixel-servo probe was sent:

```text
ARC D=-20 STE=102 V=1
```

STM32 returned:

```text
ACK 4103 ARC
DONE 4103 ARC
DONE 4128 STOP
STAT 4130 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0 YAW=-39.5 X=0.7 Y=-18.6 D=18.6 VEL=0.0 DROP=0
```

Post-motion pixel-servo dry-run:

```text
state=PIXEL_ALIGN_X
cx ~= 407 px
x_err ~= +87 px
angle_err ~= 0 deg
candidate_cmd="ARC D=-7.0 STE=102 V=1"
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

Interpretation:

- The probe moved the vehicle about 18.6 cm per STM32.
- Longitudinal distance decreased from about 42.5 cm to about 31.1 cm.
- Pixel x error improved from about +103 px to about +87 px, so the selected
  steering direction is correct but weak.
- Continuing in the same correction direction is reasonable, but the next
  probe should use a stronger servo value than 102 if there is enough side
  clearance.

## Pixel Binding Control - 2026-06-11 21:35

The pixel-servo controller was changed from fixed steering to a direct binding
function:

```text
steer_offset = pixel_kx * x_err + pixel_ka * angle_err
servo = clamp(90 + steer_offset, 45, 135)
```

Default coefficients:

```text
pixel_kx = 0.14 servo-deg / px
pixel_ka = 0.35 servo-deg / pixel-angle-deg
max steer offset = 24 deg
```

Distance and speed binding:

```text
if near or centered: D = -10 cm
elif large steering demand or large x error: D = -20 cm
else: D = -40 cm
V = 1 by default
```

The function logs its intermediate calculation under `binding`:

```json
{
  "raw_steer_offset": 9.656,
  "steer_offset": 10.0,
  "servo": 100,
  "distance_cm": 20.0,
  "distance_reason": "large_steer_or_x_error",
  "gear": 1
}
```

Dry-run verification after deployment:

```text
strategy=pixel_servo
cx ~= 390.5 px
x_err ~= +70.5 px
angle_err ~= -0.6 deg
candidate_cmd="ARC D=-20.0 STE=100 V=1"
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```

## Pixel Closed-Loop Run - 2026-06-11 22:10

Safety behavior used for this run:

```text
YOLO target lost -> wait
YOLO target continuously lost for 2.0 s -> STOP
```

This avoids stopping on a single missed detection, while still forcing a stop
when the slot remains invisible.

Executed full run:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy pixel_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --move-read-sec 8 \
  --pixel-vision-lost-stop-sec 2 \
  --log-jsonl /tmp/parking_pixel_servo_fullrun_20260611.jsonl
```

Observed sequence:

```text
step 1: ARC D=-20.0 STE=100 V=1
step 2: ARC D=-40.0 STE=98 V=1
then: YOLO target lost
after continuous loss > 2 s: STOP
```

Post-run safety state:

```text
STOP returned DONE
STM32 MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0
/tmp/parking_armed absent
no board_parking_controller process remains
YOLO process remains running
```

Controller log summary:

```text
log file: /tmp/parking_pixel_servo_fullrun_20260611.jsonl
total commanded pixel-servo distance: 60 cm
last visible binding:
  x_err ~= +58 px
  servo = 98
  D = -40 cm
  reason = far_mild_steer
```

Interpretation:

- The 2-second target-loss stop rule worked.
- The controller completed two closed-loop reverse actions and exited safely.
- The second action may be too long near the end of the maneuver, because the
  last visible detection was already close to the slot. Physical inspection is
  required to decide whether YOLO loss means "fully inside the slot" or "slot
  left the camera view too early."
- If the car overshot or left the intended line, reduce the near-slot distance
  binding so high closeness uses 10-20 cm instead of 40 cm.

## Current Pixel Vision-Lost Stop Rule - 2026-06-11 22:47

The default pixel-servo target-loss threshold was changed from 2.0 s to 0.5 s:

```text
--pixel-vision-lost-stop-sec default = 0.5
```

Board-side verification:

```text
/opt/parking/autopark/board_parking_controller.py
ap.add_argument("--pixel-vision-lost-stop-sec", type=float, default=0.5)
```

This means future pixel-servo runs stop after the parking slot is continuously
missing for 0.5 s, unless the command explicitly overrides the parameter.

## Pixel Closed-Loop Run With 0.5 s Vision-Lost Stop - 2026-06-11 22:52

Executed full run:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy pixel_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --move-read-sec 8 \
  --pixel-vision-lost-stop-sec 0.5 \
  --log-jsonl /tmp/parking_pixel_servo_fullrun_20260611_05s.jsonl
```

Observed sequence:

```text
initial: lon=45.4 lat=-3.8 head=-0.1
step 1: ARC D=-20.0 STE=101 V=1
after step 1: lon=31.5 lat=-4.5 head=-0.2
step 2: ARC D=-20.0 STE=103 V=1
then: YOLO target lost
after continuous loss >= 0.5 s: STOP=PIXEL_VISION_LOST
```

Post-run checks:

```text
/tmp/parking_armed absent
no board_parking_controller process remains
no stm32_stop_stat_once process remains
YOLO process remains running
/dev/ttyUSB0 exists
STM32_SAFE_QUERY=PASS
STAT MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0 YAW=-4.9 X=-0.0 Y=-0.7 D=0.8 VEL=0.0 DROP=0
```

Interpretation:

- The 0.5 s target-loss stop rule worked.
- The run completed two 20 cm reverse commands and stopped safely.
- Physical inspection is still required to decide whether target loss
  corresponds to successful full entry into the slot or premature loss of the
  parking-slot mask.

## Pixel Closed-Loop Rerun With 0.5 s Vision-Lost Stop - 2026-06-11 23:00

Executed rerun:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy pixel_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --move-read-sec 8 \
  --pixel-vision-lost-stop-sec 0.5 \
  --log-jsonl /tmp/parking_pixel_servo_fullrun_20260611_rerun.jsonl
```

Observed sequence:

```text
initial: lon=38.1 lat=-5.3 head=0.8
step 1: ARC D=-20.0 STE=103 V=1
after step 1: lon=27.6 lat=-5.1 head=-0.1
step 2: ARC D=-10.0 STE=104 V=1
after step 2: lon=20.4 lat=-4.8 head=-0.1
step 3: ARC D=-10.0 STE=103 V=1
then: YOLO target lost
after continuous loss >= 0.5 s: STOP=PIXEL_VISION_LOST
```

Post-run checks:

```text
/tmp/parking_armed absent
no board_parking_controller process remains
no stm32_stop_stat_once process remains
YOLO process remains running
/dev/ttyUSB0 exists
STM32_SAFE_QUERY=PASS
STAT MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0 YAW=-17.3 X=0.1 Y=-8.2 D=8.2 VEL=0.0 DROP=0
```

Interpretation:

- The controller repeated the safe stop behavior.
- The binding chose shorter 10 cm steps near the slot, which is safer than the
  earlier 40 cm second step.
- The final visible detection had low-to-moderate confidence, so the end
  condition still depends on physical inspection of the car position.

## Parking Failure Analysis And Blind-Finish Fix - 2026-06-11 23:10

Observed failure mode:

```text
last stable visible state:
  lon ~= 20.4 cm
  lat ~= -4.8 cm
  x_err ~= +96 px
  servo ~= 103
  command = ARC D=-10.0 STE=103 V=1
then:
  YOLO target lost
  controller stopped after 0.5 s
```

Interpretation:

- The vehicle is still roughly 10-20 cm short when the parking slot leaves the
  camera view.
- Treating YOLO loss as immediate terminal success stops the car too early.
- The safer fix is not continuous velocity control yet; it is one capped
  blind-finish action after a near-slot stable detection.

Implemented locally in `tools/board_parking_controller.py`:

```text
--pixel-blind-finish-cm
--pixel-blind-finish-max-lon-cm
--pixel-blind-finish-min-steps
--pixel-blind-finish-max-steer-offset-deg
```

Default behavior remains unchanged because `--pixel-blind-finish-cm` defaults
to `0.0`.

Recommended next test command should explicitly enable:

```text
--pixel-blind-finish-cm 10
--pixel-blind-finish-max-lon-cm 25
--pixel-blind-finish-min-steps 2
--pixel-blind-finish-max-steer-offset-deg 18
```

Expected behavior in the previous failure case:

```text
YOLO lost after near stable state
-> one final ARC D=-10 STE=<last_safe_servo> V=1
-> STOP
```

## Corridor Servo Implementation Status - 2026-06-11

Goal:

```text
Replace pure center/bbox pixel control with a YOLO polygon corridor strategy
that tracks the slot left/right side lines and stops before line-pressure risk.
No real-car motion was executed during this implementation pass.
```

Implemented locally:

```text
tools/board_parking_controller.py
  - slot_pixel_geometry now extracts:
    - entrance_edge_px
    - back_edge_px
    - left_edge_px
    - right_edge_px
    - corridor_sample_px
  - new corridor_metrics()
  - new corridor_servo_command()
  - new strategy: --strategy corridor_servo
  - new states:
    - APPROACH
    - ALIGN_CORRIDOR
    - ENTER_SLOT
    - FINAL_STOP
    - LINE_RISK_LEFT / LINE_RISK_RIGHT
  - new parameterized CLI:
    - --corridor-sample-y
    - --corridor-entry-y
    - --corridor-x-tolerance-px
    - --corridor-min-line-margin-px
    - --corridor-line-risk-min-closeness
    - --corridor-final-stop-closeness
    - --corridor-approach-closeness
    - --corridor-kx
    - --corridor-near-kx
    - --corridor-ka
    - --corridor-approach-d-cm
    - --corridor-align-d-cm
    - --corridor-enter-d-cm
    - --corridor-min-command-abs-d-cm
    - --corridor-approach-max-steer-offset-deg
    - --corridor-align-max-steer-offset-deg
    - --corridor-enter-max-steer-offset-deg
  - candidate logs now preserve:
    - slot_polygon_px
    - slot_edges_px
    - corridor metrics
    - binding output

tools/parking_corridor_replay.py
  - audits historical candidate JSONL logs
  - replays rows that contain raw YOLO detections or slot_polygon_px
  - reports evidence gaps for old logs that did not preserve polygons
```

Control interpretation:

```text
APPROACH:
  use the side-line corridor center while the slot is still far enough away

ALIGN_CORRIDOR:
  use stronger steering and shorter movement when corridor center or angle is off

ENTER_SLOT:
  when corridor center and slot angle are aligned, reverse a short straight step

FINAL_STOP:
  when close enough and aligned, stop instead of issuing another reverse step

LINE_RISK_LEFT / LINE_RISK_RIGHT:
  if the target x is too close to either side line near the slot, stop early
```

Local verification:

```text
.venv\Scripts\python -m py_compile tools\board_parking_controller.py tools\parking_corridor_replay.py
PASS

.venv\Scripts\python tools\board_parking_controller.py \
  --strategy corridor_servo \
  --dry-run \
  --duration-sec 2 \
  --target-wait-sec 0.2 \
  --settle-sec 0.1 \
  --log-jsonl artifacts\autopark_baseline\corridor_local_no_motion_dryrun.jsonl

Result:
  dry_run=True
  no STM32 serial opened
  STOP=NO_TARGET repeated
  STOP=DURATION elapsed
```

Offline replay verification:

```text
.venv\Scripts\python tools\parking_corridor_replay.py \
  artifacts\autopark_baseline\corridor_synthetic_polygon_log.jsonl \
  artifacts\autopark_baseline\parking_corridor_servo_dryrun_20260611.jsonl \
  artifacts\autopark_baseline\parking_dry_run_detected_full_20260611.jsonl \
  --out artifacts\autopark_baseline\corridor_replay_report_current.json
```

Replay result:

```text
Synthetic polygon log:
  candidates=1 stable=1 raw=1 replayed=1
  replayed state=ENTER_SLOT
  replayed command=MOVE D=-6.0 V=1
  corridor_x_err=0.0
  left_margin_px=90.0
  right_margin_px=90.0
  line_risk=false

2026-06-11 corridor dry-run log:
  candidates=1 stable=0 raw=0 replayed=0
  last candidate=ALIGN_CORRIDOR
  command=ARC D=-8.0 STE=71 V=1
  corridor_x_err=-75.12
  min side margin=117.12 px
  line_risk=false

Older full dry-run log:
  candidates=192 stable=188 raw=0 replayed=0
  evidence gap: historical log did not preserve raw YOLO polygon
```

Current evidence gap:

```text
Old logs cannot fully compare pixel_servo vs corridor_servo because they do not
contain raw YOLO polygon/mask data. Future logs now include slot_polygon_px, so
the same replay script can recompute corridor decisions offline.
```

Current live-board limitation:

```text
The last board-side YOLO health check showed inference was running but count=0
in the current view. A stronger live corridor dry-run needs the camera/vehicle/
parking slot positioned so YOLO detects the slot before starting the capture.
```

Update after board rerun:

```text
The live YOLO view later recovered and produced Parking detections at roughly
90-95% confidence. A non-motion board corridor dry-run was completed and
downloaded for offline replay.
```

## Board Polygon Corridor Dry-Run - 2026-06-11 22:45

Uploaded local controller to the board:

```text
.venv\Scripts\python tools\board_auto_ssh.py put-text \
  --host 192.168.137.2 \
  --user root \
  --password ebaina \
  --allow-risk \
  tools\board_parking_controller.py \
  /opt/parking/autopark/board_parking_controller.py
```

Risk and safety:

```text
This overwrote the board controller script only.
No real-car motion was commanded.
The following run used --dry-run, so STM32 serial was not opened and no MOVE/ARC
command was sent to the STM32.
```

Executed board dry-run:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy corridor_servo \
  --dry-run \
  --duration-sec 20 \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --stable-frames 3 \
  --pixel-vision-lost-stop-sec 0.5 \
  --log-jsonl /tmp/parking_corridor_servo_polygon_dryrun_20260611.jsonl
```

Observed board output:

```text
dry_run=True
arm=False
arm_file=/tmp/parking_armed(False)
strategy=corridor_servo
stable_frames=3

initial unstable frames:
  frames=1/3, 2/3 -> WAIT=UNSTABLE

stable frames:
  state=APPROACH
  command candidate=ARC D=-20.0 STE=101 V=1
  send behavior=[dry-run] would send only

end:
  STOP=DURATION elapsed
```

Downloaded log:

```text
artifacts\autopark_baseline\parking_corridor_servo_polygon_dryrun_20260611.jsonl
size=66708 bytes
```

Offline replay command:

```text
.venv\Scripts\python tools\parking_corridor_replay.py \
  artifacts\autopark_baseline\parking_corridor_servo_polygon_dryrun_20260611.jsonl \
  artifacts\autopark_baseline\corridor_synthetic_compare_cases.jsonl \
  artifacts\autopark_baseline\parking_dry_run_detected_full_20260611.jsonl \
  --out artifacts\autopark_baseline\corridor_replay_board_polygon_report_current.json
```

Real board polygon replay result:

```text
candidates=40
stable=38
raw polygon rows=40
pixel/corridor compare rows=40
pixel/corridor command differences=0
pixel/corridor state differences=40
vision_lost=0

last stable corridor:
  state=APPROACH
  command=ARC D=-20.0 STE=101 V=1
  corridor_x_err=92.49 px
  min side margin=79.94 px
  line_risk=false
  closeness=0.797
```

Interpretation:

```text
The current live view is still in the far/approach phase. It is not yet near
enough to test physical line-pressure behavior, and the side margin is still
above the 34 px LINE_RISK threshold.

In this current view, pixel_servo and corridor_servo produce the same command,
but for different reasons:
  pixel_servo: PIXEL_ALIGN_X
  corridor_servo: APPROACH

The new log now contains slot_polygon_px and slot_edges_px, so future real runs
can be replayed frame-by-frame without the historical evidence gap.
```

Synthetic safety replay:

```text
artifacts\autopark_baseline\corridor_synthetic_compare_cases.jsonl

centered_enter:
  pixel=PIXEL_REVERSE MOVE D=-10.0 V=1
  corridor=ENTER_SLOT MOVE D=-6.0 V=1

left_line_risk:
  pixel=PIXEL_ALIGN_X ARC D=-10.0 STE=100 V=1
  corridor=LINE_RISK_LEFT STOP

right_line_risk:
  pixel=PIXEL_ALIGN_X ARC D=-10.0 STE=80 V=1
  corridor=LINE_RISK_RIGHT STOP

approach_offset_left:
  pixel=PIXEL_ALIGN_X ARC D=-40.0 STE=82 V=1
  corridor=APPROACH ARC D=-20.0 STE=83 V=1
```

Post-run safety checks:

```text
/tmp/parking_armed absent
no board_parking_controller process remains
no stm32_stop / stm32 bridge process remains
local py_compile PASS
```

## Real Corridor Run Failure And Fix - 2026-06-11 22:53

Executed real run:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy corridor_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --move-read-sec 8 \
  --stable-frames 3 \
  --pixel-vision-lost-stop-sec 0.5 \
  --corridor-approach-d-cm 20 \
  --corridor-align-d-cm 8 \
  --corridor-enter-d-cm 6 \
  --corridor-min-line-margin-px 34 \
  --log-jsonl /tmp/parking_corridor_servo_realrun_20260611.jsonl
```

Result:

```text
The vehicle still pressed significantly onto the parking frame.
This run must be treated as failed.
```

Downloaded log:

```text
artifacts\autopark_baseline\parking_corridor_servo_realrun_20260611.jsonl
```

Key evidence:

```text
stable command 1:
  lon=43.52 lat=-4.39 corridor_x_err=90.0
  command=ARC D=-20.0 STE=101 V=1

stable command 2:
  lon=30.56 lat=-5.37 corridor_x_err=106.0
  command=ARC D=-8.0 STE=109 V=1

stable command 3:
  lon=25.85 lat=-5.37 corridor_x_err=106.0
  command=ARC D=-8.0 STE=109 V=1

stable command 4:
  lon=19.72 lat=-5.21 corridor_x_err=103.33
  command=ARC D=-8.0 STE=109 V=1

then:
  YOLO target lost
  STOP=PIXEL_VISION_LOST
```

Interpretation:

```text
The controller did not converge. corridor_x_err grew from 90 px to 106 px
after the first real movement, while the controller kept commanding STE>90.
This indicates the corridor steering sign was wrong for the reverse motion in
this setup, or at minimum that this steering direction is physically divergent.

The old lateral divergence threshold was too loose to stop this early.
The line-risk check did not trigger because it only measured target-x margin
inside the detected slot, not whether the vehicle trajectory was actually
moving toward the frame.
```

Implemented local fix:

```text
tools\board_parking_controller.py
  - added --corridor-steer-sign, default -1.0
  - corridor steering now flips the failed real-run direction by default
  - added --corridor-diverge-stop-px, default 10.0
  - added --corridor-diverge-min-closeness, default 0.8
  - if corridor_x_err grows after a real/simulated corridor step, stop before
    issuing the next movement

tools\parking_corridor_replay.py
  - updated replay parameters for the new corridor steer sign and divergence
    knobs
```

Offline verification:

```text
.venv\Scripts\python -m py_compile \
  tools\board_parking_controller.py \
  tools\parking_corridor_replay.py

PASS
```

Replay with the corrected sign:

```text
old final command:
  ARC D=-8.0 STE=109 V=1

corrected-sign replay:
  ARC D=-8.0 STE=72 V=1
```

Divergence protection replay:

```text
first stable sent x_err=90.0
next stable x_err=106.0
growth=16.0 px
threshold=10.0 px
closeness=0.874
would_stop=True
```

Next test policy:

```text
Do not run another full autonomous reverse from this state.
The next real test should be a single-step or very short capped test with the
corrected steer sign, then inspect whether corridor_x_err decreases.
```

## Corrected-Sign Real Test Result - 2026-06-11 23:25

Executed corrected-sign test:

```text
--strategy corridor_servo
--arm
--corridor-steer-sign -1
--corridor-approach-d-cm 8
--corridor-align-d-cm 6
--corridor-enter-d-cm 5
--corridor-min-command-abs-d-cm 5
--corridor-diverge-stop-px 8
--corridor-diverge-min-closeness 0.65
--pixel-max-command-abs-d-cm 8
--log-jsonl /tmp/parking_corridor_servo_single_step_fix_20260611.jsonl
```

Safety result:

```text
STOP sent after test
STAT MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0 VEL=0.0
/tmp/parking_armed absent
```

Downloaded log:

```text
artifacts\autopark_baseline\parking_corridor_servo_single_step_fix_20260611.jsonl
```

Important correction:

```text
This was intended as a single-step validation, but the controller did not yet
have a CLI max-step gate. It therefore executed 7 stable 6 cm movements before
YOLO loss stopped the run.
```

Observed trajectory:

```text
first sent:
  ARC D=-6.0 STE=72 V=1
  lon=38.13 lat=-5.22 corridor_x_err=102.3

last sent:
  ARC D=-6.0 STE=71 V=1
  lon=19.41 lat=-5.45 corridor_x_err=107.33

vision lost:
  steps=7
  total_cm=42.0
```

Interpretation:

```text
Flipping the sign alone did not solve the path problem. corridor_x_err still
failed to decrease, and the lateral error stayed around -5.2 to -5.6 cm.

Do not keep tuning by full runs. The next controller revision must first add a
hard max-motion-step gate and should treat corridor_x_err as an observation
metric, not as a sufficient path-planning target.
```

Implemented local safety fix after this run:

```text
tools\board_parking_controller.py
  - added --max-motion-steps
  - added --max-total-cm

Recommended next real command must include:
  --max-motion-steps 1
  --max-total-cm 8
```

## Steering Command Effect Suspect - 2026-06-11

User observation:

```text
The vehicle appears not to be meaningfully controlled by steering, or the
steering command effect is too weak/late.
```

Code audit:

```text
STM32 firmware:
  SS928_hub\Core\CarProtocol.c
    ARC parses STE and calls StartArcDrive(distance, steer)
    PWM_STAT is supported

  SS928_hub\Core\CarControl.c
    StartArcDrive() calls SetSteeringAngle(steerDeg)
    then resets odometry, starts speed, and enters CTRL_ARC

  SS928_hub\HARDWARE\PWMO.c
    SetServoRotation() writes TIM2 CCR2 PWM according to requested angle

Current board controller before this fix:
  logs candidate_cmd only
  does not log ARC response
  does not log PWM_STAT before/during/after ARC
  does not prove servo PWM changed before movement
```

Important interpretation:

```text
The code path says ARC should command steering, but the prior parking logs only
prove that ARC strings were sent. They do not prove that the servo PWM reached
the target before the car moved.

STAT after STOP reports ANG=90 because STM32 SetStandbyMode() centers steering
after motion completion/stop. That does not prove whether steering was active
during the ARC command.

Because ARC starts steering and motor motion in the same command, a slow servo
or weak mechanical linkage can make the first part of each short reverse step
effectively straight.
```

Implemented local controller instrumentation:

```text
tools\board_parking_controller.py
  - added --log-stm32-detail
  - added --pre-steer-settle-sec
  - logs event=stm32_motion_result after real motion commands
  - logs stat_before, pwm_before, pre_servo_response, pwm_after_pre_servo,
    motion_response, pwm_after, stat_after
```

Recommended next validation, do not run full parking:

```text
1. Upload the instrumented controller.
2. Query read-only STAT/PWM_STAT at rest.
3. With the car lifted or wheels clear if possible, test SERVO A=70 and
   SERVO A=110 while visually confirming front wheel movement.
4. Only after the static steering response is confirmed, run a single capped
   ARC step with:
     --max-motion-steps 1
     --max-total-cm 8
     --log-stm32-detail
     --pre-steer-settle-sec 0.5
5. Compare pwm_after_pre_servo and motion_response before trusting any parking
   path controller.
```

Next capped command template:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy corridor_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --move-read-sec 8 \
  --stable-frames 3 \
  --pixel-vision-lost-stop-sec 0.5 \
  --max-motion-steps 1 \
  --max-total-cm 8 \
  --corridor-steer-sign -1 \
  --corridor-approach-d-cm 6 \
  --corridor-align-d-cm 6 \
  --corridor-enter-d-cm 5 \
  --corridor-min-command-abs-d-cm 5 \
  --pixel-max-command-abs-d-cm 8 \
  --log-stm32-detail \
  --pre-steer-settle-sec 0.5 \
  --log-jsonl /tmp/parking_corridor_servo_steering_instrumented_20260611.jsonl
```

Next board dry-run command, no motion:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy corridor_servo \
  --dry-run \
  --duration-sec 30 \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --stable-frames 3 \
  --pixel-vision-lost-stop-sec 0.5 \
  --log-jsonl /tmp/parking_corridor_servo_polygon_dryrun_20260611.jsonl
```

Next real-car single-pass command, do not execute until the car is physically
clear, YOLO is detecting the slot, and the operator is ready to stop power:

```text
touch /tmp/parking_armed
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --strategy corridor_servo \
  --arm \
  --target-wait-sec 1 \
  --settle-sec 0.5 \
  --stable-frames 3 \
  --pixel-vision-lost-stop-sec 0.5 \
  --corridor-approach-d-cm 20 \
  --corridor-align-d-cm 8 \
  --corridor-enter-d-cm 6 \
  --corridor-min-line-margin-px 34 \
  --log-jsonl /tmp/parking_corridor_servo_realrun_20260611.jsonl
rm -f /tmp/parking_armed
```

Recommended acceptance criteria for the next real test:

```text
1. Before YOLO loss, corridor_x_err should trend toward 0 instead of growing.
2. min side margin should not collapse below --corridor-min-line-margin-px.
3. LINE_RISK must stop the car before visible line pressure becomes obvious.
4. ENTER_SLOT should only occur after both corridor center and slot angle agree.
5. If YOLO is lost for 0.5 s, the controller must STOP.
```
