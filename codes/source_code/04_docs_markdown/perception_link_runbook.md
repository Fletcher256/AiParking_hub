# Perception Link Runbook

## Current Authoritative Baseline: Automatic Perception Route

Date: 2026-06-01

This section is the current baseline for the active parking perception goal.
Older Wi-Fi, Ethernet, and STM32 sections below are retained as historical
notes when they do not match the currently discovered route.

Scope:

- Windows host workspace: `D:\parking_board_agent`
- Board control: COM11 serial when available, otherwise board SSH fallback
- Board network: currently iPhone hotspot on `wlan0`, `172.20.10.2`
- Windows forwarding IP: currently `172.20.10.10`
- Ubuntu VM: ROS2 Humble, SSH/Foxglove at `192.168.247.129`, board-subnet
  receive IP `192.168.137.100`
- Camera: OS08A20 RTSP, currently `rtsp://172.20.10.2:554/live0`
- dToF: SS-LD-AS01 UDP `2368`, official `4873` byte / `40x30` packet
- Foxglove: `ws://192.168.247.129:8765`

Safety boundary:

- This route is perception-only.
- It must not start MCU, CAN, serial actuator, motor, steering, brake,
  throttle, PWM, or chassis-control commands.
- STM32 is disconnected/disabled and was not part of the 2026-06-01 acceptance.

Current discovered route:

```text
board_ip: 172.20.10.2
board_ssid: iPhone
host_forward_ip: 172.20.10.10
vm_ip: 192.168.247.129
vm_board_subnet_ip: 192.168.137.100
rtsp_url: rtsp://172.20.10.2:554/live0
dToF UDP mode: host_forwarder
dToF UDP: board -> 172.20.10.10:2368 -> 192.168.247.129:2368
foxglove_ws_url: ws://192.168.247.129:8765
```

