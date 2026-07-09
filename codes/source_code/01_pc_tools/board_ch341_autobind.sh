#!/bin/sh

# Receive-path helper for the CH340/CH341 USB serial adapter.
# It never opens the serial port and never writes bytes to STM32. If no proper
# CH341 driver creates a tty, it falls back to usbserial_generic and records
# that status explicitly.

VID="${VID:-1a86}"
PID="${PID:-7523}"
STATUS="${STATUS:-/tmp/stm32_usb_serial_driver_status.json}"

find_usb_path() {
	for d in /sys/bus/usb/devices/*; do
		[ -f "$d/idVendor" ] || continue
		[ -f "$d/idProduct" ] || continue
		v=$(cat "$d/idVendor")
		p=$(cat "$d/idProduct")
		if [ "$v" = "$VID" ] && [ "$p" = "$PID" ]; then
			echo "$d"
			return 0
		fi
	done
	return 1
}

find_serial_name() {
	for name in ttyCH341USB* ttyUSB* ttyACM*; do
		for dev in /dev/$name; do
			[ -e "$dev" ] || continue
			basename "$dev"
			return 0
		done
	done
	return 1
}

driver_name_for_tty() {
	tty="$1"
	[ -n "$tty" ] || return 1
	path=$(readlink -f "/sys/bus/usb-serial/devices/$tty/driver" 2>/dev/null)
	if [ -n "$path" ]; then
		basename "$path"
		return 0
	fi
	return 1
}

write_status() {
	status="$1"
	usb_path="$2"
	tty="$3"
	driver="$4"
	mode="$5"
	attempted="$6"
	now=$(date +%s 2>/dev/null || echo 0)
	tmp="${STATUS}.$$"
	cat > "$tmp" <<EOF
{"time_sec":$now,"status":"$status","vid":"$VID","pid":"$PID","usb_path":"$usb_path","tty":"$tty","driver":"$driver","driver_mode":"$mode","generic_bind_attempted":$attempted}
EOF
	mv "$tmp" "$STATUS"
}

usb_path=$(find_usb_path || true)
if [ -z "$usb_path" ]; then
	write_status "usb_device_not_found" "" "" "" "missing" false
	exit 0
fi

tty=$(find_serial_name || true)
driver=$(driver_name_for_tty "$tty" || true)
if [ -n "$tty" ]; then
	case "$driver" in
	ch341) mode="formal_ch341" ;;
	generic) mode="generic_fallback" ;;
	*) mode="other" ;;
	esac
	write_status "serial_ready" "$usb_path" "/dev/$tty" "$driver" "$mode" false
	exit 0
fi

if [ -d /sys/bus/usb-serial/drivers/ch341 ]; then
	write_status "waiting_for_ch341_tty" "$usb_path" "" "ch341" "formal_ch341" false
	exit 0
fi

if [ -e /sys/bus/usb-serial/drivers/generic/new_id ]; then
	echo "$VID $PID" > /sys/bus/usb-serial/drivers/generic/new_id 2>/dev/null || true
	sleep 1
	tty=$(find_serial_name || true)
	driver=$(driver_name_for_tty "$tty" || true)
	if [ -n "$tty" ]; then
		write_status "serial_ready" "$usb_path" "/dev/$tty" "$driver" "generic_fallback" true
	else
		write_status "generic_bind_failed" "$usb_path" "" "$driver" "generic_fallback" true
	fi
	exit 0
fi

write_status "no_usable_driver" "$usb_path" "" "" "missing" false
exit 0
