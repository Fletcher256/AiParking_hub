# dToF and YOLO Validation Report

- Generated: 2026-06-01 18:47:23
- Audit JSON: `D:\parking_board_agent\artifacts\dtof_yolo_validation\audits\audit_20260601_184723.json`
- Overall status: `PENDING`
- Safety: perception-only; no MCU, CAN, serial actuator, motor, steering, brake, or throttle path is used.

## Board Runtime Evidence

- Board runtime should be `/opt/sample/official_dtof/sample_dtof_rtsp_stable 7 192.168.137.100`.
- Treat `/opt_sample` only as an old experiment archive, not as the active baseline.
- Confirm with `perception_link_manager.py health` after each restart.

## dToF Evidence

Physical-condition dToF reports exist. Compare the rows below: a clear drop in center-zone p25/median and an obstacle/warn state means the raw sensor is responding; little change means the remaining fault is board-side acquisition, sensor mounting, cable, power, or the test target.

| Condition | Name | Packet rate | Avg valid pixels | p25 | median | obstacle states |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| unobstructed | current_after_camera_rotate_unobstructed | 17.453 Hz | 391.572 | 4276 mm | 5540 mm | {'clear': 300} |
| 30-80cm flat object | center_30_80cm_blocked_user_holding | 17.394 Hz | 396.833 | 4266 mm | 5529 mm | {'clear': 300} |
| close obstruction | close_obstruction_retry_2 | 18.310 Hz | 334.033 | 3816 mm | 5292 mm | {'clear': 300} |

### dToF Diagnosis

- `30_80cm_flat_object`: `no_clear_raw_response`
  - The test report does not show a clear raw-depth response against the baseline. Next checks should focus on target placement/reflectivity, sensor angle, cable/power, or falling back to official case1/case3/case7 validation.
- `close_obstruction`: `no_clear_raw_response`
  - The test report does not show a clear raw-depth response against the baseline. Next checks should focus on target placement/reflectivity, sensor angle, cable/power, or falling back to official case1/case3/case7 validation.

Normal Foxglove dToF panels:

- Image: `/parking/dtof/obstacle_view`
- Image: `/parking/dtof/depth_color`
- Raw Messages: `/parking/dtof/obstacle_blocks`

## YOLO Person Evidence

YOLO negative and positive checks have both passed.

- No-person check: `PASS`, max_person_count=0
- Person-visible check: `PASS`, max_person_count=1
- Foxglove Image: `/parking/yolo/person_view`
- Foxglove Raw Messages: `/parking/yolo/person_detections`

## Foxglove

- Low-bandwidth audit: `PASS`
- Connect to `ws://192.168.247.129:8765`.

## Pending Items

- `dtof_flat_object_raw_response`: The test report does not show a clear raw-depth response against the baseline. Next checks should focus on target placement/reflectivity, sensor angle, cable/power, or falling back to official case1/case3/case7 validation.
- `dtof_close_obstruction_raw_response`: The test report does not show a clear raw-depth response against the baseline. Next checks should focus on target placement/reflectivity, sensor angle, cable/power, or falling back to official case1/case3/case7 validation.

## Commands

```powershell
.venv\Scripts\python tools\perception_link_manager.py health
.venv\Scripts\python tools\foxglove_low_bandwidth_audit.py --vm-host 192.168.247.129 --skip-upload
.venv\Scripts\python tools\dtof_yolo_validation.py capture-dtof --condition center_30_80cm_flat_object --frames 180 --metadata-lines 300
.venv\Scripts\python tools\dtof_yolo_validation.py capture-dtof --condition close_obstruction --frames 180 --metadata-lines 300
.venv\Scripts\python tools\dtof_yolo_validation.py diagnose-dtof
.venv\Scripts\python tools\dtof_yolo_validation.py check-yolo --duration 10 --require-person
```