Latest perception-only acceptance:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_122633.json
started: 2026-06-01 12:21:02
finished: 2026-06-01 12:26:33
run_sec: 20
record root: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_122151
session: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_122151/session_20260601_122153
final camera frames: 1132
final dToF metadata rows: 554
final sync rows: 1284
goal-check camera frames: 1799
goal-check dToF metadata rows: 855
goal-check sync rows: 2048
rosbag smoke: /home/ebaina/parking_sensor_records/rosbag_smoke/bag_20260601_122303
rosbag messages: 1137
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
RTSP source audit: tcp_default/tcp_lowdelay BAD_DECODE=0, FLAT=0
RTSP selected receiver: ffmpeg_tcp_default
RTSP null diagnostics: bad_lines=73, dts_warning_lines=6
Foxglove low-bandwidth audit: PASS, 20 checks
STM32 sessions: 0
```

The RTSP null-decode warnings are recorded as diagnostics. The acceptance gate
is based on usable output frames and live ROS/Foxglove behavior: ROS JPEG bad
decode, flat-frame, and gray-frame counts were all zero.

Board-side stable binary:

```text
/opt/sample/official_dtof/sample_dtof_rtsp_stable
sha256: 45b7b597d04d642c7409450861944c47f53cd6cc3d4b7b38a42eb7b939f69892
```

This binary is built from the official `src/dtof` baseline with the current
RTSP and dToF fixes:

- H.264 camera RTSP for current low-latency client compatibility
- GOP shortened to 10
- IDR requested on stream start and client connect
- SPS/PPS/IDR access unit handling fixed for RTSP clients
- one RTP timestamp per encoded access unit
- RTP marker set only on the last non-SEI packet of a frame
- dToF VI pipe attributes preserved so the payload is not flattened to the
  earlier all-2mm/pure-purple failure mode

Rollback binaries retained on the board:

```text
/opt/sample/official_dtof/sample_dtof_rtsp_keepattr
/opt/sample/official_dtof/sample_dtof_rtsp_stable_h264_keygate
/opt/sample/official_dtof/sample_dtof_rtsp_stable_h264_pre_tsfix
/opt/sample/official_dtof/sample_dtof_rtsp_stable_h264_tsfix_nogate
/opt/sample/official_dtof/sample_dtof_rtsp_stable_h265_keepattr
```

Automatic link discovery writes:

```text
artifacts\current_link_config.json
```

Previously verified Ethernet direct route:

```text
board_ip: 192.168.137.2
host_forward_ip: 192.168.137.1
vm_ip: 192.168.247.129
vm_board_subnet_ip: 192.168.137.100
rtsp_url: rtsp://192.168.137.2:554/live0
dToF UDP: 192.168.137.100:2368 (direct_to_vm)
foxglove_ws_url: ws://192.168.247.129:8765
```

Current dToF route selection is automatic. If the VM has an address on the
same subnet as the board, the manager uses a direct board-to-VM route and
skips the Windows UDP forwarder. If it does not, it falls back to the Windows
host-forwarder route.

Use these one-command entry points instead of editing IPs by hand:

```powershell
.venv\Scripts\python tools\perception_link_manager.py discover
.venv\Scripts\python tools\perception_link_manager.py adapt --allow-risk
.venv\Scripts\python tools\perception_link_manager.py health
.venv\Scripts\python tools\perception_link_manager.py latest-session
.venv\Scripts\python tools\perception_link_manager.py stop --allow-risk
```

After changing Ethernet/Wi-Fi/VM networking, run the same `adapt` command
again. It re-discovers the board IP, Windows forwarding IP, VM IP, RTSP URL,
dToF UDP route, and Foxglove URL, then restarts only the perception stack.

Automatic stale-config recovery has been validated with the same path:

```powershell
.venv\Scripts\python tools\perception_link_adapt_recovery_check.py
```

The check intentionally overwrites `artifacts\current_link_config.json` with
bogus IPs, runs `perception_link_manager.py adapt --allow-risk`, then verifies
that the recovered config and live health no longer use stale values.

```text
result: PERCEPTION_LINK_ADAPT_RECOVERY PASS
report: D:\parking_board_agent\artifacts\perception_link_adapt_recovery\adapt_recovery_20260601_031116.json
stale board/host/vm values: 10.255.10.2, 10.255.10.1, 10.255.20.100
recovered board_ip: 192.168.137.2
recovered host_forward_ip: 192.168.137.1
recovered vm_ip: 192.168.247.129
checks: stale_values_removed, camera_ok, dtof_ok, route/forwarder_ok, stm32_disabled
```

COM11 noisy-console recovery:

During a later 10-minute acceptance attempt, the board serial console was
temporarily flooded by Wi-Fi/DHCP kernel logs. The direct COM11 discovery step
then returned an incomplete board result. `tools\perception_link_config.py` now
handles that case in two layers:

- first, it falls back to read-only board SSH discovery through
  `tools\board_auto_ssh.py` when COM11 is noisy or has no parsed addresses;
- second, it preserves and reuses `artifacts\last_good_link_config.json` if a
  discovery is incomplete but the last known board IP still accepts SSH.

This prevents a transient serial-console failure from overwriting the last
known working Ethernet route. A normal successful discovery now writes both:

```text
artifacts\current_link_config.json
artifacts\last_good_link_config.json
```

Post-fix discovery was verified with:

```powershell
.venv\Scripts\python tools\perception_link_manager.py discover
```

```text
result: PASS
board_ip: 192.168.137.2
host_forward_ip: 192.168.137.1
vm_ip: 192.168.247.129
vm_board_subnet_ip: 192.168.137.100
rtsp_url: rtsp://192.168.137.2:554/live0
dToF UDP: 192.168.137.100:2368 (direct_to_vm)
foxglove_ws_url: ws://192.168.247.129:8765
last_good_link_config: present
```

Run the full static acceptance:

```powershell
.venv\Scripts\python tools\perception_link_acceptance.py --run-sec 600 --health-interval-sec 60
```

The acceptance script now discovers the VM host and RTSP URL from
`artifacts\current_link_config.json`; `--vm-host` and `--rtsp-url` are only
manual overrides.

Latest verified 10-minute acceptance with the RTSP quality/latency gate:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_045710.json
started: 2026-06-01 04:43:10
finished: 2026-06-01 04:57:10
run_sec: 600
route mode: direct_to_vm
dToF UDP: board -> 192.168.137.100:2368
host UDP forwarder: skipped
record root: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_044340
session: /home/ebaina/parking_sensor_records/sensor_suite_auto/run_20260601_044340/session_20260601_044341
camera frames at final health: 18366
dToF metadata rows at final health: 10938
sync rows at final health: 21023
camera frames at final goal check: 18926
dToF metadata rows at final goal check: 11271
sync rows at final goal check: 21667
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
RTSP source audit: tcp_default FILES=602 BAD_DECODE=0 FLAT=0; tcp_lowdelay FILES=578 BAD_DECODE=0 FLAT=0
RTSP quality/latency audit: PASS, selected mode=ffmpeg_tcp_lowdelay
ffmpeg_tcp_default: first_frame=1.285s, fps=30.100, bitrate=8417.6kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.217s, fps=27.700, bitrate=7694.3kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.300, flat=3, grayish=3
FFmpeg null decode: NULL_DECODE_BAD_LINES=0, NULL_DTS_WARNING_LINES=9
dToF packet: 4873 bytes, 40x30, expected_shape=True, depth_flat=False, depth_ok=True
dToF depth: valid_pixels=348, unique_count=346, min=2mm, max=8033mm, mean=2182.60mm
Foxglove bridge: running, low-bandwidth audit PASS
Foxglove low-bandwidth report: D:\parking_board_agent\artifacts\foxglove_low_bandwidth_audit\foxglove_low_bandwidth_20260601_045710.json
STM32 sessions: 0
```

