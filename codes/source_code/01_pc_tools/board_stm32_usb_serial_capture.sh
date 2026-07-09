#!/bin/sh

# Board-side STM32 USB serial capture helper.
# This script receives only. It never writes bytes to the STM32 serial port.

VID="1a86"
PID="7523"
BAUD="9600"
CAPTURE_SECONDS="10"
COUNT="4096"
OUT_DIR="/tmp/stm32_serial_records"
DEVICE=""
BIND_GENERIC="auto"

usage() {
    cat <<'EOF'
usage: board_stm32_usb_serial_capture.sh [options]

Options:
  --vid HEX             USB vendor id, default 1a86
  --pid HEX             USB product id, default 7523
  --baud N              Serial baud rate, default 9600
  --seconds N           Max capture duration, default 10
  --bytes N             Max bytes to capture, default 4096
  --out-dir PATH        Output directory, default /tmp/stm32_serial_records
  --device PATH         Serial device. If omitted, first ttyUSB/ttyACM is used.
  --bind-generic        Bind VID:PID through usbserial_generic when needed.
  --no-bind             Do not bind; fail if no serial device exists.
  -h, --help            Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --vid) VID="$2"; shift 2 ;;
        --pid) PID="$2"; shift 2 ;;
        --baud) BAUD="$2"; shift 2 ;;
        --seconds) CAPTURE_SECONDS="$2"; shift 2 ;;
        --bytes) COUNT="$2"; shift 2 ;;
        --out-dir) OUT_DIR="$2"; shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        --bind-generic) BIND_GENERIC="yes"; shift ;;
        --no-bind) BIND_GENERIC="no"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

has_usb_device() {
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        [ -f "$d/idProduct" ] || continue
        found_vid=$(cat "$d/idVendor")
        found_pid=$(cat "$d/idProduct")
        if [ "$found_vid" = "$VID" ] && [ "$found_pid" = "$PID" ]; then
            echo "$d"
            return 0
        fi
    done
    return 1
}

find_serial_device() {
    if [ -n "$DEVICE" ] && [ -e "$DEVICE" ]; then
        echo "$DEVICE"
        return 0
    fi
    for entry in /sys/bus/usb-serial/devices/*; do
        [ -e "$entry" ] || continue
        tty=$(basename "$entry")
        [ -e "/dev/$tty" ] || continue
        echo "/dev/$tty"
        return 0
    done
    for dev in /dev/ttyUSB* /dev/ttyACM*; do
        [ -e "$dev" ] || continue
        echo "$dev"
        return 0
    done
    return 1
}

bind_generic() {
    BIND_GENERIC_ATTEMPTED="true"
    if [ ! -w /sys/bus/usb-serial/drivers/generic/new_id ]; then
        echo "generic_new_id_writable=false"
        return 1
    fi
    echo "$VID $PID" > /sys/bus/usb-serial/drivers/generic/new_id 2>/tmp/stm32_usb_serial_bind.err || true
    sleep 1
}

BIND_GENERIC_ATTEMPTED="false"
USB_PATH=$(has_usb_device || true)
if [ -z "$USB_PATH" ]; then
    echo "status=error"
    echo "reason=usb_device_not_found"
    echo "vid=$VID"
    echo "pid=$PID"
    exit 3
fi

SERIAL_DEV=$(find_serial_device || true)
if [ -z "$SERIAL_DEV" ]; then
    if [ "$BIND_GENERIC" = "yes" ] || [ "$BIND_GENERIC" = "auto" ]; then
        bind_generic
        SERIAL_DEV=$(find_serial_device || true)
    fi
fi

if [ -z "$SERIAL_DEV" ]; then
    echo "status=error"
    echo "reason=serial_device_not_found"
    echo "vid=$VID"
    echo "pid=$PID"
    exit 4
fi

mkdir -p "$OUT_DIR"
STAMP=$(date +%Y%m%d_%H%M%S 2>/dev/null || echo unknown_time)
RAW="$OUT_DIR/stm32_usb_serial_${STAMP}.bin"
HEX="$OUT_DIR/stm32_usb_serial_${STAMP}.hex"
META="$OUT_DIR/stm32_usb_serial_${STAMP}.meta"
DDLOG="$OUT_DIR/stm32_usb_serial_${STAMP}.ddlog"
STTY_OUT="$OUT_DIR/stm32_usb_serial_${STAMP}.stty.out"
STTY_STATE_PATH="$OUT_DIR/stm32_usb_serial_${STAMP}.stty.state"
DMESG_PATH="$OUT_DIR/stm32_usb_serial_${STAMP}.dmesg"

stty -F "$SERIAL_DEV" "$BAUD" cs8 -cstopb -parenb -ixon -ixoff -crtscts -hupcl clocal cread raw -echo >"$STTY_OUT" 2>&1 || true
stty -F "$SERIAL_DEV" -a >"$STTY_STATE_PATH" 2>&1 || true
dmesg | grep -i -E 'ch34|ch341|ch343|cp210|ftdi|pl2303|cdc_acm|ttyUSB|ttyACM|usb serial|usbserial|1a86|7523' | tail -120 > "$DMESG_PATH" 2>/dev/null || true

timeout "$CAPTURE_SECONDS" dd if="$SERIAL_DEV" of="$RAW" bs=1 count="$COUNT" 2>"$DDLOG"
DD_RC=$?

BYTES=$(wc -c < "$RAW" 2>/dev/null || echo 0)
hexdump -C "$RAW" > "$HEX" 2>/dev/null || true
ASCII_PREVIEW=$(tr -cd '\11\12\15\40-\176' < "$RAW" 2>/dev/null | tr '\r\n' '  ' | head -c 240)
TTY_NAME=$(basename "$SERIAL_DEV")
TTY_DRIVER=$(readlink -f "/sys/class/tty/$TTY_NAME/device/driver" 2>/dev/null || true)

{
    echo "status=ok"
    echo "usb_path=$USB_PATH"
    echo "vid=$VID"
    echo "pid=$PID"
    echo "device=$SERIAL_DEV"
    echo "tty_driver=$TTY_DRIVER"
    echo "bind_generic_mode=$BIND_GENERIC"
    echo "bind_generic_attempted=$BIND_GENERIC_ATTEMPTED"
    echo "baud=$BAUD"
    echo "seconds=$CAPTURE_SECONDS"
    echo "byte_limit=$COUNT"
    echo "bytes=$BYTES"
    echo "dd_rc=$DD_RC"
    echo "raw=$RAW"
    echo "hex=$HEX"
    echo "ddlog=$DDLOG"
    echo "stty_output=$STTY_OUT"
    echo "stty_state=$STTY_STATE_PATH"
    echo "dmesg=$DMESG_PATH"
    echo "ascii_preview=$ASCII_PREVIEW"
} > "$META"

cat "$META"
echo "HEX_PREVIEW"
head -80 "$HEX"
