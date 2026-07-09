# C0 YAW Validation - 2026-06-13

## Purpose

Validate whether STM32 `STAT YAW=` can be trusted by the board-side PoseFuser.

This is part of the core fusion closed-loop plan:

```text
docs/autopark_fusion_closed_loop_plan_20260613.md
```

## Commands

Non-motion checks:

```text
STAT x10
ZERO_YAW
STAT x10
single-session rapid STAT x10
```

No new motion command was executed during this C0 YAW check. The planned
movement-induced YAW test was skipped because static YAW already failed.

## Results

### Static Before ZERO_YAW

Report:

```text
artifacts/autopark_baseline/c0_yaw_static_before_zero_20260613.json
```

YAW samples:

```text
-152.5, 57.8, -94.0, 112.6, -37.2, 171.0, 17.6, -135.8, 73.3, -73.3
```

Range:

```text
323.5 deg
```

### Static After ZERO_YAW

Report:

```text
artifacts/autopark_baseline/c0_yaw_static_after_zero_20260613.json
```

YAW samples:

```text
69.1, -81.8, 128.9, -23.6, -178.7, 30.0, -118.7, 91.5, -63.6, 146.1
```

Range:

```text
324.8 deg
```

### Same Serial Session Rapid STAT

This was run to rule out repeated CH341/serial reinitialization effects.

Observed sequence:

```text
STAT 8400 YAW=9.5
STAT 8401 YAW=30.9
STAT 8402 YAW=52.3
STAT 8403 YAW=73.7
STAT 8404 YAW=95.0
STAT 8405 YAW=116.4
STAT 8406 YAW=137.8
STAT 8407 YAW=159.1
STAT 8408 YAW=-179.5
STAT 8409 YAW=-158.1
```

The yaw advanced by about 21.4 deg per sample while the vehicle was static.
At the sampling interval used here, this is approximately an 80 deg/s false yaw
rate.

## Conclusion

`STAT YAW=` is not currently usable for PoseFuser.

This is not a simple zero-point issue:

```text
ZERO_YAW changes the offset but does not stop the drift.
The drift is visible within one continuous serial session.
The issue is on the STM32/BMI270 yaw path, not in the Windows query script.
```

Likely fault area:

```text
SS928_hub/HARDWARE/BMI270/bmi270_driver.c
  BMI270_SoftCalibrate_Z()
  BMI270_Get_Raw()
  BMI270_Get_AngleDt()

SS928_hub/HARDWARE/CarApp.c
  ServiceMpuTask()
```

Most likely causes:

```text
1. GyroZ zero offset is wrong or calibration acceptance is too weak.
2. BMI270 gyro raw byte/axis mapping is wrong.
3. BMI270 gyro scale/range does not match actual register configuration.
4. PT1 filter state starts at zero after calibration and leaves a large transient.
5. dt accumulation is larger than intended, amplifying yaw integration.
```

## Decision

Until fixed:

```text
PoseFuser must not trust YAW.
YAW may only be logged as diagnostic data.
The fusion plan should continue with odometry and vision parsing work, but B2
must gate yaw use on a successful C0 re-test.
```

## Next Software Step

Add an IMU diagnostic command or extend `STAT`/`GET` diagnostics to expose:

```text
raw GyroX/GyroY/GyroZ
post-offset GyroX/GyroY/GyroZ
gyro_zero_x/y/z
dt used by BMI270_Get_AngleDt()
unfiltered vs filtered GyroZ
```

Then re-run static sampling and verify post-offset GyroZ is near 0 before using
YAW in any closed-loop logic.

## Retest After User YAW Firmware Update - 2026-06-13

Non-motion commands:

```text
PING
VER
STAT
GDIAG
GYROCAL
GDIAG
ZERO_YAW
same-session STAT x20
```

Report:

```text
artifacts/autopark_baseline/c0_yaw_static_retest_after_user_update_20260613.json
```

Observed diagnostics:

```text
GDIAG ID=0x24 RANGE=0 SCALE=1065 DT=5.0ms ZZ=-2 TEMP=26.5 I2CERR=0 IMU=OK
RAWPOST values stayed near zero.
```

Static YAW samples after `GYROCAL` and `ZERO_YAW`:

```text
-0.1 repeated for all 20 samples
```

Result:

```text
sample_count_parsed: 20
yaw_range_deg: 0.0
yaw_first_last_delta_deg: 0.0
imu_values: IMU=OK
pass_static_yaw: true
```

Decision:

```text
The static YAW drift bug is fixed enough for the next C0 step.
C0 is not fully complete yet: movement sign validation is still required before
PoseFuser may trust yaw in closed-loop movement.
```