Earlier integrated short acceptance with the RTSP quality/latency gate:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_043953.json
started: 2026-06-01 04:35:37
finished: 2026-06-01 04:39:53
run_sec: 20
route mode: direct_to_vm
dToF UDP: board -> 192.168.137.100:2368
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
RTSP source audit: tcp_default FILES=602 BAD_DECODE=0 FLAT=0; tcp_lowdelay FILES=578 BAD_DECODE=0 FLAT=0
RTSP quality/latency audit: PASS
selected RTSP receiver: ffmpeg_tcp_default
ffmpeg_tcp_default: first_frame=1.217s, fps=30.100, bitrate=8698.9kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.217s, fps=27.700, bitrate=7820.8kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.900, flat=9, grayish=9
Foxglove low-bandwidth report: D:\parking_board_agent\artifacts\foxglove_low_bandwidth_audit\foxglove_low_bandwidth_20260601_043953.json
```

Earlier accepted host-forwarder fallback:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_035949.json
dToF UDP: board -> 192.168.137.1:2368 -> 192.168.247.129:2368
UDP forwarder errors: 0
```

Earlier short automatic-discovery acceptance, run without `--vm-host` or
hard-coded RTSP override:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_033156.json
command: .venv\Scripts\python tools\perception_link_acceptance.py --run-sec 20 --health-interval-sec 10 --min-camera-frames 20 --min-dtof-lines 20
discovered RTSP: rtsp://192.168.137.2:554/live0
final camera frames: 681
final dToF metadata rows: 386
final sync rows: 749
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
RTSP source audit: BAD_DECODE=0, FLAT=0
Foxglove low-bandwidth audit: PASS
UDP forwarder errors: 0
```

The acceptance runner now includes this Foxglove-specific gate:

```text
PASS foxglove_low_bandwidth_ok - bridge whitelist active, recommended topics receive messages, point cloud idle
```

It also includes this RTSP receiver-selection gate:

```text
PASS rtsp_quality_latency_ok - RTSP alternatives audited and the selected receiver meets fps/startup/gray-frame thresholds
```

Run the standalone camera quality/latency audit when tuning RTSP receivers:

```powershell
.venv\Scripts\python tools\rtsp_quality_latency_audit.py --seconds 8
```

Latest standalone result:

```text
result: RTSP_QUALITY_LATENCY_AUDIT PASS
report: D:\parking_board_agent\artifacts\rtsp_quality_latency_audit\rtsp_quality_latency_20260601_043500.json
selected mode: ffmpeg_tcp_lowdelay
stream: h264, 3840x2160, nominal 30fps
ffmpeg_tcp_default: first_frame=1.220s, fps=30.125, bitrate=8254.9kbps, bad_decode=0, flat=0, grayish=0
ffmpeg_tcp_lowdelay: first_frame=1.164s, fps=27.125, bitrate=7691.0kbps, bad_decode=0, flat=0, grayish=0
gstreamer_tcp_lowdelay: rejected candidate, fps=0.500, flat=4, grayish=4
```

Current conclusion: use the FFmpeg receiver path for the production ROS2
camera node. GStreamer remains useful for experiments, but the current H.264
pipeline is not the selected stable viewing/recording route.

Standalone low-bandwidth audit:

```powershell
.venv\Scripts\python tools\foxglove_low_bandwidth_audit.py --vm-host 192.168.247.129
```

Latest standalone low-bandwidth report:

```text
result: FOXGLOVE_LOW_BANDWIDTH_AUDIT PASS
report: D:\parking_board_agent\artifacts\foxglove_low_bandwidth_audit\foxglove_low_bandwidth_20260601_042136.json
checks: camera_jpeg, obstacle_view, depth_color, obstacle_blocks, pointcloud idle, bridge whitelist
```

Latest live health snapshot inside the 10-minute acceptance:

```text
time: 2026-06-01 04:19 local
board case7 pid: 13032
board binary: ./sample_dtof_rtsp_stable
VM ROS2 pid: 21602
route mode: direct_to_vm
host UDP forwarder: skipped
VM_CAMERA_FRAMES 18355
VM_DTOF_METADATA_LINES 10991
VM_SYNC_LINES 20977
VM_LAST_CAMERA_OK True
VM_LAST_DTOF_OK True
VM_ANY_BOTH_OK True
VM_STM32_SESSION_COUNT 0
camera health: 30.0 fps
dToF health: transport=True, depth=True, about 18.0 fps
foxglove_ws_url: ws://192.168.247.129:8765
```

Known residual warning:

```text
Application provided invalid, non monotonically increasing dts to muxer
```

This still appears in FFmpeg muxer output during audit, but the same audit
showed no decode/corrupt/no-frame errors and no flat/gray frames. Treat it as a
timestamp-quality warning to improve later, not as the old gray-frame failure.

Foxglove Studio:

1. Open Foxglove Studio on Windows.
2. Choose `Foxglove WebSocket`.
3. Use the discovered URL from `artifacts\current_link_config.json`, currently:

```text
ws://192.168.247.129:8765
```

Use only the low-bandwidth default topics:

```text
/parking/camera/image_jpeg
/parking/dtof/obstacle_view
/parking/dtof/depth_color
/parking/dtof/obstacle_blocks
/parking/sensors/health
/parking/sensors/sync_pair
/tf_static
```

The current one-command path disables `/parking/dtof/points` publishing by
default and the Foxglove bridge whitelist also blocks that topic. Re-enable it
only for an explicit point-cloud experiment with `--publish-pointcloud`.

Avoid subscribing to these in the normal live dashboard:

```text
/parking/camera/image_raw
/parking/dtof/raw_packet
/parking/dtof/points
```

Detailed 2026-06-01 evidence is summarized in:

```text
docs\perception_acceptance_20260601.md
```

Scope: current perception-only camera+dToF stack for:

- Euler Pi / SS928 board, currently `172.20.10.2` on the `iPhone` hotspot
- Ubuntu VM, currently `192.168.247.129` over VMware networking
- Windows host Wi-Fi forwarding address, currently `172.20.10.8`
- OS08A20 RTSP camera
- SS-LD-AS01 dToF UDP packets

Do not use this runbook for chassis control. It does not start MCU bridge, CAN,
serial actuator, motor, steering, brake, throttle, or actuator commands.
The STM32 receive-only path is optional historical work and is disabled by
default for the current phase-1/phase-2 parking goal.

## Baseline

Board-side camera + dToF baseline:

```text
/opt/sample/official_dtof/sample_dtof_rtsp 7 <udp_destination_ip>
```

For the current board, `tools/wifi_sensor_suite_manager.py` prefers the fixed
binary below when present:

```text
/opt/sample/official_dtof/sample_dtof_rtsp_keepattr
```

That binary keeps the official dToF VI pipe attributes (`pixfmt=21`,
`compress=4`) and fixes the earlier flat-depth/pure-purple symptom.

For the current pure-wireless route, `<udp_destination_ip>` is the Windows Wi-Fi
address `172.20.10.8`; the host forwards UDP `2368` into the VM at
`192.168.247.129:2368`.

Do not use `/opt_sample` as the baseline. It is only an archive of previous
experiments.

VM ROS2 package:

```text
/home/ebaina/parking_ws/src/parking_bridge
```

Host workspace:

```text
D:\parking_board_agent
```

## Quick Audit

Use this first for the current perception-only camera+dToF phase-1/phase-2
goal:

```powershell
.venv\Scripts\python tools\perception_phase12_status.py
```

Latest verified result:

```text
PERCEPTION_PHASE12_STATUS PASS
report: D:\parking_board_agent\artifacts\perception_phase12_status\status_20260531_024359.json
```

It checks the active wireless path, board case7, VM ROS2 topics, official dToF
packet shape, rosbag replay, Foxglove-lite/WebSocket visualization, dashboard
rendering, Windows `172.20.10.8` being on `WLAN`, and the absence of forbidden
motion-control processes.

The older broad link audit is still useful after reboot, USB replug, or moving
to another PC/VM setup:

```powershell
.venv\Scripts\python tools\parking_link_audit.py
```

Expected current result is `PARKING_LINK_AUDIT WARN`, not `PASS`, because the
USB serial adapter is still using `generic_fallback` instead of formal
`ch341`.

For the current perception-only Wi-Fi goal, the useful pass criteria are:

- board SSH works on the current Wi-Fi IP, normally `172.20.10.2`
- VM SSH works
- ROS2 workspace is present
- latest camera + dToF records exist
- no residual sensor process is running after stop
- no forbidden control process is running

The older wired `192.168.137.2` and STM32 receive-only checks are historical
diagnostics. They are not required for the current "look and record only"
camera+dToF goal.

The audit writes JSON reports to:

```text
artifacts\parking_link_audit\audit_YYYYmmdd_HHMMSS.json
```

## Same Wi-Fi Board Control

When the Windows host and the board are connected to the same Wi-Fi or phone
hotspot, use automatic SSH discovery instead of a fixed board IP:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py discover
.venv\Scripts\python tools\board_auto_ssh.py run "whoami; uname -a"
```

