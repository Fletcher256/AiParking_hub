#!/bin/sh
set -eu

# Safe STM32 V2 serial check for the CH340/CH341 USB-UART on the Euler Pi.
# Sends only PING/VER/STAT. It never sends motion or actuator commands.

VID="${VID:-1a86}"
PID="${PID:-7523}"
TTY="${TTY:-/dev/ttyUSB0}"
INIT_HELPER="${INIT_HELPER:-/opt/parking/stm32_uart/ch341_user_init}"
RUN_ROOT="${RUN_ROOT:-/tmp/stm32_v2_safe_query}"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$RUN_ROOT/run_$STAMP"
OUT="$RUN_DIR/response.bin"

mkdir -p "$RUN_DIR"

find_usb_node() {
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        [ -f "$d/idProduct" ] || continue
        v="$(cat "$d/idVendor")"
        p="$(cat "$d/idProduct")"
        if [ "$v" = "$VID" ] && [ "$p" = "$PID" ]; then
            basename "$d"
            return 0
        fi
    done
    return 1
}

find_tty() {
    if [ -e "$TTY" ]; then
        echo "$TTY"
        return 0
    fi
    for dev in /dev/ttyUSB* /dev/ttyCH341USB* /dev/ttyACM*; do
        [ -e "$dev" ] || continue
        echo "$dev"
        return 0
    done
    return 1
}

USB_NODE="$(find_usb_node || true)"
if [ -z "$USB_NODE" ]; then
    echo "STM32_SAFE_QUERY=FAIL"
    echo "reason=usb_device_not_found"
    echo "vid=$VID pid=$PID"
    exit 2
fi

BUS="$(cat "/sys/bus/usb/devices/$USB_NODE/busnum")"
DEV="$(cat "/sys/bus/usb/devices/$USB_NODE/devnum")"
USBDEV="$(printf "/dev/bus/usb/%03d/%03d" "$BUS" "$DEV")"
TTY_DEV="$(find_tty || true)"

echo "STM32_SAFE_QUERY_OUT=$RUN_DIR"
echo "usb_node=$USB_NODE"
echo "usbdev=$USBDEV"
echo "tty=$TTY_DEV"
echo "init_helper=$INIT_HELPER"

if [ -z "$TTY_DEV" ]; then
    echo "STM32_SAFE_QUERY=FAIL"
    echo "reason=tty_not_found"
    exit 3
fi

if [ -x "$INIT_HELPER" ]; then
    "$INIT_HELPER" "$USBDEV" | tee "$RUN_DIR/ch341_init.txt"
else
    echo "ch341_init=skipped_missing_or_not_executable" | tee "$RUN_DIR/ch341_init.txt"
fi

stty -F "$TTY_DEV" 9600 cs8 -cstopb -parenb -ixon -ixoff -crtscts -hupcl clocal cread raw -echo min 0 time 1
stty -F "$TTY_DEV" -a > "$RUN_DIR/stty.txt" 2>&1 || true

# Drain stale data before the safe query.
drain="$RUN_DIR/drain.bin"
: > "$drain"
end=$(( $(date +%s) + 1 ))
while [ "$(date +%s)" -lt "$end" ]; do
    dd if="$TTY_DEV" bs=1 count=256 >> "$drain" 2>/dev/null || true
    sleep 0.05
done

printf '@1 PING\r' > "$TTY_DEV"
printf '@2 VER\r' > "$TTY_DEV"
printf '@3 STAT\r' > "$TTY_DEV"

: > "$OUT"
end=$(( $(date +%s) + 5 ))
while [ "$(date +%s)" -lt "$end" ]; do
    dd if="$TTY_DEV" bs=1 count=256 >> "$OUT" 2>/dev/null || true
    sleep 0.05
done

ASCII="$RUN_DIR/response_ascii.txt"
tr -cd '\11\12\15\40-\176' < "$OUT" > "$ASCII"

echo "BYTES"
wc -c "$OUT"
echo "ASCII"
sed -n '1,40p' "$ASCII"
echo "HEX"
hexdump -C "$OUT" | sed -n '1,40p'

if grep -q 'PONG' "$ASCII" && grep -q 'FW=' "$ASCII" && grep -q 'MODE=' "$ASCII"; then
    echo "STM32_SAFE_QUERY=PASS"
else
    echo "STM32_SAFE_QUERY=FAIL"
    echo "reason=missing_expected_v2_response"
    exit 4
fi
