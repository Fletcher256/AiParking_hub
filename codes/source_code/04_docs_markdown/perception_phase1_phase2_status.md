# Perception Phase 1-2 Status

Current note: this file records the older 2026-05-31 wireless phase-1/phase-2
status. The active 2026-06-01 goal is now documented in
`docs\perception_link_runbook.md` and
`docs\perception_acceptance_20260601.md`. The latest accepted route is the
iPhone-hotspot host-forwarded perception stack:

```text
result: PERCEPTION_LINK_ACCEPTANCE PASS
report: D:\parking_board_agent\artifacts\perception_link_acceptance\perception_acceptance_20260601_122633.json
board_ip: 172.20.10.2
host_forward_ip: 172.20.10.10
vm_ip: 192.168.247.129
rtsp_url: rtsp://172.20.10.2:554/live0
Foxglove: ws://192.168.247.129:8765
ROS JPEG audit: BAD_DECODE=0, FLAT_COUNT=0, GRAYISH_COUNT=0
rosbag replay: PASS
vision preprocessing: /parking/vision/line_debug, /parking/parking_slot_candidates, /parking/perception/state
STM32 sessions: 0
```

Date: 2026-05-31

Scope: perception-only bring-up for the intelligent parking project. This
status covers OS08A20 camera RTSP, SS-LD-AS01 dToF UDP, ROS2 receive/record,
live preview, rosbag2 smoke verification, and Foxglove readiness. It explicitly
excludes MCU, CAN, serial actuator, motor, steering, brake, throttle, PWM, and
chassis control.

## Safety Boundary

The active workflow is "look and record only".

Do not start or test any command that can move the car. The Wi-Fi perception
manager starts only camera+dToF by default. The STM32 receive-only path is
disabled unless `--enable-stm32` is passed explicitly, and it must not be used
for the current phase-1/phase-2 goal.

## Current Wireless Topology

Verified pure wireless host-to-board path:

```text
Windows WLAN SSID: iPhone
Windows WLAN IP: 172.20.10.8/28
Board wlan0 IP: 172.20.10.2
VM IP: 192.168.247.129
Camera RTSP: rtsp://172.20.10.2:554/live0
dToF UDP: board -> 172.20.10.8:2368 -> 192.168.247.129:2368
```

The live run used only one host UDP forwarding rule:

```text
172.20.10.8:2368 -> 192.168.247.129:2368
```

No STM32, CAN, motor, steering, brake, throttle, or actuator process was
started.

## Start, Status, Stop

Start the low-latency live perception preview:

```powershell
.venv\Scripts\python tools\wifi_live_preview_control.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 --camera-backend ffmpeg_mjpeg --camera-scale 0.25 --preview-stride 3 start
```

Check health:

```powershell
.venv\Scripts\python tools\wifi_sensor_suite_manager.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 health
```

Stop cleanly:

```powershell
.venv\Scripts\python tools\wifi_live_preview_control.py --vm-host 192.168.247.129 --board-host 172.20.10.2 --host-forward-ip 172.20.10.8 stop
```

Viewer URL:

```text
http://192.168.247.129:8090/
```

Latest local preview snapshot:

```text
D:\parking_board_agent\logs\wifi_live_preview_latest.jpg
```

## Current Verified Live Run

Current phase-1/phase-2 acceptance audit:

```powershell
.venv\Scripts\python tools\perception_phase12_status.py
```

Latest result:

```text
PERCEPTION_PHASE12_STATUS PASS
report: D:\parking_board_agent\artifacts\perception_phase12_status\status_20260531_024359.json
```

Record root:

```text
/home/ebaina/parking_sensor_records/sensor_suite_wifi/run_20260531_020207
```

Session:

```text
/home/ebaina/parking_sensor_records/sensor_suite_wifi/run_20260531_020207/session_20260531_020208
```

Board evidence:

```text
ssid=iPhone
ip_address=172.20.10.2
BOARD_CASE7_RUNNING yes
BOARD_CASE7_BINARY ./sample_dtof_rtsp_keepattr
RTSP client connected 172.20.10.8
[DTOF_DBG] keep vi_pipe 1 attr pixfmt=21 compress=4
```

VM evidence:

```text
camera_backend=ffmpeg_mjpeg
publish_camera_raw=False
VM_CAMERA_FRAMES 73763
VM_DTOF_METADATA_LINES 42069
VM_SYNC_LINES 93866
VM_LAST_CAMERA_OK True
VM_LAST_DTOF_OK True
VM_ANY_BOTH_OK True
VM_STM32_SESSION_COUNT 0
```

ROS topics:

```text
/parking/camera/image_jpeg
/parking/camera/image_raw
/parking/dtof/camera_info
/parking/dtof/confidence
/parking/dtof/depth
/parking/dtof/points
/parking/dtof/raw_packet
/parking/sensors/health
/parking/sensors/sync_pair
```

Low-latency camera result:

```text
/parking/camera/image_jpeg: roughly 18-36 Hz in live checks
health camera fps: usually 16-36 Hz after startup
```

dToF result:

```text
dToF UDP forwarding errors: 0
dToF topic rate: roughly 15-18 Hz
packet_size=4873
expected_packet_size=4873
width=40
height=30
pixel_number=1200
expected_shape=True
depth_valid_pixels ~= 350-370
depth_unique_count ~= 350+
depth_flat=False
depth_ok=True
```

The previous pure-purple dToF view was caused by the original board-side dToF
dump path changing the VI pipe attributes. The working path uses the keepattr
binary:

```text
/opt/sample/official_dtof/sample_dtof_rtsp_keepattr
```

`tools/wifi_sensor_suite_manager.py` now prefers that binary when it exists.

## rosbag2 Smoke Test

Latest smoke bag:

```text
/home/ebaina/parking_sensor_records/rosbag_smoke/bag_20260531_020306
```

Bag info:

```text
Storage: sqlite3
Duration: 5.699 s
Messages: 1144
/parking/sensors/health: 6
/parking/sensors/sync_pair: 493
/parking/dtof/points: 102
/parking/dtof/depth: 102
/parking/camera/image_jpeg: 441
```

The sensor data topics now use ROS2 `sensor_data` QoS (`BEST_EFFORT`) to avoid
reliable-QoS backpressure during high-rate camera + dToF recording. The
`ROSBAG_RECORD_RC=124` value is expected because the smoke test stops the
recorder with `timeout 8`.

## rosbag2 Replay Test

Replay check script:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --host 192.168.247.129 --timeout 90 run "bash /tmp/vm_rosbag_replay_check.sh"
```

The replay test uses isolated `ROS_DOMAIN_ID=77` so it does not interfere with
the live perception topics. It plays the latest smoke bag and subscribes once to
camera, dToF depth, and health:

```text
BAG_DIR /home/ebaina/parking_sensor_records/rosbag_smoke/bag_20260531_020306
BAG_PLAY_RC 124
REPLAY_CAMERA_RC 0
REPLAY_DEPTH_RC 0
REPLAY_HEALTH_RC 0
REPLAY_CAMERA_BYTES 729
REPLAY_DEPTH_BYTES 720
REPLAY_HEALTH_BYTES 144
```

`BAG_PLAY_RC=124` is expected because the script stops looped playback with
`timeout 8`.

## Visualization Tool Status

Available on the VM:

```text
ros2
ffplay
gst-launch-1.0
rviz2
rosbag2_transport
rqt_image_view package prefix
```

Missing:

```text
foxglove_bridge
rqt_image_view executable
```

Because the current tool policy says not to install new software unless
explicitly requested, Foxglove is adapted with a no-install control wrapper. It
starts the bridge only if the package already exists; otherwise it reports the
missing package and exits without changing the VM package set.

Check Foxglove bridge status:

```powershell
.venv\Scripts\python tools\foxglove_bridge_control.py --vm-host 192.168.247.129 status
```

Current result:

```text
FOXGLOVE_BRIDGE_INSTALLED no
FOXGLOVE_BRIDGE_MISSING
RECOMMENDED_PACKAGE ros-humble-foxglove-bridge
```

No-install Foxglove-compatible live endpoint:

```powershell
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 start
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 status
.venv\Scripts\python tools\foxglove_lite_control.py --vm-host 192.168.247.129 stop
```

Connect Foxglove Studio to:

```text
ws://192.168.247.129:8765
```

The no-install endpoint publishes these Foxglove WebSocket v1 channels from the
current record directory:

```text
/parking/camera/image
/parking/dtof/preview
/parking/preview/composite
/parking/dtof/points_lite
/parking/sensors/health_lite
/parking/dtof/metadata_lite
```

Probe evidence:

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

Current process:

```text
57316 python3 /home/ebaina/parking_foxglove_lite_server.py --host 0.0.0.0 --port 8765 --rate-hz 5.0
```

Browser dashboard file:

```text
D:\parking_board_agent\tools\foxglove_lite_dashboard.html
```

Visual render evidence generated from the same Foxglove-lite WebSocket data:

```text
D:\parking_board_agent\logs\foxglove_lite_render_latest.png
```

Render check evidence:

```text
FOXGLOVE_LITE_RENDER_TOPICS [
  /parking/camera/image,
  /parking/dtof/metadata_lite,
  /parking/dtof/points_lite,
  /parking/dtof/preview,
  /parking/preview/composite,
  /parking/sensors/health_lite
]
FOXGLOVE_LITE_RENDER_MISSING []
```

Once `foxglove_bridge` is installed, start it with:

```powershell
.venv\Scripts\python tools\foxglove_bridge_control.py --vm-host 192.168.247.129 start
```

Then connect from Windows Foxglove Studio or a browser to:

```text
ws://192.168.247.129:8765
```

## Third-Stage Physical Calibration Prerequisites

Do not start this until the sensors are physically mounted. When ready, collect:

- camera position relative to the vehicle reference frame: x, y, z
- dToF position relative to the vehicle reference frame: x, y, z
- camera roll, pitch, yaw
- dToF roll, pitch, yaw
- camera calibration board images for intrinsic calibration
- photos of the fixed sensor mount and cable routing

Until then, keep the software work limited to live perception, recording,
replay, and visualization.
