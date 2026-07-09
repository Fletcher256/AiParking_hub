# Parking Link Check - 2026-06-27

## Check Type

Read-only current-state check of the board-side parking chain.

No YOLO process, camera process, controller, STM32 bridge, serial actuator, CAN,
or motion command was started.

## Topology Observed

```text
Windows host
  192.168.137.1
    |
    | wired Ethernet
    v
Euler Pi / SS928 board
  192.168.137.2 / eth0

Ubuntu VM
  192.168.137.100
  192.168.247.129
```

VM SSH was reachable on both `192.168.137.100` and `192.168.247.129`; both
addresses resolved to the same host:

```text
ebaina-virtual-machine
Linux 6.8.0-124-generic x86_64
```

## Board Runtime State

- Board SSH: OK at `192.168.137.2`.
- Board OS: `Linux (none) 4.19.90 ... aarch64`.
- Board time reported `Fri Jul 17 09:47:04 UTC 2026`, so board clock is skewed
  versus the Windows project date `2026-06-27`.
- Active network traffic is on `eth0`.
- ARP shows Windows host `192.168.137.1`.
- Root filesystem has about `19.5G` free.
- Memory available is about `900MB`.

No active processes were found for:

```text
sample_parking
parking
yolo
stm32
uart
mcu
bridge
sample_dtof
rtsp
python
```

No active sockets were found for the parking ports checked:

```text
24579, 24580, 24581, 2368, 554, 8765, 8090
```

## Safety State

```text
/tmp/parking_armed missing
/tmp/parking_feedback missing
```

This means the current controller arm-file gate is not open.

Boot-time parking link log exists:

```text
/tmp/parking_link_init.log
```

Latest log shows:

```text
status=serial_ready
vid=1a86
pid=7523
tty=/dev/ttyUSB0
driver=generic
driver_mode=generic_fallback
generic_bind_attempted=true
```

Device names observed under `/dev` include:

```text
ttyUSB0
ttyAMA0..ttyAMA5
ttyS000
```

Only device names were listed; no serial device was opened.

## Media / Camera Resource State

`/proc/umap/vb` reports:

```text
max_pool_cnt 0
```

So the MPP VB pool is clean/idle at the time of the check.

Media/NPU modules are loaded, including:

```text
ot_mipi_rx
ot_isp
ot_vi
ot_vpss
ot_venc
ot_npu_tsfw
ot_npu_device
```

## Board Autopark Files

Active autopark directory:

```text
/opt/parking/autopark
```

Important hashes:

```text
20e6ab67ac068a20f37020bddeb2ec17f8817282be508bd75889ea0ef19fe4aa  board_parking_controller.py
fcc484842b1f35fe3c44db20ded128355c9b8be2abf509a9cbc55a0c62ceef81  board_start_yolo_closed_loop_monitor.sh
dfe83438886b29b9e7e56bba2b5f1ae8a8156c39b688758fb04c80d04d4c8d3a  board_yolo_udp_tee.py
129abb10752e606cdff17b8ea670eee04bf00e7bfb6f049de72ba1ee8a78b3b2  parking_action_library.json
dbcbd50f2b6fcaffa046b38467e83ab6ab58e75d59232ffe17a2fd7213b208b2  parking_action_response_model.json
e7a66731766a2bed2fb084bf1bbfb401e20e6533592afc0105441bcf6e6cecc4  chassis_kinematics.json
a74e702f505e98e25fa8346d4e72e468d30371458ed8f2d293af0540fda5bc27  chassis_signs.json
7ddfc88ebd09730487a2a7cc739a1494a45e0c9b529db69d9d79e1b2c88918e9  perception_filter.json
```

Board-side AST/JSON parse checks passed:

```text
AST_OK board_parking_controller.py lines=7602
AST_OK parking_action_scorer.py
AST_OK parking_fusion.py
AST_OK parking_slot_state_analyzer.py
AST_OK parking_response_model_updater.py
AST_OK parking_success_criteria_check.py

JSON_OK parking_action_library.json
JSON_OK parking_action_response_model.json
JSON_OK chassis_kinematics.json
JSON_OK chassis_signs.json
JSON_OK perception_filter.json
JSON_OK parking_success_criteria.json
JSON_OK parking_policy.json
```

Configuration summary:

```text
parking_action_library.json
  actions=10
  version=2026-06-22-transition-reverse-templates

parking_action_response_model.json
  records=18
  legacy_records=1

parking_policy.json
  present
```

## YOLO / Model Files

YOLO app directory:

```text
/opt/sample/parking_yolo_seg_safe
```

Key files are present:

```text
sample_parking_yolo_rtsp_conf06_quiet_displayoff
sample_parking_yolo_rtsp
parking_slot.om
```

Hashes:

```text
1f51690bdece18d28faeabda7bfa1936fa496fba8c8c10d79d4d4e76ba8cba74  sample_parking_yolo_rtsp_conf06_quiet_displayoff
8047faef69abd6f7034f994cc826572ea30f5642f99bd87c579431dbfbbaa7c4  sample_parking_yolo_rtsp
af27758f0383a7c5192558cb899a6500ca4ccfca9377dce356a8030fecab9dc5  parking_slot.om
```

## Boot Scripts

Relevant init scripts:

- `S81wired137`: keeps `eth0` at `192.168.137.2/24`.
- `S90autorun`: loads media stack with `sensor0 os08a20`.
- `S92wifi`: toggles WS73 Wi-Fi via MCU utility and starts STA script.
- `S98stm32uart`: starts the boot-time STM32 USB-UART initializer only.
- `S99parkinglink`: late boot repair for wired IP and USB serial driver status.

No boot script was modified in this check.

## Current Verdict

```text
Static board-side parking chain: READY / IDLE
Dynamic perception chain: NOT RUNNING
Motion/control chain: NOT ARMED, NOT RUNNING
VM receiver side: reachable, idle
```

The chain has the necessary board files, model, configs, Python runtime, media
modules, wired network, and USB serial device name present. It is not actively
producing detections or control decisions because the YOLO monitor/controller
are not running.

## Notable Issue

`/opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh` is currently
`-rw-r--r--` on the board, not executable. It can still be invoked as:

```sh
sh /opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh
```

but direct execution as:

```sh
/opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh
```

would fail unless its execute bit is restored. Changing permissions requires
the approval protocol because `chmod` is gated by `AGENTS.md`.

## Next Dynamic Check Requires Approval

A true end-to-end check would need to start at least the camera/YOLO monitor and
UDP tee, and optionally a no-motion controller. That is not read-only because
it starts processes, writes PID/log files, may clean MPP VB state, and the start
script contains stop/cleanup logic for previous YOLO processes.