## Reverse Right Motion Sign Sample - 2026-06-13

Motion command, approved by operator:

```text
TEL ON
ARC D=-6.0 STE=120 V=1
TEL OFF
STAT
```

Report:

```text
artifacts/autopark_baseline/c0_motion_sign_reverse_right_20260613.json
configs/chassis_signs.json
```

Observed `ARC` response:

```text
ACK 8521 ARC
TLM 0..10 with IMU=OK
DONE 8521 ARC X=0.7 Y=-4.0 D=4.0 YAW=1.5
```

Post-motion state:

```text
STAT 8523 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0
          YAW=1.5 X=0.8 Y=-4.4 D=4.5 VEL=0.0 DROP=0 IMU=OK
```

Sign observations:

```text
Reverse commanded distance D=-6.0 produced odometry D=+4.0/+4.5.
Reverse velocity is negative.
STE=120 reverse arc produced positive X and positive YAW.
YAW changed smoothly from -0.1 to +1.5 deg during motion.
```

Partial `configs/chassis_signs.json` result:

```text
odom_d_reverse_negative: false
odom_x_right_positive: true
yaw_cw_positive: null
vision_lateral_left_negative: null
```

Decision:

```text
Static YAW and motion YAW smoothness are now acceptable.
C0 is still partial because yaw_cw_positive requires operator visual
confirmation or a manual clockwise rotation sample, and vision lateral sign must
be verified from YOLO slot state.
PoseFuser must still refuse motion while required sign fields remain null.
```

### Repeat Reverse Right Sample

Second approved repeat motion:

```text
ARC D=-6.0 STE=120 V=1
```

Report:

```text
artifacts/autopark_baseline/c0_motion_sign_reverse_right_repeat_20260613.json
```

Observed:

```text
DONE 8531 ARC X=0.4 Y=-4.1 D=4.1 YAW=3.4
STAT 8533 MODE=IDLE RUN=STANDBY DIR=-1 SPD=0 ANG=90.0
          YAW=4.0 X=0.7 Y=-5.7 D=5.7 VEL=0.0 DROP=0 IMU=OK
```

This is consistent with the first sample:

```text
STE=120 reverse arc -> YAW increased, X positive, Y negative, D positive.
```

Operator visual confirmation:

```text
The repeated STE=120 reverse arc looked clockwise from top view.
Because YAW increased during that motion, yaw_cw_positive=true.
Confidence: preliminary/operator-observed.
```

Updated:

```text
configs/chassis_signs.json
  yaw_cw_positive: true
  odom_d_reverse_negative: false
  odom_x_right_positive: true
  vision_lateral_left_negative: null
```

## Vision Lateral Sign - 2026-06-13

Report:

```text
artifacts/autopark_baseline/c0_vision_lateral_sign_20260613.json
```

Live status:

```text
board YOLO process: running
board_yolo_udp_tee.py: running
UDP samples from 127.0.0.1:24580: received
current detections: detection_count=0
```

Current live scene therefore did not provide a fresh physical left/right
placement test.

Source-code convention:

```text
tools/board_parking_controller.py:
  Pixel(YOLO 640x640) -> ground cm in rear-axle frame [+x reverse/toward slot, +y left].

slot_relative_state:
  ground_estimate.slot_lateral_cm = plan.lat
```

Historical evidence:

```text
artifacts/autopark_baseline/parking_slot_state_dryrun_20260612.jsonl
rows: 33
slot_x_err_px mean: +76.333
slot_lateral_cm mean: -3.949
```

Decision:

```text
vision_lateral_left_negative: false
Reason: the implemented ground frame defines left as positive. Historical right
image error maps to negative slot_lateral_cm, which is consistent with right
being negative and left being positive.
Confidence: source-code convention plus historical sample; live current scene
was blocked by YOLO detection_count=0.
```

Current `configs/chassis_signs.json`:

```text
yaw_cw_positive: true
odom_d_reverse_negative: false
odom_x_right_positive: true
vision_lateral_left_negative: false
```

## B1/B2 Local Software Foundation - 2026-06-13

Implemented locally:

```text
tools/parking_fusion.py
tools/parking_fusion_selftest.py
```

`parking_fusion.py` provides:

```text
parse_stm32_line()
parse_stm32_text()
load_chassis_signs()
vision_anchor_from_slot_state()
PoseFuser
```

`tools/board_parking_controller.py` now:

```text
imports parking_fusion when available
adds --chassis-signs-json
adds --require-fusion-signs
prints FUSION_SIGNS=OK/INVALID at startup
adds structured pre_servo_events and motion_events to stm32_motion_result logs
caps acquire_info wait time by --duration-sec for bounded dry-run health checks
```

Local verification:

```text
.venv\Scripts\python -m py_compile tools\parking_fusion.py tools\parking_fusion_selftest.py tools\board_parking_controller.py tools\stm32_send.py
.venv\Scripts\python tools\parking_fusion_selftest.py
.venv\Scripts\python tools\board_parking_controller.py --dry-run --duration-sec 0.5 --target-wait-sec 0.1 --listen-port 0 --chassis-signs-json configs\chassis_signs.json --require-fusion-signs
```

Observed startup gate:

```text
FUSION_SIGNS=OK configs\chassis_signs.json yaw_cw_positive=True
odom_d_reverse_negative=False odom_x_right_positive=True
vision_lateral_left_negative=False
```

Decision:

```text
B1/B2 local parser and PoseFuser skeleton are ready for board deployment.
No board files were changed by this step.
Next board-side step requires copying parking_fusion.py, board_parking_controller.py,
and chassis_signs.json to /opt/parking/autopark/ after operator approval.
```

## B1/B2 Board Deployment - 2026-06-13

Deployed to board `192.168.137.2`:

```text
/opt/parking/autopark/parking_fusion.py
/opt/parking/autopark/board_parking_controller.py
/opt/parking/autopark/chassis_signs.json
```

Board verification:

```text
python3 -m py_compile /opt/parking/autopark/parking_fusion.py /opt/parking/autopark/board_parking_controller.py
python3 /opt/parking/autopark/parking_fusion.py --signs /opt/parking/autopark/chassis_signs.json --parse-line 'DONE 8521 ARC X=0.7 Y=-4.0 D=4.0 YAW=1.5'
```

Parsed result:

```text
signs loaded from /opt/parking/autopark/chassis_signs.json
DONE parsed as: type=done seq=8521 cmd=ARC x=0.7 y=-4.0 d=4.0 yaw=1.5
```

Board no-motion controller check:

```text
cd /opt/parking/autopark &&
python3 ./board_parking_controller.py --dry-run --duration-sec 0.5 --target-wait-sec 0.1 --listen-port 0 --chassis-signs-json /opt/parking/autopark/chassis_signs.json --require-fusion-signs
```

Observed:

```text
FUSION_SIGNS=OK /opt/parking/autopark/chassis_signs.json
yaw_cw_positive=True odom_d_reverse_negative=False
odom_x_right_positive=True vision_lateral_left_negative=False
STOP=NO_TARGET (no slot / no anchor).
STOP=DURATION elapsed.
```

No motion command was sent during deployment verification.

## B2 Shadow Fusion Logging - 2026-06-13

Local controller update:

```text
tools/board_parking_controller.py now creates PoseFuser in shadow_log_only mode
when chassis signs are valid.
```

New log fields:

```text
candidate.fusion_pose
stm32_motion_result.fusion_motion_trace
stm32_motion_result.fusion_motion_final
```

Behavior:

```text
fusion_pose is anchored from stable slot_relative_state.
fusion_motion_trace is propagated only from parsed TLM rows after a real motion.
The fused pose is logged only; it does not affect candidate selection or STM32 commands.
```

Local no-board UDP test:

```text
artifacts/autopark_baseline/fusion_shadow_local_dryrun_20260613.jsonl
```

Observed candidate fusion pose:

```text
fusion_pose:
  x_s_cm=-3.925
  y_s_cm=-48.36
  phi_deg=2.32
  source=vision_anchor
  tlm_count=0
candidate_cmd=ARC D=-7.0 STE=100 V=1
```

Verification:

```text
.venv\Scripts\python -m py_compile tools\parking_fusion.py tools\parking_fusion_selftest.py tools\board_parking_controller.py tools\stm32_send.py
.venv\Scripts\python tools\parking_fusion_selftest.py
local UDP dry-run generated candidate.fusion_pose
```

Board deployment for this shadow logging update is pending operator approval.

## B2 Shadow Fusion Board Live Dry-Run - 2026-06-13

Deployed updated controller:

```text
/opt/parking/autopark/board_parking_controller.py
```

Board verification:

```text
python3 -m py_compile /opt/parking/autopark/board_parking_controller.py
```

Live dry-run command:

```text
cd /opt/parking/autopark &&
python3 ./board_parking_controller.py --dry-run --duration-sec 4 --target-wait-sec 0.5 --listen-host 127.0.0.1 --listen-port 24580 --stable-frames 1 --chassis-signs-json /opt/parking/autopark/chassis_signs.json --require-fusion-signs --log-jsonl /tmp/parking_fusion_live_dryrun_20260613_055316.jsonl
```

Observed:

```text
FUSION_SIGNS=OK
fusion_pose=shadow_log_only
YOLO live detections available
candidate rows include slot_relative_state and fusion_pose
No motion was sent: dry_run=True, send_to_stm32=False
```

Example live candidate:

```text
slot_y_dist_cm ~= 38.5
slot_lateral_cm ~= -1.1
slot_x_err_px ~= 27..31
min_margin_px ~= 187..191
fusion_pose:
  x_s_cm ~= -1.1
  y_s_cm ~= -38.6
  phi_deg ~= 2.3..2.7
  source=vision_anchor
candidate_cmd=MOVE D=-7.0 V=1
```

Decision:

```text
B2 shadow fusion logging is live on the board and validated with real YOLO UDP.
It is still log-only. The next step is to run one approved short real motion
with this logger enabled so fusion_motion_trace can be validated against TLM.
```

## B2 Shadow Fusion Motion Trace Validation - 2026-06-13

Report:

```text
artifacts/autopark_baseline/b2_fusion_motion_trace_tel_20260613.json
Board log: /tmp/parking_fusion_motion_trace_tel_20260613.jsonl
```

Approved motion command was run through the controller with:

```text
--motion-telemetry
--max-motion-steps 1
--max-total-cm 8
```

Controller selected:

```text
MOVE D=-7.0 V=1
```

Telemetry result:

```text
TEL ON:  DONE 1003 TEL ON
MOVE:    ACK 1004 MOVE
TLM:     11 rows, TLM 21..31
DONE:    DONE 1004 MOVE X=-0.0 Y=-5.1 D=5.1
TEL OFF: DONE 1005 TEL OFF
STAT after: YAW=-21.3 X=-0.0 Y=-6.2 D=6.2 DROP=0 IMU=OK
```

Fusion result:

```text
candidate fusion_pose:
  x_s_cm=-0.704
  y_s_cm=-36.302
  phi_deg=-0.614
  source=vision_anchor

fusion_motion_final:
  x_s_cm=-0.757
  y_s_cm=-31.402
  phi_deg=-0.614
  source=dead_reckon
  tlm_count=11
  last_tlm_n=31
```

Interpretation:

```text
The fused y_s coordinate moved by about +4.9cm, matching the final TLM D=4.9cm
and the MOVE DONE D=5.1cm scale. Straight reverse kept phi essentially constant.
B2 shadow TLM -> fusion_motion_trace is validated.
```

Open protocol note:

```text
This MOVE DONE line did not include YAW, although TLM and STAT did include YAW.
Earlier F3 validation had MOVE DONE with YAW. Before relying on DONE yaw, verify
the firmware DONE format remains consistent for TEL ON/OFF motion runs.
```

Decision:

```text
B2 shadow trace passes.
PoseFuser may now be used for dry-run reconcile logging.
PoseFuser is still not authorized to affect control commands until reconcile
checks and safety gates are implemented and reviewed.
```

## C2 ARC Calibration Sample STE=120 - 2026-06-13

Report:

```text
artifacts/autopark_baseline/c2_arc_calib_ste120_20260613.json
Board log: /tmp/parking_arc_calib_ste120_20260613.jsonl
```

Approved command:

```text
ARC D=-6.0 STE=120 V=1
```

Pre-YOLO:

```text
lon=37.00cm
lat=-0.58cm
head=0.03deg
fusion_pose: x_s=-0.582 y_s=-37.004 phi=0.026
```

TLM:

```text
TLM rows: 10
first: YAW=-21.5 D=0.0 X=0.0 Y=0.0
last:  YAW=-19.2 D=3.6 X=0.2 Y=-3.6
yaw_change=+2.3deg
dist_change=3.6cm
preliminary R_eff ~= 89.7cm
```

STAT after:

```text
YAW=-18.0 X=0.3 Y=-5.9 D=5.9 DROP=0 IMU=OK
```

Fusion:

```text
fusion_motion_final:
  x_s=-0.503
  y_s=-33.405
  phi=2.326
  tlm_count=10
```

Post-YOLO:

```text
lon=35.59cm
lat=3.28cm
head=-1.95deg

YOLO delta:
  lon=-1.41cm
  lat=+3.86cm
  head=-1.98deg
```

Interpretation:

```text
STE=120 clearly produces positive yaw change and an arc.
The preliminary TLM curvature estimate is R_eff ~= 90cm.
Post-YOLO lateral changed much more than fusion x_s, so do not fit a final model
from this single sample. Repeat after serial DONE reader fix and collect
STE=105/75/60 samples.
```

Reader fix:

```text
The captured DONE line was truncated:
  DONE 1004 ARC X=0.2 Y=-4.1 D=4.1 Y

Local fixes:
  board_parking_controller.py now waits for a complete DONE/ERR line.
  stm32_send.py reads an extra tail after DONE/ERR.
```

## C2 ARC Calibration STE=120 Repeat After Reader Fix - 2026-06-13

Report:

```text
artifacts/autopark_baseline/c2_arc_calib_ste120_repeat_20260613.json
Board log: /tmp/parking_arc_calib_ste120_repeat_20260613.jsonl
```

Result:

```text
Pre-YOLO: lon=36.83 lat=-1.35 head=-1.52
TLM rows: 10
TLM yaw_change=+1.8deg
TLM dist_change=2.7cm
R_eff ~= 85.9cm
DONE complete: DONE 1004 ARC X=0.2 Y=-4.1 D=4.1 YAW=-29.1
STAT after: YAW=-28.4 X=0.4 Y=-5.8 D=5.8 DROP=0 IMU=OK
Post-YOLO: lon=34.98 lat=1.53 head=-0.96
```

Decision:

```text
Reader fix is verified.
STE=120 now has two preliminary R_eff samples: 89.7cm and 85.9cm.
Continue C2 calibration with STE=105, STE=75, STE=60.
```

## C2 STE=105 One-Step Incident - 2026-06-13

Report:

```text
artifacts/autopark_baseline/c2_arc_calib_ste105_incident_20260613.json
```

Approved command under test:

```text
ARC D=-6.0 STE=105 V=1
```

First motion result:

```text
Pre-YOLO: lon=35.1 lat=1.6 head=-1.3
DONE: DONE 1004 ARC X=0.3 Y=-4.1 D=4.1 YAW=-28.8
STAT after first step: YAW=-28.4 X=0.5 Y=-5.8 D=5.9 DROP=0 IMU=OK
fusion final: x_s=1.529 y_s=-31.772 phi=-0.493
odom_progress_cm=5.9
```

Safety incident:

```text
YOLO was lost after the first step.
The legacy dead-reckon branch issued an extra blind MOVE D=-10.0 V=1.
This violates the one-step calibration constraint, so the sample is not valid
for curve fitting.
```

Corrective action:

```text
board_parking_controller.py now stops by default after vision loss.
Dead-reckon continuation requires --allow-dead-reckon-after-loss.
primitive_probe stops immediately on vision loss.
Dead-reckon commands are capped by --max-motion-steps and --max-total-cm.
```

## C2 STE=105 Repeat After Safety Fix - 2026-06-13

Report:

```text
artifacts/autopark_baseline/c2_arc_calib_ste105_repeat_20260613.json
Local motion log:
artifacts/autopark_baseline/parking_arc_calib_ste105_repeat_20260613.jsonl
Local post dry-run log:
artifacts/autopark_baseline/parking_arc_calib_ste105_post_dryrun_20260613.jsonl
```

Approved command:

```text
ARC D=-6.0 STE=105 V=1
```

Result:

```text
Pre-YOLO:  lon=37.12 lat=0.47 head=1.09 confidence=0.799
Post-YOLO: lon=34.88 lat=3.11 head=-1.23 confidence=0.886
Vision delta: lon=-2.24cm lat=+2.64cm head=-2.32deg

TLM rows: 10
TLM first: YAW=-6.5 D=0.0 X=0.0 Y=0.0
TLM last:  YAW=-6.0 D=1.6 X=0.0 Y=-1.6
TLM yaw_change=+0.5deg
TLM dist_change=1.6cm
TLM R_eff ~= 183.3cm

DONE: DONE 1005 ARC X=0.1 Y=-4.1 D=4.1 YAW=-5.5
DONE yaw_change=+1.0deg
DONE R_eff ~= 234.9cm

STAT after: YAW=-5.0 X=0.2 Y=-6.7 D=6.8 DROP=0 IMU=OK
STAT yaw_change=+1.5deg
STAT R_eff ~= 259.7cm

Fusion final: x_s=0.511 y_s=-35.522 phi=1.594
Safety: steps=1 total_cm=6.8, no extra blind move
```

Interpretation:

```text
STE=105 is now a valid one-step sample.
It is much shallower than STE=120, so do not fit the final steering model yet.
Collect STE=75 and STE=60 next.
```
