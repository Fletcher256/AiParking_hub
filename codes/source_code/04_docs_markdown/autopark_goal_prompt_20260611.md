# Autonomous Parking Goal Prompt - 2026-06-11

Use this as the project goal prompt for future agent runs.

```text
Goal: Complete the non-motion prerequisites for board-only autonomous parking on the Euler Pi / SS928 vehicle.

Scope:
- Audit current YOLO, STM32, ROS, controller, board scripts, VM scripts, and documentation.
- Verify board and VM health using safe checks.
- Verify camera/YOLO perception without starting any actuator path.
- Verify STM32 safety commands only: PING, VER, STAT, STOP.
- Run board-only dry-run parking closure: camera -> board YOLO -> UDP 127.0.0.1:24580 -> board_parking_controller.py --dry-run -> candidate MOVE/ARC diagnostics only.
- Improve the non-motion controller path: multi-frame target filtering, entrance/axis stability checks, rear-axle target pose, state-machine/action-template decisions, divergence detection, vision-loss WAIT/STOP behavior, structured dry-run logs, and configurable thresholds.
- Add offline replay and model-regression tooling for future YOLO updates.
- Implement and test safety gates: no --arm means no motion; no /tmp/parking_armed means no motion; dry-run never opens motion output; unstable vision blocks motion; STM32 abnormal state blocks motion; target loss yields WAIT/STOP; invalid MOVE/ARC parameters are rejected.
- Produce current status report, dry-run runbook, real-car single-step checklist, safety checklist, YOLO model-regression flow, and final board-only startup flow.

Strict safety boundary:
- Do not send MOVE or ARC.
- Do not start MCU bridge, CAN actuator, serial actuator daemon, motor, steering, brake, throttle, or any automatic vehicle-motion process.
- Allowed board/VM actions are perception-only, dry-run, file upload for scripts/docs, logs, and STM32 PING/VER/STAT/STOP.
- If a future step requires real motion, stop and ask for explicit per-command approval with command, purpose, risk, and emergency stop path.

Definition of done:
- All non-motion checks and dry-run tests have reports under docs/ and artifacts/autopark_baseline/.
- The controller and tools compile.
- The board dry-run log proves send_to_stm32=false, motion_enabled=false, and actuator_control_allowed=false for all dry-run events.
- A clear next-step checklist exists for real single-step motion testing.
```

