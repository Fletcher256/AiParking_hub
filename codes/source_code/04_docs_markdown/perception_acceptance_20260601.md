# Perception Acceptance Evidence

Date: 2026-06-01

Scope: static, perception-only validation for the OS08A20 camera plus
SS-LD-AS01 dToF chain. No MCU, CAN, serial actuator, motor, steering, brake,
throttle, PWM, or chassis-control path was started.

## Latest Acceptance With Vision Preprocessing

The latest accepted route is the current phone-hotspot/host-forwarded
perception stack, with ROS2 visual preprocessing enabled and STM32 disconnected.

```text
PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_122633.json
started: 2026-06-01 12:21:02
finished: 2026-06-01 12:26:33
run_sec: 20
board_ip: 172.20.10.2
host_forward_ip: 172.20.10.10
vm_ip: 192.168.247.129
rtsp_url: rtsp://172.20.10.2:554/live0
dToF UDP: board -> 172.20.10.10:2368 -> 192.168.247.129:2368
foxglove_ws_url: ws://192.168.247.129:8765
```

Final live health:

```text
VM_CAMERA_FRAMES 1132
VM_DTOF_METADATA_LINES 554
VM_SYNC_LINES 1284
VM_LAST_CAMERA_OK True
VM_LAST_DTOF_OK True
VM_ANY_BOTH_OK True
VM_STM32_SESSION_COUNT 0
```

Goal-check session evidence:

```text
record root: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_122151
session: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_122151/session_20260601_122153
CAMERA_FRAMES 1799
DTOF_METADATA_LINES 855
SYNC_LINES 2048
PREVIEW_FILES 57
```

dToF packet/depth evidence:

```text
packet_size 4873
expected_packet_size 4873
width 40
height 30
pixel_number 1200
expected_shape True
depth_valid_pixels 408
depth_unique_count 391
depth_flat False
depth_ok True
depth_min_mm 2
depth_max_mm 8007
depth_mean_mm 2811.4522
```

ROS2 and Foxglove evidence:

```text
/parking/camera/image_jpeg
/parking/dtof/depth_color
/parking/dtof/obstacle_view
/parking/dtof/obstacle_blocks
/parking/sensors/health
/parking/sensors/sync_pair
/parking/vision/line_debug
/parking/parking_slot_candidates
/parking/perception/state
motion_enabled=false
actuator_control_allowed=false
FOXGLOVE_LOW_BANDWIDTH_AUDIT PASS
FOXGLOVE_LOW_BANDWIDTH_AUDIT_PASS_COUNT 20
```

Recording and replay evidence:

```text
rosbag: /home/ebaina/parking_sensor_records/rosbag_smoke/bag_20260601_122303
messages: 1137
/parking/camera/image_jpeg: 231
/parking/dtof/depth: 128
/parking/dtof/depth_color: 64
/parking/dtof/obstacle_view: 64
/parking/dtof/obstacle_blocks: 128
/parking/sensors/sync_pair: 275
/parking/parking_slot_candidates: 77
/parking/perception/state: 85
/parking/vision/line_debug: 77
ROSBAG_REPLAY_CHECK PASS
```

Camera quality evidence:

```text
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
RTSP capture audit: tcp_default BAD_DECODE=0 FLAT=0
RTSP capture audit: tcp_lowdelay BAD_DECODE=0 FLAT=0
RTSP quality/latency: PASS
selected receiver: ffmpeg_tcp_default
acceptance gate: camera_quality_and_rtsp_diagnostics_ok
ffmpeg_tcp_default: first_frame=1.726s, fps=29.300, bitrate=8618.3kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=2.027s, fps=27.700, bitrate=7139.0kbps, bad_decode=0, flat=0, grayish=0
```

RTSP null-decode diagnostic evidence:

```text
NULL_DECODE_RC=0
NULL_DECODE_BAD_LINES=73
NULL_DTS_WARNING_LINES=6
```

These H.264 warnings are retained in the report because they are useful for
future board-side timestamp/stream polish. They did not create bad ROS JPEG
frames, flat frames, gray frames, failed dToF, failed rosbag replay, or failed
Foxglove output in this acceptance run.

## Earlier Ethernet Topology

Earlier automatically discovered COM11 plus Ethernet link:

```text
board_ip: 192.168.137.2
board_interface: eth0
vm_ssh_ip: 192.168.247.129
vm_board_subnet_ip: 192.168.137.100
host_forward_ip: 192.168.137.1
rtsp_url: rtsp://192.168.137.2:554/live0
dToF UDP mode: direct_to_vm
dToF UDP: board -> 192.168.137.100:2368
foxglove_ws_url: ws://192.168.247.129:8765
```

The manager now prefers `direct_to_vm` when the VM has an address on the same
subnet as the board. The Windows UDP forwarder is kept as fallback for Wi-Fi or
VM NAT-only layouts, but it is not used on the current Ethernet route.

Authoritative state files:

```text
D:\parking_board_agent\artifacts\current_link_config.json
D:\parking_board_agent\artifacts\last_good_link_config.json
```

