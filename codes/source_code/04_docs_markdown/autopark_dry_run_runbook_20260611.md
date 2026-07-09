# Board-Only Dry-Run Runbook - 2026-06-11

Purpose: run the autonomous parking software path without moving the vehicle.

## Safety Boundary

This runbook must not send `MOVE` or `ARC`.

Allowed:

- start/restart board YOLO perception
- listen to board YOLO UDP on `127.0.0.1:24580`
- run `board_parking_controller.py --dry-run`
- run STM32 `PING/VER/STAT/STOP`
- collect logs and RTSP frames

Not allowed:

- MCU bridge
- CAN actuator
- serial actuator daemon
- motor, steering, brake, throttle commands
- `board_parking_controller.py --arm` real motion mode

## Expected Runtime Path

```text
OS08A20 camera
  -> /opt/sample/parking_yolo_seg_safe/sample_parking_yolo_rtsp
  -> UDP 127.0.0.1:24580
  -> /tmp/board_parking_controller.py --dry-run
  -> JSONL candidate diagnostics only
```

## Start YOLO Local Output

Use the existing local restart script or equivalent board command that sets:

```text
PARKING_YOLO_RTSP=1
PARKING_YOLO_UDP_HOST=127.0.0.1
PARKING_YOLO_UDP_PORT=24580
PARKING_YOLO_RUN_FOREVER=1
PARKING_YOLO_CONFIDENCE_THRESHOLD=0.25
```

This is perception-only.

## Deploy Controller To Board

```powershell
.venv\Scripts\python tools\board_auto_ssh.py put-text --host 192.168.137.2 --user root --password ebaina --allow-risk tools\board_parking_controller.py /tmp/board_parking_controller.py
```

## Run Bounded Dry-Run

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 70 --allow-risk "/usr/local/bin/python3 /tmp/board_parking_controller.py --dry-run --duration-sec 60 --target-wait-sec 2 --settle-sec 0.2 --log-jsonl /tmp/parking_dry_run.jsonl --strategy template"
```

Expected safety fields in JSONL:

```json
{"send_to_stm32":false,"motion_enabled":false,"actuator_control_allowed":false}
```

## Analyze Log

Fetch the board log into `artifacts/autopark_baseline/`, then run:

```powershell
.venv\Scripts\python tools\parking_dry_run_analyze.py artifacts\autopark_baseline\parking_dry_run.jsonl --summary-json artifacts\autopark_baseline\parking_dry_run_summary.json --curve-csv artifacts\autopark_baseline\parking_dry_run_curve.csv
```

Useful pass criteria before motion:

- stable candidate events exist
- command family does not flip rapidly
- lateral sign does not jump
- confidence is stable enough for the current scene
- `send_to_stm32_events=0`
- `motion_events=0`
- `actuator_allowed_events=0`

