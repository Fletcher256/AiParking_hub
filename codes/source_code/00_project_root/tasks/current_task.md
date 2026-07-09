# Current Task: OS08A20 Camera + dToF Bring-Up

## Objective

Bring up the Euler Pi / SS928 board with:

- OS08A20 camera on sensor0, 4lane.
- Official ebaina dToF module on dtof0, sensor2/J3/I2C4.
- Ubuntu VM receiving dToF packets first, then camera data after the official
  combined mode is stable.

## Strict Route

1. Use `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof` as the
   board-side source of truth.
2. Do not use `/opt_sample` binaries or configs as the baseline.
3. Deploy fresh artifacts to `/opt/sample/official_dtof`.
4. Build with:
   - `SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT`
   - `SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT`
5. Validate official `sample_dtof` cases in order:
   - `case 0`: sensor0 only.
   - `case 1`: dtof0 only.
   - `case 3`: sensor0 + dtof0.
6. Validate dToF UDP on VM before ROS:
   - destination port: `2368`
   - packet size: `4873` bytes
   - expected image: `40 x 30`, `1200` pixels
7. Add camera network output only after `case 3` is stable.

## Current Board Baseline

- `/etc/init.d/S90autorun` has been restored to the basic media-loader script.
- Previous experimental dToF/camera files were moved out of `/opt/sample` and
  are archived under `/opt_sample`.
- Do not restore from `/opt_sample` unless explicitly requested.
- `/opt/sample/official_dtof` now contains the clean official runtime files
  deployed from the VM build below.

## Current Build Evidence

- Clean VM build directory:
  `/home/ebaina/official_dtof_build_20260530_0010`
- Build command used official zip:
  `/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip`
- Build macros included:
  - `SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT`
  - `SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT`
- Deployed board directory:
  `/opt/sample/official_dtof`
- Verified deployed SHA256:
  - `sample_dtof`: `4aaa07c81b48ec379ac475861c1b5cf94a1aad1600d91c7627f63600d73e9f35`
  - `dtof.ini`: `7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6`
  - `gs1860_register.ini`: `3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb`
  - `dtof_init.sh`: `eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0`
  - `ko/ot_isp.ko`: `628294f55dc71238f725f7ef4d7e072f26012c2a40d889889d3284b8685d7ee7`
  - `ko/ot_mipi_rx.ko`: `75b5f78073a9c332c4b32207a706621cac64640269337e17cc27e16fcd125f41`
  - `ko/ot_vi.ko`: `b69099f799196dc1121ddf24025ebc133370665958626a5986c6b4c78d2d46c4`

## Prepared Validation Notes

- Case 0 result: passed on 2026-05-30.
  - Board command reloaded media stack with OS08A20 sensor parameters.
  - `sample_dtof 0 192.168.137.100` reported:
    `os08a20 24Mclk 8M30fps(MIPI) 12bit linear init success`
  - It also reported `program exit normally` and `CASE0_RC=0`.
  - A wrapper timeout happened only because the old wrapper used `exit $rc`
    before `board_serial.py` could receive its sentinel; the wrapper has been
    fixed.
- Case 1 result: passed on 2026-05-30.
  - Board command reloaded media stack and ran
    `sample_dtof 1 192.168.137.100`.
  - Board output reported `DTOF version: F01V01T01`,
    `DtofInit success!!!`, `DtofDestory success!!!`,
    `program exit normally`, and `CASE1_RC=0`.
  - VM received 20 UDP packets on port `2368` from `192.168.137.2`.
  - All 20 packets had payload size `4873`.
  - First packet header evidence:
    `FIRST_32_HEX=0000000000000000b004000000000000000028001e001e0000da5b174227e010`
    where payload offsets 18/20 contain `28 00` and `1e 00`
    (`40 x 30`).
  - The first run of `tools/vm_dtof_udp_check.py` incorrectly checked
    width/height at offsets 26/28 and reported `DTOF_UDP_CHECK=FAIL`.
    The script has been corrected to offsets 18/20 after inspecting the
    packet and official format.
  - Post-run checks found no residual `sample_dtof` process.
- Case 3 result: passed on 2026-05-30.
  - Board command reloaded media stack and ran
    `sample_dtof 3 192.168.137.100`.
  - OS08A20 output reported:
    `os08a20 24Mclk 8M30fps(MIPI) 12bit linear init success`
    and `ISP Dev 0 running !`.
  - dToF output reported `DTOF version: F01V01T01`,
    `DtofInit success!!!`, `DtofDestory success!!!`,
    `program exit normally`, and `CASE3_RC=0`.
  - VM received 30 UDP packets on port `2368` from `192.168.137.2`.
  - All 30 packets had payload size `4873` and header `40 x 30`.
  - VM check reported `DTOF_UDP_CHECK=PASS`.
  - Post-run checks found no residual `sample_dtof` process.