Earlier Ethernet 10-minute acceptance report:

```text
D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_045710.json
```

Earlier short acceptance report with the newly integrated RTSP
quality/latency gate:

```text
D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_043953.json
```

## Board Binary

Current board binary:

```text
/opt/sample/official_dtof/sample_dtof_rtsp_stable
sha256: 45b7b597d04d642c7409450861944c47f53cd6cc3d4b7b38a42eb7b939f69892
size: 4550632
```

Board log evidence:

```text
BOARD_CASE7_BINARY ./sample_dtof_rtsp_stable
camera rtsp stable ready: codec=h264 gop=10
[DTOF_DBG] keep vi_pipe 1 attr pixfmt=21 compress=4
RTSP client connected 192.168.137.100
```

This proves the current run used the H.264 stable binary and preserved the
dToF VI pipe attributes that are needed to avoid the earlier flat-depth view.

## 10-Minute Acceptance Result

Command:

```powershell
.venv\Scripts\python tools\perception_link_acceptance.py --run-sec 600 --health-interval-sec 60 --min-camera-frames 1000 --min-dtof-lines 1000
```

Result:

```text
PERCEPTION_LINK_ACCEPTANCE PASS
started: 2026-06-01 04:43:10
finished: 2026-06-01 04:57:10
run_sec: 600
```

The acceptance runner checked:

```text
PASS adapt_exit_code
PASS final_health_exit_code
PASS discovered_rtsp_url
PASS camera_ok
PASS dtof_ok
PASS dtof_udp_route_ok - direct_to_vm target=192.168.137.100
PASS stm32_disabled
PASS camera_frames_min - 18355 >= 1000
PASS dtof_lines_min - 10991 >= 1000
PASS camera_audit_no_bad_decode
PASS camera_audit_no_flat
PASS camera_audit_no_grayish
PASS rtsp_capture_no_bad_decode
PASS rtsp_capture_no_flat
PASS rtsp_null_no_decode_errors
PASS rtsp_quality_latency_ok
PASS foxglove_status_ok
PASS foxglove_low_bandwidth_ok
```

Final health evidence:

```text
VM_CAMERA_FRAMES 18366
VM_DTOF_METADATA_LINES 10938
VM_SYNC_LINES 21023
VM_LAST_CAMERA_OK True
VM_LAST_DTOF_OK True
VM_ANY_BOTH_OK True
VM_STM32_SESSION_COUNT 0
HOST_FORWARDER_SKIPPED_DIRECT_ROUTE yes
```

Final goal-check record evidence:

```text
record root: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_044340
session: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_044340/session_20260601_044341
CAMERA_FRAMES 18926
DTOF_METADATA_LINES 11271
SYNC_LINES 21667
PREVIEW_FILES 751
```

ROS camera frame audit:

```text
FILES 1000
BAD_DECODE 0
FLAT_COUNT 0
GRAYISH_COUNT 0
MEAN_RANGE 59.6171 .. 120.9332
LUMA_STD_RANGE 15.3993 .. 40.7705
COLOR_DELTA_RANGE 13.0359 .. 22.9130
SIZE_RANGE 34719 .. 116601
```

RTSP source capture audit:

```text
tcp_default: FILES 602, BAD_DECODE 0, FLAT 0
tcp_lowdelay: FILES 578, BAD_DECODE 0, FLAT 0
```

FFmpeg null decode audit:

```text
NULL_DECODE_RC=0
NULL_DECODE_BAD_LINES=0
NULL_DTS_WARNING_LINES=9
```

dToF packet and depth evidence:

```text
packet_size 4873
expected_packet_size 4873
width 40
height 30
pixel_number 1200
expected_shape True
depth_valid_pixels 348
depth_unique_count 346
depth_flat False
depth_ok True
depth_min_mm 2
depth_max_mm 8033
depth_mean_mm 2182.5965
```

Foxglove bridge evidence:

```text
FOXGLOVE_BRIDGE_INSTALLED yes
FOXGLOVE_BRIDGE_RUNNING yes
FOXGLOVE_BRIDGE_PID 3202
WS_URL ws://192.168.247.129:8765
LOW_BANDWIDTH_AUDIT PASS
LOW_BANDWIDTH_REPORT D:\parking_board_agent\artifacts\foxglove_low_bandwidth_audit\foxglove_low_bandwidth_20260601_045710.json
```

## RTSP Quality and Latency Gate

Standalone audit command:

```powershell
.venv\Scripts\python tools\rtsp_quality_latency_audit.py --seconds 8
```

Standalone report:

```text
D:\parking_board_agent\artifacts\rtsp_quality_latency_audit\rtsp_quality_latency_20260601_043500.json
```

Result:

```text
RTSP_QUALITY_LATENCY_AUDIT PASS
stream codec: h264
stream size: 3840x2160
source nominal fps: 30
selected mode: ffmpeg_tcp_lowdelay
ffmpeg_tcp_default: first_frame=1.220s, fps=30.125, bitrate=8254.9kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.164s, fps=27.125, bitrate=7691.0kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.500, flat=4, grayish=4
```

