# Camera-only OS08A20 bring-up, 2026-06-03

Scope:
- Board: Euler Pi / SS928 at `192.168.137.2`.
- VM: Ubuntu at `192.168.137.100`.
- Active sensor path: OS08A20 camera only.
- Disabled paths: dToF, STM32, MCU bridge, CAN, serial actuator, motor, steering, brake, throttle.

## Code changes

- Added board-side `sample_dtof` case 8:
  - `sample_camera_rtsp 8 <dst_ip>`
  - Starts sensor0, VPSS, VENC, and RTSP `live0`.
  - Does not call `gs1860_read_ini_file`, `dtof_init`, or `vi_bayerdump`.
- Added ROS `enable_dtof` parameter to `sensor_suite_node`.
  - `enable_dtof:=false` skips the UDP dToF listener thread.
  - Health JSON reports `dtof.enabled=false` and does not mark missing dToF as a fault.
- Changed `parking.launch.py` defaults for camera-only bring-up:
  - `enable_dtof=false`
  - `enable_vision_preprocess=true`
  - `enable_yolo_person=false`
- Extended `vision_preprocess_node.py`:
  - Publishes schema version 2.
  - Keeps line candidates.
  - Adds pixel-space `slots`, `slot_count`, and conservative `possibly_empty` / `possibly_occupied` / `unknown` status.
  - Still publishes no control commands and has `motion_enabled=false`.

## Build and deploy

VM build inputs:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --allow-risk put-text tools\vm_camera_only_rtsp_build.sh /tmp/vm_camera_only_rtsp_build.sh
.venv\Scripts\python tools\vm_ssh_run.py --allow-risk put-text vendor\SS928V100_SDK_V2.0.2.2_MPP_Sample-master\src\dtof\sample_dtof.c /tmp/sample_camera_rtsp.c
.venv\Scripts\python tools\vm_ssh_run.py --timeout 600 --allow-risk run "BUILD=/home/ebaina/official_camera_rtsp_20260603_codex bash /tmp/vm_camera_only_rtsp_build.sh prepare && BUILD=/home/ebaina/official_camera_rtsp_20260603_codex bash /tmp/vm_camera_only_rtsp_build.sh build"
```

Build result:

```text
/home/ebaina/official_camera_rtsp_20260603_codex/src/dtof/sample_camera_rtsp
sha256: 7edc0d3d039a94f503099298bdc82c218ba7be7cb627af77ca84baa7cc5fa5a2
size: 4538344
```

Board deploy:

```powershell
.venv\Scripts\python tools\board_run.py --allow-risk "mkdir -p /opt/sample/camera_only && ls -ld /opt/sample/camera_only"
.venv\Scripts\python tools\vm_ssh_run.py --timeout 180 --allow-risk run "sshpass -p ebaina scp -p -o StrictHostKeyChecking=no /home/ebaina/official_camera_rtsp_20260603_codex/src/dtof/sample_camera_rtsp root@192.168.137.2:/opt/sample/camera_only/sample_camera_rtsp"
.venv\Scripts\python tools\board_run.py "cd /opt/sample/camera_only && ls -l sample_camera_rtsp && sha256sum sample_camera_rtsp && strings sample_camera_rtsp | grep -F 'sensor0 + rtsp' || true"
```

Board verification:

```text
/opt/sample/camera_only/sample_camera_rtsp
sha256: 7edc0d3d039a94f503099298bdc82c218ba7be7cb627af77ca84baa7cc5fa5a2
usage string: (8) sensor0 + rtsp 4lane sensor0 + rtsp live0, no dtof init.
```

ROS deploy:

```powershell
.venv\Scripts\python tools\deploy_ros_package.py --host 192.168.137.100 --user ebaina --password ebaina --allow-risk
```

Result:

```text
colcon build --packages-select parking_bridge: success
```

## Runtime commands

Board camera-only RTSP start:

```powershell
.venv\Scripts\python tools\board_run.py --allow-risk 'sh -lc "set -e; fifo=/tmp/camera_only_rtsp.stdin; log=/tmp/camera_only_rtsp.log; pidfile=/tmp/camera_only_rtsp.pid; if [ -s \"$pidfile\" ]; then old=$(cat \"$pidfile\" 2>/dev/null || true); if [ -n \"$old\" ] && [ -d \"/proc/$old\" ]; then echo CAMERA_ONLY_ALREADY_RUNNING $old; echo CAMERA_ONLY_LOG $log; exit 0; fi; fi; rm -f \"$fifo\"; mkfifo \"$fifo\"; ( cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20; cd /opt/sample/camera_only; echo BOARD_CAMERA_BINARY ./sample_camera_rtsp; cat \"$fifo\" | ./sample_camera_rtsp 8 192.168.137.100; echo CAMERA_ONLY_EXIT_CODE=$? ) > \"$log\" 2>&1 & pid=$!; echo $pid > \"$pidfile\"; echo CAMERA_ONLY_PID $pid; echo CAMERA_ONLY_LOG $log"'
```

VM ROS camera-only start:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 120 --allow-risk run 'nohup setsid bash -lc "source /opt/ros/humble/setup.bash && source ~/parking_ws/install/setup.bash && exec ros2 launch parking_bridge parking.launch.py rtsp_url:=rtsp://192.168.137.2:554/live0 enable_dtof:=false enable_vision_preprocess:=true enable_yolo_person:=false publish_camera_raw:=false camera_record_stride:=10 enable_stm32:=false" > /tmp/parking_camera_only_ros.log 2>&1 & echo $! > /tmp/parking_camera_only_ros.pid'
```

