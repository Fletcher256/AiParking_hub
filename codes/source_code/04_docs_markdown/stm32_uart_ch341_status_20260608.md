# STM32 UART Link Status - 2026-06-08

## Current Result

Board-to-STM32 communication through the USB-to-UART cable is working.

The board sees the adapter as:

- USB VID/PID: `1a86:7523`
- TTY: `/dev/ttyUSB0`
- Board driver path: generic USB serial fallback

The STM32 V2 safe query succeeds after the CH340/CH341 userspace initializer runs.

Verified response:

```text
DONE 1 PING PONG
VER 2 FW=SS928-CTRL-2.0 BAUD=9600 PROTO=2
STAT 3 MODE=IDLE RUN=STANDBY DIR=1 SPD=0 ANG=90.0 ... DROP=0
STM32_SAFE_QUERY=PASS
```

## Root Cause

The PC can talk to the same STM32 and cable because Windows uses a proper CH340/CH341 driver.

The Euler Pi board currently exposes the adapter through `usbserial_generic`, which creates `/dev/ttyUSB0` but does not fully initialize the CH340/CH341 chip for this STM32 link. Running a small userspace CH341 initializer before opening the serial port fixes the board-side communication.

## Board Files

Persistent board files:

```text
/opt/parking/stm32_uart/ch341_user_init
/opt/parking/stm32_uart/stm32_v2_safe_query.sh
/opt/parking/stm32_uart/board_stm32_usb_serial_udp_bridge.py
/opt/parking/stm32_uart/stm32_uart_boot_init.sh
/etc/init.d/S98stm32uart
```

The safe query script sends only:

```text
@1 PING
@2 VER
@3 STAT
```

It does not send motion or actuator commands.

## Boot Autostart

The board uses BusyBox init. `/etc/init.d/rcS` runs executable scripts matching `/etc/init.d/S[0-9][0-9]*`.

The STM32 USB-UART link is now initialized at boot by:

```text
/etc/init.d/S98stm32uart
```

That init entry starts this background initializer:

```text
/opt/parking/stm32_uart/stm32_uart_boot_init.sh
```

Boot initializer behavior:

- Waits up to 60 seconds for USB VID/PID `1a86:7523`.
- Runs `/opt/parking/stm32_uart/ch341_user_init` on the matching `/dev/bus/usb/...` node.
- Applies 9600 8N1 settings to `/dev/ttyUSB0`.
- Runs the safe query by default: `PING`, `VER`, `STAT`.
- Writes logs to `/tmp/parking_stm32_uart_boot.log`.
- Writes status to `/tmp/parking_stm32_uart_boot_status.json`.

Manual boot-init simulation passed:

```text
S98STM32UART_STARTED ...
STM32_SAFE_QUERY=PASS
{"state":"ready","reason":"safe_query_pass","vid":"1a86","pid":"7523","tty":"/dev/ttyUSB0"}
```

Actual reboot validation has not been run yet in this step.

## Reproducible Command

From Windows:

```powershell
tools\stm32_board_safe_query.bat
```

Equivalent direct command:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 60 --allow-risk "/opt/parking/stm32_uart/stm32_v2_safe_query.sh"
```

## Next Engineering Step

Use the same CH341 initialization before any board-side telemetry receiver opens `/dev/ttyUSB0`.

Do not start movement commands until the perception and safety gates are implemented.

## Check Boot Link Status

From Windows:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 30 "cat /tmp/parking_stm32_uart_boot_status.json; tail -80 /tmp/parking_stm32_uart_boot.log"
```

## Disable Boot Autostart

Disable only the STM32 UART boot initializer:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 30 --allow-risk "chmod -x /etc/init.d/S98stm32uart"
```

Re-enable:

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 30 --allow-risk "chmod +x /etc/init.d/S98stm32uart"
```