The acceptance runner now includes the same class of check:

```text
PASS rtsp_quality_latency_ok - RTSP alternatives audited and the selected receiver meets fps/startup/gray-frame thresholds
```

Integrated short acceptance evidence:

```text
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_043953.json
started: 2026-06-01 04:35:37
finished: 2026-06-01 04:39:53
overall: PASS
selected RTSP receiver in this run: ffmpeg_tcp_default
ffmpeg_tcp_default: first_frame=1.217s, fps=30.100, bitrate=8698.9kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.217s, fps=27.700, bitrate=7820.8kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.900, flat=9, grayish=9
```

Integrated 10-minute acceptance evidence:

```text
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_045710.json
started: 2026-06-01 04:43:10
finished: 2026-06-01 04:57:10
overall: PASS
selected RTSP receiver in this run: ffmpeg_tcp_lowdelay
ffmpeg_tcp_default: first_frame=1.285s, fps=30.100, bitrate=8417.6kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.217s, fps=27.700, bitrate=7694.3kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.300, flat=3, grayish=3
```

Current conclusion: the production ROS2 camera receiver should stay on the
FFmpeg path. The GStreamer H.264 candidate is documented and tested, but it is
not the current stable route because it produced flat/gray candidate frames in
the audit.

Default low-bandwidth whitelist:

```text
/parking/camera/image_jpeg
/parking/dtof/obstacle_view
/parking/dtof/depth_color
/parking/dtof/obstacle_blocks
/parking/sensors/health
/parking/sensors/sync_pair
/tf_static
/rosout
/foxglove_bridge/sysinfo
```

## Commands

Use these commands for the current active goal:

```powershell
.venv\Scripts\python tools\perception_link_manager.py discover
.venv\Scripts\python tools\perception_link_manager.py adapt --allow-risk
.venv\Scripts\python tools\perception_link_manager.py health
.venv\Scripts\python tools\perception_link_manager.py latest-session
.venv\Scripts\python tools\foxglove_bridge_control.py --vm-host 192.168.247.129 status
.venv\Scripts\python tools\rtsp_quality_latency_audit.py --seconds 8
.venv\Scripts\python tools\perception_link_acceptance.py --run-sec 600 --health-interval-sec 60
```

After a network change, run:

```powershell
.venv\Scripts\python tools\perception_link_manager.py adapt --allow-risk
```

Do not edit hard-coded IPs for normal recovery. The manager re-discovers the
board IP, VM IP, host forwarding IP, RTSP URL, dToF UDP route, and Foxglove URL
and writes them to `artifacts\current_link_config.json`.

## Automatic Network Adaptation Evidence

Stale-config recovery command:

```powershell
.venv\Scripts\python tools\perception_link_adapt_recovery_check.py
```

This validation intentionally wrote impossible old network values into the
state file, then used the normal `adapt` path to recover the active COM11 plus
Ethernet route.

```text
PERCEPTION_LINK_ADAPT_RECOVERY PASS
report: D:\parking_board_agent\artifacts\perception_link_adapt_recovery\adapt_recovery_20260601_031116.json
stale board_ip: 10.255.10.2
stale host_forward_ip: 10.255.10.1
stale vm_ip: 10.255.20.100
recovered board_ip: 192.168.137.2
recovered host_forward_ip: 192.168.137.1
recovered vm_ip: 192.168.247.129
```

COM11 noisy-console recovery:

```text
primary discovery: COM11 serial
fallback discovery: read-only board SSH via tools\board_auto_ssh.py
state protection: artifacts\last_good_link_config.json
recovery rule: reuse last good route only when the last board IP still accepts SSH
```

Direct-route adaptation added after the earlier host-forwarded run:

```text
VM addresses discovered: 192.168.247.129, 192.168.137.100
selected dToF route: direct_to_vm
board dToF target: 192.168.137.100:2368
host UDP forwarder: skipped
```

Earlier accepted fallback route:

```text
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_035949.json
mode: host_forwarder
dToF UDP: board -> 192.168.137.1:2368 -> 192.168.247.129:2368
result: PERCEPTION_LINK_ACCEPTANCE PASS
```

## Known Residual Issue

FFmpeg still reports non-monotonic DTS warnings during RTSP audit:

```text
Application provided invalid, non monotonically increasing dts to muxer
```

Current evidence shows this is not producing gray frames or decode failures:

```text
BAD_DECODE 0
FLAT 0
GRAYISH_COUNT 0
NULL_DECODE_BAD_LINES 0
```

Keep this as a future timestamp-polish item. It is not the original gray-frame
failure and did not fail the 10-minute acceptance.

## Safety Notes

The accepted path starts only:

- board official camera+dToF sample
- VM ROS2 receive/record node
- VM Foxglove bridge
- Windows UDP forwarder only when the route mode requires host forwarding

It does not start STM32, MCU, CAN, serial actuator, motor, steering, brake,
throttle, PWM, or any chassis-control process.