The discovery path scans active local IPv4 networks and the ARP cache, then
verifies the board over SSH as `root` / `ebaina`. It prioritizes the observed
board Wi-Fi MAC:

```text
38:7a:cc:e9:db:1a
```

Latest verified same-hotspot route:

```text
host board: 172.20.10.2
host interface: iPhone hotspot / Apple Mobile Device Ethernet
board ssid: iPhone
result: SSH ok, whoami=root
```

This is a control path only. It does not prove the VM receive path for
camera+dToF+STM32 UDP until the VM address and board-to-VM routing are also
validated.

## Same Wi-Fi Perception-Only Sensor Link

Use this route when the board Ethernet cable is unplugged and the board plus
Windows host are on the same Wi-Fi or phone hotspot. The VM is still controlled
over VMware NAT/host-only SSH, so the board sends UDP to the Windows host and
the host forwards those packets to the VM.

Current verified pure-wireless topology:

```text
board wlan0: 172.20.10.2 on ssid iPhone
Windows host WLAN IP: 172.20.10.8
VM SSH/UDP target: 192.168.247.129
camera RTSP URL: rtsp://172.20.10.2:554/live0
dToF UDP: board -> 172.20.10.8:2368 -> 192.168.247.129:2368
```

Start the adapted perception-only chain:

```powershell
.venv\Scripts\python tools\wifi_sensor_suite_manager.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 start --allow-risk
```

Check live health:

```powershell
.venv\Scripts\python tools\wifi_sensor_suite_manager.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 health
```

Stop cleanly:

```powershell
.venv\Scripts\python tools\wifi_sensor_suite_manager.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 stop --allow-risk
```

Summarize latest Wi-Fi records:

```powershell
.venv\Scripts\python tools\wifi_sensor_suite_manager.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 latest-session
```

Latest verified perception-only Wi-Fi run:

```text
/home/ebaina/parking_sensor_records/sensor_suite_wifi/run_20260531_020207
session: /home/ebaina/parking_sensor_records/sensor_suite_wifi/run_20260531_020207/session_20260531_020208
camera frames: 2359 at the last health check
dToF metadata rows: 1168 at the last health check
sync pairs: 3041 at the last health check
rosbag smoke: /home/ebaina/parking_sensor_records/rosbag_smoke/bag_20260531_020306
```

During the live health check the host UDP forwarder reported `0` errors and
only one forwarding rule:

```text
dToF: board 172.20.10.2 -> host 172.20.10.8:2368 -> VM 192.168.247.129:2368
```

This path uses `/opt/sample/official_dtof/sample_dtof_rtsp_keepattr 7` on the
board when available, receives RTSP directly from the board Wi-Fi IP, and does
not start STM32, MCU, CAN, motor, steering, brake, throttle, or actuator
processes. Pass
`--enable-stm32` only for an explicitly approved STM32 receive-only diagnostic,
not for the current perception-only parking goal.

