#!/bin/sh

echo 1a86 7523 > /sys/bus/usb-serial/drivers/generic/new_id
sleep 1

echo "DEV_TTY"
ls -l /dev | grep -E 'ttyUSB|ttyACM' || true

echo "USB_SERIAL_DEVICES"
find /sys/bus/usb-serial/devices -maxdepth 2 -print 2>/dev/null || true

echo "DMESG"
dmesg | grep -i -E 'ttyUSB|ttyACM|usb serial|usbserial|1a86|7523|ch34|ch341' | tail -100 || true
