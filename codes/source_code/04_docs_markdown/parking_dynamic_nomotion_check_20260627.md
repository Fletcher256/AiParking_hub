# Parking Dynamic No-Motion Check - 2026-06-27

## Scope

Approved no-motion dynamic validation:

1. Start board YOLO + UDP tee.
2. Run board `action_replanner` with `--replanner-dry-run`.
3. Stop YOLO + UDP tee.
4. Fetch and analyze logs.

No STM32 motion command was sent. `/tmp/parking_armed` remained missing.

## Commands Executed

Start perception:

```powershell
.venv\Scripts\python.exe tools\board_auto_ssh.py run --host 192.168.137.2 --socket-timeout 1 --ssh-timeout 8 --command-timeout 45 --allow-risk "ACTION=start VM_HOST=192.168.137.100 sh /opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh"
```

Controller no-motion:

```powershell
.venv\Scripts\python.exe tools\board_auto_ssh.py run --host 192.168.137.2 --socket-timeout 1 --ssh-timeout 8 --command-timeout 75 --allow-risk "/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --strategy action_replanner --replanner-dry-run --duration-sec 30 --stable-frames 5 --pixel-vision-lost-stop-sec 0.5 --listen-host 127.0.0.1 --listen-port 24580 --action-library-json /opt/parking/autopark/parking_action_library.json --response-model-json /opt/parking/autopark/parking_action_response_model.json --success-criteria-json /opt/parking/autopark/parking_success_criteria.json --chassis-signs-json /opt/parking/autopark/chassis_signs.json --require-fusion-signs --perception-filter-json /opt/parking/autopark/perception_filter.json --log-jsonl /tmp/parking_action_replanner_dryrun_20260627.jsonl"
```

Stop perception:

```powershell
.venv\Scripts\python.exe tools\board_auto_ssh.py run --host 192.168.137.2 --socket-timeout 1 --ssh-timeout 8 --command-timeout 45 --allow-risk "ACTION=stop sh /opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh"
```

## Artifacts

Fetched logs:

```text
D:\parking_board_agent\artifacts\autopark_dynamic_check_20260627\tmp__parking_action_replanner_dryrun_20260627.jsonl
D:\parking_board_agent\artifacts\autopark_dynamic_check_20260627\tmp__parking_yolo_closed_loop_monitor.log
D:\parking_board_agent\artifacts\autopark_dynamic_check_20260627\tmp__parking_yolo_udp_tee.log
D:\parking_board_agent\artifacts\autopark_dynamic_check_20260627\parking_action_replanner_dryrun_20260627_summary.json
D:\parking_board_agent\artifacts\autopark_dynamic_check_20260627\parking_action_replanner_dryrun_20260627_curve.csv
```

## Result Summary

Controller startup:

```text
FUSION_SIGNS=OK
strategy=action_replanner
replanner_dry_run=True
no_motion_mode=True
listening UDP 127.0.0.1:24580
```

Controller result:

```text
STOP=NO_TARGET (no slot / no anchor). repeated
STOP=DURATION elapsed
```

Dry-run JSONL summary:

```text
total_events=6
candidate_events=0
replanner_step_events=0
vision_lost_events=5
send_to_stm32_events=0
motion_events=0
actuator_allowed_events=0
```

YOLO log:

```text
model /opt/sample/parking_yolo_seg_safe/parking_slot.om loaded successfully
OS08A20 init success
ISP Dev 0 running
parking_yolo_udp target=127.0.0.1:24579
parking_yolo_image_udp target=192.168.137.100:24581
parking_yolo_live_infer idx=1 ret=0x0 count=0
parking_yolo_live_infer idx=2 ret=0x0 count=0
...
parking_yolo_live_infer idx=630 ret=0x0 count=0
```

UDP tee log:

```text
listen=127.0.0.1:24579
targets=127.0.0.1:24580,192.168.137.100:24580
packets reached 660
rate reached about 12.49 Hz
packet bytes=219
```

Stop/cleanup:

```text
BOARD_YOLO_STOP stdin_newline pid=2545
BOARD_YOLO_CLEANUP_RUN /opt/parking/autopark/mpp_sys_vb_exit max_pool_cnt=768
MPP_SYS_EXIT ret=0x0
MPP_VB_EXIT ret=0x0
BOARD_YOLO_STOP_ONLY_DONE
```

Post-check:

```text
no parking / YOLO / controller / STM32 process
no relevant UDP/TCP socket
/proc/umap/vb max_pool_cnt=0
/tmp/parking_armed missing
```

## Verdict

