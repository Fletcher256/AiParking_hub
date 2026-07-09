# Real-Car Single-Step Test Checklist - 2026-06-11

Do not use this checklist until the non-motion dry-run path has stable candidate
events in the current physical scene.

## Pre-Test Physical Conditions

- Vehicle is in a clear area.
- A human can physically stop or lift the vehicle.
- Battery is stable.
- Camera mount is fixed.
- Wheels and steering linkage are visible.
- No one is in front of or behind the vehicle.
- The intended first movement is no more than 3-5 cm.

## Software Conditions

- Board SSH is online.
- STM32 `STAT` returns `MODE=IDLE RUN=STANDBY SPD=0`.
- `STOP` returns `DONE`.
- No MCU bridge, CAN actuator, serial actuator daemon, or old controller process
  is running.
- YOLO local dry-run is stable.
- Candidate command has been printed and reviewed.

## First Motion Sequence

The first real movement should be manual, one command only:

1. Send `STAT`.
2. Send `STOP`.
3. Send one tiny `MOVE` or `ARC`.
4. Wait for `DONE`.
5. Send `STAT`.
6. Record actual movement and steering direction.
7. Send `STOP`.

Do not start automatic multi-step parking until:

- `D<0` direction is confirmed.
- `STE<90` and `STE>90` directions are confirmed.
- actual distance roughly matches command distance.
- STOP behavior is reliable.