## Validation

Board process check:

```text
./sample_camera_rtsp 8 192.168.137.100
No sample_dtof process.
No MCU/CAN/actuator process observed.
```

RTSP audit:

```powershell
.venv\Scripts\python tools\rtsp_quality_latency_audit.py --rtsp-url rtsp://192.168.137.2:554/live0 --vm-host 192.168.137.100 --seconds 8
```

Result:

```text
STREAM_CODEC h264
STREAM_SIZE 3840x2160
STREAM_R_FPS 30.0
ffmpeg_tcp_default: BAD_DECODE=0 FLAT=0 GRAYISH=0 FPS=26.500
ffmpeg_tcp_lowdelay: BAD_DECODE=0 FLAT=0 GRAYISH=0 FPS=27.125
SELECTED_MODE ffmpeg_tcp_lowdelay
RTSP_QUALITY_LATENCY_AUDIT PASS
Host report: artifacts/rtsp_quality_latency_audit/rtsp_quality_latency_20260603_204811.json
```

ROS topic checks:

```text
/parking/camera/image_jpeg: about 11 FPS through ffmpeg_mjpeg
/parking/vision/line_debug: about 3.7 FPS with process_stride=3
/parking/parking_slot_candidates: schema_version=2
/parking/sensors/health: camera.ok=true, dtof.enabled=false, dtof.ok=true
```

Example candidate payload:

```json
{
  "schema_version": 2,
  "status": "line_candidates",
  "original_image_size": [3840, 2160],
  "processed_image_size": [960, 540],
  "line_count": 3,
  "slot_count": 0,
  "motion_enabled": false,
  "calibrated": false
}
```

Interpretation:
- The camera path is restored and stable.
- The current view contains parking-line candidates but not enough paired geometry for a full parking-slot polygon.
- Pointing the camera at clear paired stall lines should produce `slot_count > 0`.

## Logs

- VM build: `D:\parking_board_agent\logs\vm_ssh_20260603_204336_4eca99eb.log`
- Board deploy check: `D:\parking_board_agent\logs\vm_ssh_20260603_204508_6123ca6b.log`
- RTSP host report: `D:\parking_board_agent\artifacts\rtsp_quality_latency_audit\rtsp_quality_latency_20260603_204811.json`
- Board runtime log: `/tmp/camera_only_rtsp.log`
- VM ROS runtime log: `/tmp/parking_camera_only_ros.log`
- VM ROS record session: `/home/ebaina/parking_sensor_records/session_20260603_204846`