- Camera network output result: passed on 2026-05-30.
  - Local source updated from the official dToF sample only:
    `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/sample_dtof.c`.
  - Added case `7`: `sensor0 + dtof0 + rtsp`, using the existing SDK
    VENC/RTSP path and leaving case `3` unchanged.
  - Clean VM RTSP build directory:
    `/home/ebaina/official_dtof_rtsp_build_20260530_0100`
  - RTSP-enabled binary SHA256:
    `fc60d2c9415af1cccc98a920d0151ae5aaa58502d38cc2446c91c9e0a5d86857`
  - Deployed board file:
    `/opt/sample/official_dtof/sample_dtof_rtsp`
  - Case 7 board output reported:
    `camera rtsp ready: rtsp://192.168.137.2:554/live0`,
    `RTSP client connected 192.168.137.100`, `DtofInit success!!!`,
    `DtofDestory success!!!`, `program exit normally`, and `CASE7_RC=0`.
  - VM dToF UDP check reported:
    `PACKETS=30`, `GOOD_SIZE_4873=30`, `GOOD_HEADER_40x30=30`,
    and `DTOF_UDP_CHECK=PASS`.
  - VM RTSP check reported:
    `RTSP_URL=rtsp://192.168.137.2:554/live0`,
    `RTSP_LAST_RC=124`, `RTSP_LAST_ELAPSED=8.01`, and `RTSP_CHECK=PASS`.
  - Combined wrapper reported `CASE7_COMBINED_CHECK=PASS`.
  - Post-run check found no residual `sample_dtof` process or RTSP `:554`
    listener.
- Local dry-run wrapper prepared:
  `tools/board_case0_check.py`
  - Without `--execute-approved`, it only prints the exact board-side command.
  - With `--execute-approved`, it calls `tools/board_serial.py --allow-risk`
    to run the approved case 0 command.
- Case 0 must reload the media stack with OS08A20 sensor parameters before
  running:
  `/opt/ko/load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20`
- Existing old helper scripts such as `tools/listen_dtof.py` and
  `tools/concurrent_udp_test.py` reference old paths or direct board SSH
  operations. Do not use them as the clean-route baseline.
- Clean VM-only UDP validation helper prepared:
  `tools/vm_dtof_udp_check.py`
  - Connects only to the Ubuntu VM.
  - Listens on UDP port `2368`.
  - Validates payload size `4873` and header width/height `40 x 30`.
  - Does not control the board or reference `/opt_sample`.
- Case 1 dry-run wrapper prepared:
  `tools/board_case1_dtof_udp_check.py`
  - Without `--execute-approved`, it only prints the VM listener and board
    case 1 commands.
  - With `--execute-approved`, it starts `tools/vm_dtof_udp_check.py`, then
    runs the approved board-side `sample_dtof 1 192.168.137.100` command.
- Case 3 dry-run wrapper prepared:
  `tools/board_case3_rgb_dtof_udp_check.py`
  - Without `--execute-approved`, it only prints the VM listener and board
    case 3 combined-mode commands.
  - With `--execute-approved`, it starts `tools/vm_dtof_udp_check.py`, then
    runs the approved board-side `sample_dtof 3 192.168.137.100` command.
  - Use only after case 0 and case 1 have passed.
- Case 7 dry-run wrapper prepared:
  `tools/board_case7_rgb_dtof_rtsp_check.py`
  - Without `--execute-approved`, it only prints the VM UDP listener, VM RTSP
    checker, and board case 7 commands.
  - With `--execute-approved`, it starts `tools/vm_dtof_udp_check.py`, starts
    `tools/vm_rtsp_check.py`, then runs approved board-side
    `sample_dtof_rtsp 7 192.168.137.100`.
  - Acceptance requires `CASE7_RC=0`, `DTOF_UDP_CHECK=PASS`,
    `RTSP_CHECK=PASS`, and `CASE7_COMBINED_CHECK=PASS`.
- Case 1 dToF UDP acceptance criteria from official docs:
  - UDP destination port: `2368` (`0x0940`)
  - UDP payload/data size: `4873` bytes
  - Packet header width/height: `40 x 30`
  - Pixel count: `1200`

## Checklist

