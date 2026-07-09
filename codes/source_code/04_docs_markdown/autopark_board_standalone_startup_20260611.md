# Final Board-Only Startup Flow - Draft - 2026-06-11

This is the intended future flow after dry-run, single-step, and semi-auto tests
pass. It is not yet approved for real motion.

## Manual Board-Only Runtime

1. Initialize STM32 UART at boot.
2. Start YOLO with local UDP:

```text
PARKING_YOLO_UDP_HOST=127.0.0.1
PARKING_YOLO_UDP_PORT=24580
```

3. Verify `STAT`:

```text
MODE=IDLE RUN=STANDBY SPD=0
```

4. Run dry-run first:

```sh
/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --dry-run --duration-sec 60 --log-jsonl /tmp/parking_dry_run.jsonl
```

5. Only after dry-run and single-step checks pass, real motion mode would require
   both:

```text
--arm
/tmp/parking_armed exists
```

## Principle

Boot may initialize sensors and UART. Boot must never start vehicle motion.

Real automatic parking should remain a deliberate manual action until the
single-step and semi-auto tests are repeatedly safe.

