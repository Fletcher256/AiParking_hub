# Kinematic Lattice Replanner Migration - 2026-06-30

## Outcome

Added a conservative, measured-kinematics parking replanner and downgraded the immature paths that caused the latest reverse-chain risk.

New mature path:

```text
current reliable YOLO slot pose
  -> measured chassis primitive model from configs/chassis_kinematics.json
  -> kinematic lattice lookahead
  -> choose one bounded ARC primitive
  -> controller executes only the first short action
  -> STOP / observe / replan
```

## New files

- `tools/parking_kinematic_lattice.py`
  - Pure-Python board/offline module.
  - Uses `steer_curvature[].deg_per_cm`, `servo_center_trim_ste`, deadband and coast from `configs/chassis_kinematics.json`.
  - Provides offline replay CLI and board-side planner functions.

## Controller integration

- `tools/board_parking_controller.py`
  - New strategy: `--strategy kinematic_lattice_replanner`.
  - Reuses `--replanner-dry-run` as no-motion mode for this strategy.
  - Logs `kinematic_lattice` inside candidate events and emits `kinematic_lattice_step` events.
  - Vision loss for this strategy is fail-closed: wait briefly for reacquisition, then STOP. No belief blind driving and no final-blind token consumption.

## Downgraded immature paths

Defaults changed to fail closed:

- `--replanner-belief-enable`: default `False`.
- `--replanner-belief-use-on-partial-visible`: default `False`.
- `--replanner-belief-blind-enable`: default `False`.
- `--terminal-unreliable-vision-ignore-slot-x-px`: default `False`.
- `--terminal-unreliable-vision-relax-predicted-heading`: default `False`.
- `--final-blind-precomputed-token-enable`: default `False`.
- `--final-blind-precomputed-allow-heading-arc`: default `False`.

Existing line accumulator remains hard-disabled by policy in the controller and should not be deployed to the board for the new chain.

## Local validation

Commands run locally:

```powershell
.\.venv\Scripts\python.exe -m py_compile tools\parking_kinematic_lattice.py tools\board_parking_controller.py

.\.venv\Scripts\python.exe tools\parking_kinematic_lattice.py `
  --replay artifacts\board_sync_20260630_043426\rootfs\tmp\terminal_heading_retry_20260630_040829.jsonl `
           artifacts\board_sync_20260630_043426\rootfs\tmp\partial_planning_reverse_retry_20260630_034127.jsonl `
  --kinematics configs\chassis_kinematics.json `
  --criteria configs\parking_success_criteria.json `
  --out artifacts\kinematic_lattice_replay_20260630.json

.\.venv\Scripts\python.exe tools\board_parking_controller.py `
  --dry-run --strategy kinematic_lattice_replanner --replanner-dry-run `
  --duration-sec 0.2 --target-wait-sec 0.05 --settle-sec 0.05 `
  --listen-host 127.0.0.1 --listen-port 24681 `
  --chassis-signs-json configs\chassis_signs.json `
  --chassis-kinematics-json configs\chassis_kinematics.json `
  --success-criteria-json configs\parking_success_criteria.json `
  --perception-filter-json configs\perception_filter.json `
  --log-jsonl artifacts\kinematic_lattice_controller_smoke_20260630.jsonl
```

Replay result for the two latest bad real runs:

```text
row_count=79
chosen_counts: WAIT=79
status_counts: wait_unreliable_visual=79
```

This is the expected fail-closed behavior: the latest real runs were driven by suspect/partial geometry, so the mature replanner refuses to move instead of continuing from accumulated lines or belief.

## Board deployment note

Board-side deployment/removal is non-read-only and must follow the workspace approval protocol before execution. Recommended deployment should copy only:

- `board_parking_controller.py`
- `parking_kinematic_lattice.py`
- required configs (`chassis_kinematics.json`, `chassis_signs.json`, `parking_success_criteria.json`, `perception_filter.json`)

Recommended board cleanup: remove `/opt/parking/autopark/parking_line_accumulator.py` and its `__pycache__` after backup, because it is no longer part of the runtime chain.

## Board deployment completed

Approved by user and executed from local PC.

Board backup directories observed:

```text
/opt/parking/autopark_backup_
/opt/parking/autopark_backup_20260720_012020
```

The first directory was created by a PowerShell quoting mistake during the first backup attempt; the second one is the intended timestamped board backup. Both are harmless backup directories.

Board deployed files:

```text
/opt/parking/autopark/board_parking_controller.py
sha256=1a7608a7f49ffcd924e73ab738b34106ec82b9b65b23d1a89113e32c17cc1961

/opt/parking/autopark/parking_kinematic_lattice.py
sha256=3e6903f3c403d445dc3e02718906ac03f16abd937fc1780df01911724636fddb
```

Board removal verified:

```text
/opt/parking/autopark/parking_line_accumulator.py -> removed
```

Board smoke check:

```text
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py \
  --dry-run --strategy kinematic_lattice_replanner --replanner-dry-run \
  --duration-sec 0.2 ...
```

Result: controller started in no-motion mode, loaded chassis signs/kinematics, reported `slot_line_accumulator=DISABLED_BY_POLICY`, and exited by duration with no target. No STM32 motion was commanded.

## Live YOLO no-motion check after deployment

Executed after user confirmation:

```text
ACTION=start VM_HOST=192.168.137.100 sh /opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --dry-run --strategy kinematic_lattice_replanner --replanner-dry-run --duration-sec 30 ...
```

Result:

```text
YOLO pid=2898
UDP tee pid=2894
controller log=/tmp/parking_kinematic_lattice_dryrun_20260630.jsonl
steps=0
total_cm=0.0
STOP=DURATION elapsed
```

Controller saw no target:

```text
vision_lost events only
no candidate / no kinematic_lattice_step events
```

YOLO and UDP tee were alive, but YOLO reported zero detections:

```text
parking_yolo_live_infer idx=90 ret=0x0 count=0
...
parking_yolo_live_infer idx=1170 ret=0x0 count=0
BOARD_YOLO_UDP_TEE packets forwarded, dropped=0
```

Interpretation: the software/runtime path is alive and no-motion safety held, but the current camera scene produced no Parking detections, so the new lattice planner did not yet receive a reliable live slot pose to rank actions.