- [x] Rebuild clean official `sample_dtof` on the Ubuntu VM.
- [x] Stage clean runtime files in `/opt/sample/official_dtof` on the board.
- [x] Validate `case 0` OS08A20-only capture.
- [x] Validate `case 1` dToF-only UDP output to the VM.
- [x] Validate `case 3` OS08A20 + dToF combined mode.
- [x] Add and validate camera network output after combined mode is stable.
- [x] Build and validate VM ROS2 sensor-suite receiver/recorder for RTSP camera
  and dToF UDP.

## VM ROS2 Sensor Suite

- ROS2 workspace:
  `/home/ebaina/parking_ws`
- Package:
  `/home/ebaina/parking_ws/src/parking_bridge`
- Local source:
  `D:/parking_board_agent/ros/parking_bridge`
- Official reference used:
  `vendor/dtof_sensor_driver-master/sample/ubuntu_pc/dtof_ros_demo_udp`
  - Its C++ sample defines the dToF UDP packet layout:
    `4873` bytes, header width/height `40 x 30`, `1200` pixels, and
    per-pixel depth/confidence/flag.
  - Its README uses ROS2/colcon and `dtof_client_node` launch patterns.
- Package build:
  `colcon build --packages-select parking_bridge` passed on the VM.
- VM dependency added:
  `python3-colcon-common-extensions` was installed because colcon was missing
  and the official dToF ROS demo requires colcon.
- Main node:
  `parking_bridge/sensor_suite_node.py`
  - Receives camera RTSP:
    `rtsp://192.168.137.2:554/live0`
  - Receives dToF UDP:
    port `2368`, packet size `4873`, image `40 x 30`
  - Publishes ROS2 topics:
    `/parking/camera/image_raw`, `/parking/camera/image_jpeg`,
    `/parking/dtof/raw_packet`, `/parking/dtof/depth`,
    `/parking/dtof/confidence`, `/parking/dtof/camera_info`,
    `/parking/dtof/points`, `/parking/sensors/health`,
    `/parking/sensors/sync_pair`
  - Records raw/derived data:
    `dtof_packets.bin`, `dtof_packets.jsonl`, `dtof_metadata.jsonl`,
    `dtof_depth_npy/*.npy`, `camera_frames/*.jpg`,
    `camera_frames.jsonl`, `health.jsonl`, `sync_pairs.jsonl`,
    and preview images.
- Launch file:
  `/home/ebaina/parking_ws/src/parking_bridge/launch/parking.launch.py`
- README:
  `/home/ebaina/parking_ws/src/parking_bridge/README.md`

### ROS2 Validation Evidence

- Synthetic dToF parser smoke test passed on VM:
  - synthetic packet size: `4873`
  - parsed shape: `40 x 30`
  - parsed pixel count: `1200`
- Synthetic ROS2 node smoke test passed on VM:
  - 6 synthetic dToF packets were received.
  - `dtof_packets.bin` size was `29238` bytes (`6 * 4873`).
  - `dtof_metadata.jsonl` contained 6 parsed metadata rows.
- Real case7 ROS2 sensor-suite verification passed on 2026-05-30:
  - Wrapper:
    `tools/board_case7_ros_sensor_suite_check.py`
  - Board output:
    `camera rtsp ready: rtsp://192.168.137.2:554/live0`,
    `DtofInit success!!!`, `DtofDestory success!!!`,
    `program exit normally`, and `CASE7_RC=0`.
  - VM ROS2 log showed both live health states during capture:
    `camera=True` and `dtof=True`.
  - Record directory:
    `/home/ebaina/parking_sensor_records/case7_ros_check_sync/session_20260530_100158`
  - Recorded camera frames:
    `CAMERA_FRAMES=60`
  - Recorded dToF raw data:
    `DTOF_BIN_BYTES=2689896`, which is `552 * 4873`.
  - Parsed dToF metadata:
    `DTOF_METADATA_LINES=552`
  - dToF index rows:
    `DTOF_INDEX_LINES=552`
  - Parsed dToF depth arrays:
    `DTOF_DEPTH_NPY=552`
  - Health monitor rows:
    `HEALTH_LINES=54`
  - Sync pairs:
    `SYNC_LINES=90`
  - Preview images:
    `PREVIEW_FILES=36`
  - Verification result:
    `ROS_SENSOR_RECORD_CHECK PASS` and `ROS_SENSOR_SUITE_CHECK=PASS`.
- Post-run checks:
  - No residual board `sample_dtof` process or RTSP `:554` listener was found.
  - No residual VM `sensor_suite_node` or `ros2 launch parking_bridge` process
    was found.

## Safety

All board/VM write operations, process control, module loading, startup script
changes, file moves/removals, package installs, reboots, and network changes
must follow the approval protocol in `AGENTS.md`.
