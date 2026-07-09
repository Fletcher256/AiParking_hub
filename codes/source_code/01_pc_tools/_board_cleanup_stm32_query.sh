#!/bin/sh
set -eu

echo BEFORE
ps -ef | grep -E 'board_parking_controller|/usr/local/bin/python3 -|PING|PWM_STAT' | grep -v grep || true

for pid in $(ps -ef | grep '/usr/local/bin/python3 -' | grep -v grep | awk '{print $1}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(ps -ef | grep 'sh -c /usr/local/bin/python3 -' | grep -v grep | awk '{print $1}'); do
  kill -TERM "$pid" 2>/dev/null || true
done

sleep 1

echo AFTER
ps -ef | grep -E 'board_parking_controller|/usr/local/bin/python3 -|PING|PWM_STAT' | grep -v grep || true
echo TTY
ls -l /dev/ttyUSB* 2>/dev/null || true
echo DRIVER_STATUS
cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true