```text
Camera + YOLO process startup: PASS
Model load: PASS
UDP from YOLO to tee: PASS
UDP tee forwarding: PASS
Controller no-motion safety: PASS
Controller received usable slot target: FAIL / no target
Overall dynamic no-motion chain: PARTIAL PASS
```

The current failure point is **perception content**, not transport or controller
safety. YOLO is running and publishing UDP packets, but every inference in the
captured run reported `count=0`, so the controller had no parking-slot polygon
to convert into `slot_relative_state`.

## Likely Causes to Check Next

One or more of:

1. No visible parking slot in the current camera view.
2. Camera view orientation/color/format is still not what the model expects.
   - Runtime used `VPSS_ROTATE180=1`, `PARKING_YOLO_ROTATE180=0`,
     `PARKING_YOLO_SWAP_UV=0`, `VPSS_PIXEL_FORMAT=nv12`.
3. Confidence threshold `0.4` is too high for the current scene/model.
4. The current `parking_slot.om` model may not match the current physical scene.
5. VM/image monitor was not running, so no live visual frame was captured in this
   check.

## Recommended Next Step

Run a perception debug capture:

```text
start VM image/detection monitor or a lightweight UDP image receiver
start board YOLO again
capture current camera frame / YOLO image UDP
inspect whether parking lines are visible and correctly oriented/color-formatted
then test lower confidence and/or alternate wrapper if needed
```

This requires additional approval because it starts processes and writes
temporary files on the board and/or VM.


## Follow-up Perception Capture and L2 PASS - 2026-06-27 14:02 CST

After the initial no-target run, a lightweight Windows UDP image/detection capture
was used with `VM_HOST=192.168.137.1` to receive board YOLO image UDP directly.

Artifacts:

```text
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\udp_capture_windows\capture_summary.json
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\udp_capture_windows\detections_udp.jsonl
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\udp_capture_windows\image_frame_000030_raw.jpg
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\udp_capture_windows\image_frame_000030_overlay_last_positive.jpg
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\nomotion_replanner_1400\summary.json
D:\parking_board_agent\artifacts\autopark_perception_debug_20260627\nomotion_replanner_1400\tmp__parking_action_replanner_dryrun_perception_20260627.jsonl
```

Visual capture result:

```text
image_frames=3
image_packets=1536
bad_image_packets=0
det_packets=30
initial short capture positive detections=2/30
```

The raw image shows the yellow-tape parking slot visible and correctly oriented.
The positive overlay confirms the OM model is segmenting the slot interior, but
border/occlusion/glare can make detections intermittent in very short captures.

A second `action_replanner --replanner-dry-run` run against the current visible
scene achieved a stable target and selected an action continuously without any
motion output:

```text
candidate_events=75
replanner_step_events=75
stable_candidate_events=71
vision_lost_events=0
top_command=ARC D=-6.0 STE=120 V=1 (71 times)
chosen_action=reverse_right_hard_6 (71 times)
chosen_origin=measured_neighbor (71 times)
will_execute_motion_events=0
send_to_stm32_events=0
motion_events=0
actuator_allowed_events=0
```

Representative controller output:

```text
VIS stable=False frames=1 lon=40.5 lat=-5.0 head=11.4 state=ACTION_REPLANNER -> WAIT
...
VIS stable=True frames=5 lon=40.5 lat=-5.0 head=11.4 state=ACTION_REPLANNER -> ARC D=-6.0 STE=120 V=1
  [no-motion] would send: ARC D=-6.0 STE=120 V=1
```

YOLO/transport evidence:

```text
BOARD_YOLO_RUNTIME_BIN ./sample_parking_yolo_rtsp_conf06_quiet_displayoff
BOARD_YOLO_RUNTIME_CONFIDENCE_THRESHOLD 0.4
parking_yolo_live_infer idx=1 ret=0x0 count=1
parking_yolo_live_infer idx=90 ret=0x0 count=1
UDP tee packets reached 360, forwarding to 127.0.0.1:24580 and 192.168.137.1:24580
```

Post-cleanup state:

```text
no YOLO / tee / controller process
/proc/umap/vb max_pool_cnt=0
/tmp/parking_armed missing
```

Updated verdict:

```text
L1 camera + YOLO + UDP transport: PASS
L2 live YOLO -> slot_relative_state -> action_replanner dry-run: PASS
No-motion safety gate: PASS
Ready for supervised one-step real-motion preparation: CONDITIONALLY YES
```

Important caveat: real movement is still blocked unless the operator explicitly
creates `/tmp/parking_armed`, passes `--arm`, and runs without
`--replanner-dry-run`. The validated next real step from this pose would be the
single short action `ARC D=-6.0 STE=120 V=1`; it must be capped to one step and
followed by stop/observe/replan.
