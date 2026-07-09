# dToF and YOLO Person Diagnostic - 2026-06-01

## Current topology

- Board: Euler Pi / SS928 at `192.168.137.2` over wired network.
- VM: Ubuntu at `192.168.137.100` for board-facing UDP and `192.168.247.129` for Foxglove.
- RTSP: `rtsp://192.168.137.2:554/live0`.
- dToF UDP: direct to VM `192.168.137.100:2368`.
- Foxglove: `ws://192.168.247.129:8765`.
- Board-side baseline: `/opt/sample/official_dtof`, running `sample_dtof_rtsp_stable` case7.
- Safety: perception-only. No MCU, CAN, serial actuator, motor, steering, brake, or throttle path is started.

## Current ROS topics

- `/parking/camera/image_jpeg`
- `/parking/dtof/depth_color`
- `/parking/dtof/obstacle_view`
- `/parking/dtof/obstacle_blocks`
- `/parking/sensors/health`
- `/parking/sensors/sync_pair`
- `/parking/vision/line_debug`
- `/parking/parking_slot_candidates`
- `/parking/yolo/person_view`
- `/parking/yolo/person_detections`
- `/parking/perception/state`

## dToF baseline finding

Current no-obstacle report:

- Report file on VM:
  `/home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_160948/session_20260601_160950/dtof_condition_reports/unobstructed_current_v2.json`
- Local baseline report:
  `D:\parking_board_agent\artifacts\dtof_yolo_validation\dtof_conditions\20260601_164226\unobstructed_local_baseline.json`
- UDP packet rate: about `17.30 Hz`.
- Packet size: all sampled packets were `4873` bytes.
- Expected shape: all sampled packets were `40x30`.
- Average valid pixels, using `20..10000 mm`: about `404 / 1200`.
- Average zero pixels: about `438 / 1200`.
- Average `2 mm` pixels: about `358 / 1200`.
- Valid depth median: about `5539 mm`.
- Valid depth p25: about `4313 mm`.
- Obstacle block state over sampled window: `clear` for `300 / 300` messages.
- Obstacle nearest robust median: about `5046 mm`.
- Updated support-filter view:
  - Average supported pixels `>=250 mm`: about `400 / 1200`.
  - Average supported `<500 mm`: about `10 / 1200`.
  - Average supported `<1200 mm`: about `20 / 1200`.
  - Far-left has the largest residual near noise, about `6.9` supported `<500 mm` pixels per frame.
  - Current obstacle threshold requires at least `16` support pixels and `20%` support ratio per zone.
- Latest local baseline:
  - UDP packet rate: about `16.48 Hz`.
  - Packet size: all sampled packets were `4873` bytes.
  - Valid depth median: about `5554 mm`.
  - Valid depth p25: about `4346 mm`.
  - Center-zone valid median: about `5592 mm`.
  - Obstacle block state: `clear` for `300 / 300` messages.
  - YOLO no-person check: `PASS`, report
    `D:\parking_board_agent\artifacts\dtof_yolo_validation\yolo_checks\yolo_check_20260601_164135.json`.

Interpretation so far:

- Transport and packet parsing are working.
- The raw frame contains many invalid or near-sentinel values (`0` and `2`), so raw pseudo-color can look noisy or visually similar across conditions.
- The obstacle block layer now suppresses those sparse near values and is stable when the scene is unobstructed.
- Completion still requires side-by-side physical-condition captures.

## Pending dToF physical captures

Capture the same report under:

1. `unobstructed_current_v2`: already captured.
2. `center_30_80cm_flat_object`: user places a hand, book, or flat board around `30..80 cm` in front of the dToF, centered.
3. `close_obstruction`: user places an object very close to the dToF or covers it briefly.

After each condition is physically set, run on the VM:

```bash
python3 /tmp/vm_dtof_condition_report.py --condition center_30_80cm_flat_object --frames 180 --metadata-lines 300
python3 /tmp/vm_dtof_condition_report.py --condition close_obstruction --frames 180 --metadata-lines 300
```

Or run from Windows and automatically download the JSON report:

```powershell
.venv\Scripts\python tools\dtof_yolo_validation.py capture-dtof --condition center_30_80cm_flat_object --frames 180 --metadata-lines 300
.venv\Scripts\python tools\dtof_yolo_validation.py capture-dtof --condition close_obstruction --frames 180 --metadata-lines 300
.venv\Scripts\python tools\dtof_yolo_validation.py compare-dtof --baseline D:\parking_board_agent\artifacts\dtof_yolo_validation\dtof_conditions\20260601_164226\unobstructed_local_baseline.json --test <downloaded_condition_report.json>
```

Expected evaluation:

- If valid median/p25 and center-zone support distances drop clearly in the `30..80 cm` test, the raw dToF is responding and remaining issues are visualization/threshold tuning.
- If the raw distance distribution barely changes even with a flat object at `30..80 cm`, the issue is likely board-side sample configuration, sensor mounting, cable, power, or module behavior.
- If only the close-obstruction case changes, close covering is not a valid proxy for normal obstacle detection.

## YOLO person status

Implementation:

- ROS node: `parking_bridge.yolo_person_node`.
- Runtime model: `/home/ebaina/parking_models/yolov8n.onnx`.
- Runtime backend: `onnxruntime` CPU provider.
- Input: `/parking/camera/image_jpeg`.
- Outputs:
  - `/parking/yolo/person_detections` (`std_msgs/String`, JSON)
  - `/parking/yolo/person_view` (`sensor_msgs/CompressedImage`)
  - `/parking/perception/state` (`std_msgs/String`, component=`yolo_person`)

Verified:

- Model loads on VM with input `[1, 3, 640, 640]` and output `[1, 84, 8400]`.
- Node starts under `ros2 launch parking_bridge parking.launch.py`.
- Current no-person frame publishes `person_count=0`, `status=no_person`.
- Current person-view rate is about `4..5 Hz`.
- `/parking/perception/state` includes `component="yolo_person"` messages.
- Foxglove low-bandwidth audit passed with `/parking/yolo/person_view` and `/parking/yolo/person_detections` in the bridge whitelist:
  `D:\parking_board_agent\artifacts\foxglove_low_bandwidth_audit\foxglove_low_bandwidth_20260601_162848.json`
- Example no-person detection message:

```json
{
  "model": "yolov8n.onnx",
  "class_filter": "person",
  "person_count": 0,
  "status": "no_person",
  "inference_ms": 177.2,
  "motion_enabled": false,
  "actuator_control_allowed": false
}
```

Pending:

- User stands in the camera view for a short positive test.
- Verify `/parking/yolo/person_detections` reports at least one `person` bbox.
- Verify `/parking/yolo/person_view` displays the bbox in Foxglove.
- Positive check command:

```powershell
.venv\Scripts\python tools\dtof_yolo_validation.py check-yolo --duration 10 --require-person
```

## Foxglove view

Connect to:

```text
ws://192.168.247.129:8765
```

Recommended panels:

- Image: `/parking/camera/image_jpeg`
- Image: `/parking/yolo/person_view`
- Image: `/parking/dtof/obstacle_view`
- Image: `/parking/dtof/depth_color`
- Raw Messages: `/parking/yolo/person_detections`
- Raw Messages: `/parking/dtof/obstacle_blocks`
- Raw Messages: `/parking/sensors/health`
- Raw Messages: `/parking/perception/state`

## Restore commands

From Windows workspace:

```powershell
.venv\Scripts\python tools\perception_link_manager.py adapt --allow-risk
.venv\Scripts\python tools\foxglove_bridge_control.py start --vm-host 192.168.247.129 --skip-upload
.venv\Scripts\python tools\perception_link_manager.py health
```
