# Board Sync Status - 2026-06-27

## Scope

Read-only scan of the Euler Pi / SS928 board over wired Ethernet, followed by
local Windows workspace synchronization from the board-side autopark runtime.

No board runtime files were overwritten during this sync.

## Connectivity

- COM11 serial: unavailable on Windows during this scan.
  - Error: `FileNotFoundError(2, '系统找不到指定的文件。')`
- Wired board SSH: reachable.
  - Board IP: `192.168.137.2`
  - User: `root`
  - Kernel: `Linux (none) 4.19.90 #1 SMP Fri Jan 30 11:45:17 CST 2026 aarch64`
- Ubuntu VM SSH:
  - `192.168.137.100`: timeout
  - `192.168.247.129`: timeout

## Board State Snapshot

- Host Windows wired IP: `192.168.137.1/24`
- Board active interface from `/proc/net/dev`: `eth0`
- Board route table shows default route via `192.168.1.1` encoded as
  gateway `0101A8C0`, and connected routes for `192.168.1.0/24` and
  `192.168.137.0/24`.
- Root filesystem:
  - `/dev/root`
  - `28.2G` total, `7.5G` used, `19.5G` available.
- No selected `sample_dtof`, RTSP, parking, ROS, or Python process was found
  in the read-only process scan.
- Follow-up safety grep found no parking / STM32 / MCU / bridge / YOLO process.
- `/tmp/parking_armed` was missing, so real motion is not armed by that gate.
- A temporary scan artifact exists on the board:
  `/tmp/codex_found_files.txt`. It only contains a short list of discovered
  file paths from this scan. Delete it only through the normal approval flow
  because `rm` is a gated command in `AGENTS.md`.
- Board clock reported `Fri Jul 17 09:35:32 UTC 2026`, which is inconsistent
  with the Windows/project date `2026-06-27`. Treat board file mtimes as
  clock-skewed; prefer hashes and filenames for ordering.

## dToF / Camera Baseline

Official dToF directory still exists:

```text
/opt/sample/official_dtof
```

Key hashes matched the earlier documented official baseline:

```text
sample_dtof        4aaa07c81b48ec379ac475861c1b5cf94a1aad1600d91c7627f63600d73e9f35
sample_dtof_rtsp   fc60d2c9415af1cccc98a920d0151ae5aaa58502d38cc2446c91c9e0a5d86857
dtof.ini           7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6
gs1860_register.ini 3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb
dtof_init.sh       eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0
```

`sample_dtof_rtsp_keepattr` is present with hash:

```text
b11ec2dc96fdcd92ea108077fc96c25c7844de5f78e2cd4b76271c3d9bb5aafb
```

## Board Autopark Runtime

Current active board path:

```text
/opt/parking/autopark
```

Important current files:

```text
/opt/parking/autopark/board_parking_controller.py
/opt/parking/autopark/board_start_yolo_closed_loop_monitor.sh
/opt/parking/autopark/board_yolo_udp_tee.py
/opt/parking/autopark/parking_action_library.json
/opt/parking/autopark/parking_action_response_model.json
/opt/parking/autopark/chassis_kinematics.json
/opt/parking/autopark/chassis_signs.json
/opt/parking/autopark/perception_filter.json
```

The board controller is newer than the local copy that existed before this
sync:

```text
local old tools/board_parking_controller.py  08442da71da529741c8a60737ab6cb1fd4c48638cc4fc4058924071dd0f7bd22
board live board_parking_controller.py      20e6ab67ac068a20f37020bddeb2ec17f8817282be508bd75889ea0ef19fe4aa
```

Key board-side controller changes relative to the previous local file include:

- controller line count grew from about `4987` to `7602`;
- `SERVO_CENTER` is now `100.0`;
- slot geometry uses polygon/quadrilateral `quad_*` fields instead of the old
  oriented-bbox baseline;
- added final/blind/degraded visibility review helpers;
- added stronger motion guard helpers and lateral divergence review;
- expanded action-replanner state and response-model support.

## Local Workspace Sync Performed

Board text snapshot:

```text
D:\parking_board_agent\artifacts\board_autopark_text_snapshot_20260627_132945
```

Local pre-sync backup:

```text
D:\parking_board_agent\artifacts\local_backup_before_board_sync_20260627_133044
```

Synced from board to local:

```text
tools\board_parking_controller.py
tools\board_start_yolo_closed_loop_monitor.sh
tools\parking_action_scorer.py
configs\chassis_kinematics.json
configs\chassis_signs.json
configs\parking_action_library.json
configs\parking_action_response_model.json
configs\parking_policy.json
configs\perception_filter.json
tools\yolo_probe_quiet_wrapper.sh
tools\yolo_probe_skipmask_wrapper.sh
tools\yolo_probe_wrapper.sh
tools\board_S90autorun_live_20260627
tools\board_S81wired137_live_20260627
tools\board_S92wifi_live_20260627
tools\board_S98stm32uart_live_20260627
tools\board_S99parkinglink_live_20260627
```

Already matched before sync:

```text
tools\board_yolo_udp_tee.py
tools\_run_path_template_planner_dryrun.sh
tools\_run_path_template_planner_once.sh
tools\parking_fusion.py
tools\parking_response_analyzer.py
tools\parking_response_model_updater.py
tools\parking_slot_state_analyzer.py
tools\parking_success_criteria_check.py
configs\autopark_multistage_plan.json
configs\parking_success_criteria.json
```

Local verification after sync:

```text
VERIFY PASS
py_compile PASS
perception_filter_tests=PASS
parking_action_scorer --help PASS
```

Note: `tools/test_perception_filter.py` was locally patched after sync to add
the current `quad_*` test fields while preserving old `bbox_*` aliases. This
fixes the local regression test against the current board controller.

## Next Safe Steps

1. If VM is needed, start or reconnect the VM and re-check SSH at
   `192.168.137.100` / `192.168.247.129`.
2. If validating perception only, start with read-only/receive-only health
   checks and avoid STM32/motion paths.
3. Before any board deployment, process restart, module reload, vehicle motion,
   or cleanup command, follow the approval protocol in `AGENTS.md`.
