# Autonomous Parking Safety Checklist - 2026-06-11

## Required Gates

- No `--arm`: no motion.
- No `/tmp/parking_armed`: no motion.
- `--dry-run`: never opens motion output.
- No stable target: WAIT/STOP.
- Target lost: WAIT/STOP.
- STM32 abnormal: STOP.
- Invalid command parameter: reject before hardware access.
- Every real movement must wait for STM32 `DONE`.
- Any exception or Ctrl-C must send `STOP` in real-motion mode.

## Command Limits

Initial limits for future real-motion tests:

- max single command ground distance: 3-5 cm
- max total test distance: 30 cm
- speed gear: `V=1`
- servo range: `45 <= STE <= 135`
- preferred initial steering: near center, small offsets only

## Forbidden Until Explicit Motion Test

- `MOVE`
- `ARC`
- MCU bridge
- CAN actuator
- serial actuator daemon
- automatic controller with `--arm`
- boot-time automatic motion