Current dToF health semantics:

```text
dToF transport: true when UDP packets arrive recently and match 4873-byte/40x30
dToF depth: true only when enough pixels are above the valid-depth threshold
current result: transport_ok=True, depth_ok=True
```

The earlier invalid-depth symptom was a flat official payload at depth `2mm`.
The keepattr board binary fixes that symptom in the current run.

For a browser preview on the VM:

```powershell
.venv\Scripts\python tools\wifi_live_preview_control.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 --camera-backend ffmpeg_mjpeg --camera-scale 0.25 --preview-stride 3 start
```

Open:

```text
http://192.168.247.129:8090/
```

Check Foxglove bridge availability without installing anything:

```powershell
.venv\Scripts\python tools\foxglove_bridge_control.py --vm-host 192.168.247.129 status
```

Current Foxglove result:

```text
FOXGLOVE_BRIDGE_INSTALLED no
RECOMMENDED_PACKAGE ros-humble-foxglove-bridge
```

The current low-latency ROS camera receiver uses `camera_backend=ffmpeg_mjpeg`
and publishes sensor topics with ROS2 `sensor_data` QoS. The latest rosbag2
smoke test recorded 441 camera JPEG frames and 102 dToF depth frames in 5.699 s.

Verify rosbag2 playback in an isolated DDS domain:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --host 192.168.247.129 --timeout 60 put-text --allow-risk tools\vm_rosbag_replay_check.sh /tmp/vm_rosbag_replay_check.sh
.venv\Scripts\python tools\vm_ssh_run.py --host 192.168.247.129 --timeout 90 run "bash /tmp/vm_rosbag_replay_check.sh"
```

Expected current result:

```text
REPLAY_CAMERA_RC 0
REPLAY_DEPTH_RC 0
REPLAY_HEALTH_RC 0
```

Use the no-install Foxglove-compatible endpoint when the official
`foxglove_bridge` package is missing:

```powershell
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 start
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 status
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 stop
```

Connect Foxglove Studio to:

```text
ws://192.168.247.129:8765
```

Verify the endpoint without Foxglove Studio:

```powershell
.venv\Scripts\python tools\foxglove_lite_probe.py --url ws://192.168.247.129:8765 --listen-sec 12 --require-all
```

Expected probe evidence:

```text
TEXT_OP serverInfo
TEXT_OP advertise
TEXT_OP status
MESSAGE_DATA /parking/camera/image
MESSAGE_DATA /parking/dtof/preview
MESSAGE_DATA /parking/preview/composite
MESSAGE_DATA /parking/dtof/points_lite
MESSAGE_DATA /parking/sensors/health_lite
MESSAGE_DATA /parking/dtof/metadata_lite
```

Use the local browser dashboard HTML when Foxglove Studio is unavailable:

```text
D:\parking_board_agent\tools\foxglove_lite_dashboard.html
```

Generate a VM-rendered dashboard evidence image from the same WebSocket stream:

```powershell
.venv\Scripts\python tools\foxglove_lite_visual_check.py --host 192.168.247.129
```

Latest render output:

```text
D:\parking_board_agent\logs\foxglove_lite_render_latest.png
```

After `foxglove_bridge` is installed, start the bridge:

```powershell
.venv\Scripts\python tools\foxglove_bridge_control.py --vm-host 192.168.247.129 start
```

Connect Foxglove Studio/browser to:

```text
ws://192.168.247.129:8765
```

For the current status report and Foxglove/RViz2 notes, see:

```text
docs\perception_phase1_phase2_status.md
```

For the current perception-only goal, use:

```powershell
.venv\Scripts\python tools\perception_phase12_status.py
```

Latest verified status:

```text
PERCEPTION_PHASE12_STATUS PASS
report: D:\parking_board_agent\artifacts\perception_phase12_status\status_20260531_024359.json
```

`tools\parking_goal_status.py` is legacy for the earlier STM32/CH341-inclusive
receive-only route and can report FAIL against the current narrower camera+dToF
goal because it still expects wired `192.168.137.x` and CH341 evidence.

## Acceptance Run

Use this when you need a single command to prove start, live receiving, clean
stop, and post-stop audit:

```powershell
.venv\Scripts\python tools\parking_link_acceptance.py --run-sec 35
```

Latest verified acceptance run:

```text
report: D:\parking_board_agent\artifacts\parking_link_acceptance\acceptance_20260530_180557.json
record root: /home/ebaina/parking_sensor_records/sensor_suite_live/run_20260530_180454
result: PARKING_LINK_ACCEPTANCE WARN
camera frames: 53
dToF metadata rows: 598
sync pairs: 86
STM32 raw bytes: 62464
```

`WARN` is the expected current status because the CH340/CH341 adapter is still
using `usbserial_generic` fallback and the matching `4.19.90` kernel build
inputs for the formal CH341 route are still missing. Functional acceptance items
passed, and no forbidden control process was found.

## Full Receive-Only Run

Deploy after code changes:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py deploy --allow-risk
```

