#!/bin/sh

# Late boot repair for the receive-only parking link.
# It only restores the wired board IP and records USB serial driver status.
# It does not open the STM32 serial port and does not start control software.

LOG="${LOG:-/tmp/parking_link_init.log}"

{
	echo "PARKING_LINK_INIT_BEGIN $(date +%s 2>/dev/null || echo 0)"
	sleep "${PARKING_LINK_INIT_DELAY:-8}"

	if [ -x /etc/init.d/S81wired137 ]; then
		echo "PARKING_LINK_INIT_WIRED137"
		sh /etc/init.d/S81wired137 || true
	fi

	if [ -x /etc/udev/ch341-autobind.sh ]; then
		echo "PARKING_LINK_INIT_CH341_STATUS"
		sh /etc/udev/ch341-autobind.sh || true
	fi

	cat /tmp/stm32_usb_serial_driver_status.json 2>/dev/null || true
	echo "PARKING_LINK_INIT_END $(date +%s 2>/dev/null || echo 0)"
} >> "$LOG" 2>&1 &

exit 0