Start camera + dToF + STM32 receive-only chain:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py start --allow-risk
```

Check live health:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py health
```

Stop cleanly:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py stop --allow-risk
```

Summarize latest records:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py latest-session
```

Latest verified full run:

```text
/home/ebaina/parking_sensor_records/sensor_suite_live/run_20260530_180454
camera frames: 53
dToF metadata rows: 598
sync pairs: 86
STM32 raw bytes: 62464
STM32 classification: binary_with_nul / binary
```

## STM32-Only Run

Use this when isolating the USB serial path:

```powershell
.venv\Scripts\python tools\stm32_link_manager.py start --allow-risk
.venv\Scripts\python tools\stm32_link_manager.py health
.venv\Scripts\python tools\stm32_link_manager.py stop --allow-risk
.venv\Scripts\python tools\stm32_link_manager.py latest-analysis
```

The board-side bridge is receive-only. It reads from the USB serial adapter and
sends UDP packets to the VM. It never writes bytes back to the STM32 serial
port.

## Record Layout

Full sensor records:

```text
/home/ebaina/parking_sensor_records/sensor_suite_live/run_*
```

Important files:

```text
session_*/camera_frames/*.jpg
session_*/dtof_packets.bin
session_*/dtof_metadata.jsonl
session_*/dtof_depth_npy/*.npy
session_*/dtof_preview/*.png
session_*/sync_pairs.jsonl
session_*/health.jsonl
stm32_session_*/stm32_serial_raw.bin
stm32_session_*/stm32_serial_chunks.jsonl
stm32_session_*/stm32_health.jsonl
stm32_session_*/stm32_protocol_analysis.json
```

STM32-only records:

```text
/home/ebaina/parking_sensor_records/stm32_ros_live/run_*
/home/ebaina/parking_sensor_records/stm32_ros_check/run_*
```

## After Reboot Or USB Replug

1. Keep Ethernet wiring and VM network on `192.168.137.0/24`.
2. Confirm COM11 is not open in MobaXterm or another serial tool.
3. Run the post-replug validation:

```powershell
.venv\Scripts\python tools\post_replug_validation.py
```

Latest verified post-replug validation command and result:

```text
.venv\Scripts\python tools\post_replug_validation.py --stm32-vm-duration-sec 25 --stm32-board-duration-sec 15
POST_REPLUG_VALIDATION WARN
report: D:\parking_board_agent\artifacts\post_replug_validation\post_replug_20260530_180414.json
STM32 raw bytes: 36096
STM32 classification: binary_with_nul / binary
```

This latest run was executed after a user-confirmed physical board reboot. It
validates COM11, VM SSH, wired board IP, `/dev/ttyUSB0`, STM32 receive-only UDP
forwarding, VM ROS2 recording, latest protocol analysis, no residual sensor
processes, and no forbidden control processes. It does not start camera+dToF by
default. Add `--full-sensor` only when you also want the full
camera+dToF+STM32 acceptance run.

4. If board USB serial is missing, run the board-side USB status check:

```powershell
.venv\Scripts\python tools\board_serial.py --login-password "ebaina" run --allow-risk "sh /etc/udev/ch341-autobind.sh; cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true"
```

This helper only binds the USB serial receive path and records status. It does
not write to STM32. The current expected driver mode is:

```text
driver=generic
driver_mode=generic_fallback
```

5. If you need live camera+dToF confirmation too, run the full receive-only
   chain and stop it:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py start --allow-risk
.venv\Scripts\python tools\sensor_suite_manager.py health
.venv\Scripts\python tools\sensor_suite_manager.py stop --allow-risk
```

6. Run the audit again. It should return `WARN` only for the temporary
   `generic_fallback` driver and the formal CH341 gap.

The board now has two boot-time helpers for this route:

```text
/etc/init.d/S81wired137
/etc/init.d/S99parkinglink
```

`S99parkinglink` runs late in boot, re-applies the wired `192.168.137.2/24`
address, and runs the USB serial status helper. Its boot log is:

```text
/tmp/parking_link_init.log
```

## Migration Checklist

To move to another Windows host or VM:

- Copy `D:\parking_board_agent` or clone the same workspace.
- Keep `.venv` dependencies available, or recreate them with Python packages
  used by `tools/board_serial.py` and `tools/vm_ssh_run.py` (`pyserial`,
  `paramiko`).
- Keep the board on COM11 or pass `--board-port`.
- Keep VM SSH reachable, currently at `192.168.247.129`.
- For the lowest-latency Ethernet dToF route, keep a VM address on the board
  subnet too, currently `192.168.137.100`.
- If the board and Windows host are on the same Wi-Fi/hotspot, verify board
  control with:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py discover
.venv\Scripts\python tools\board_auto_ssh.py run "whoami"
```

- If the VM is not on the board subnet, the manager will use the
  host-forwarded route instead:

```powershell
.venv\Scripts\python tools\perception_link_manager.py adapt --allow-risk
.venv\Scripts\python tools\perception_link_manager.py health
.venv\Scripts\python tools\perception_link_manager.py stop --allow-risk
```

- Deploy ROS2 package to the VM:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py deploy --allow-risk
```

- Verify with:

```powershell
.venv\Scripts\python tools\post_replug_validation.py
```

The board-side persistent pieces expected after migration are:

```text
/opt/sample/official_dtof/sample_dtof_rtsp
/etc/init.d/S81wired137
/etc/init.d/S99parkinglink
/etc/udev/ch341-autobind.sh
/etc/udev/rules.d/98-ch341-autobind.rules
```

## Formal CH341 Gap

The current working route is acceptable for bounded receive-only validation but
is not the formal driver solution:

```text
VID:PID 1a86:7523
device /dev/ttyUSB0
driver generic
driver_mode generic_fallback
```

The formal route requires one of:

- board image/kernel with `CONFIG_USB_SERIAL_CH341=y`
- matching SS928 board `4.19.90` kernel headers/build tree so the official WCH
  `ch341.ko` can be built for the running kernel

Current evidence is intentionally conservative:

- board boot args include `root=/dev/mmcblk0p5`, so the active board image is
  an eMMC-style boot
- the local official HiEuler hardware-driver patch has
  `hieulerpi1_defconfig: CONFIG_USB_SERIAL_CH341=y`
- the same patch has
  `ss928v100_emmc_defconfig: # CONFIG_USB_SERIAL_CH341 is not set`
- the running board exposes only `/sys/bus/usb-serial/drivers/generic` and
  `/sys/bus/usb-serial/drivers/option1`
- no `ch341.ko` or matching `4.19.90` build tree is currently present

Read-only readiness check:

```powershell
.venv\Scripts\python tools\ch341_readiness_check.py
```

Guarded build helper after obtaining matching kernel inputs:

```powershell
.venv\Scripts\python tools\build_ch341_for_board.py --kernel-dir /path/to/ss928-4.19.90-kernel-build --allow-risk
```

The build helper refuses wrong-kernel inputs.

Official references tracked locally:

- WCH official CH341 Linux driver source:
  `vendor/WCHSoftGroup_ch341ser_linux`
  (`https://github.com/WCHSoftGroup/ch341ser_linux`)
- HiEuler hardware-driver patch material:
  `vendor/HiEuler_hardware_driver_unzip/hardware_driver-master/linux/5.10.0-153.28.0.patch`
  (`https://gitee.com/HiEuler/hardware_driver`)
- HiEuler firmware-building metadata:
  `vendor/HiEuler_PI_Firmware_Building_unzip/HiEuler_PI_Firmware_Building-master/opt/*/cfg/dev_info.config`
