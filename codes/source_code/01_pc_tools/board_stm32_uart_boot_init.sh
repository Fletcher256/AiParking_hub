#!/bin/sh
set -u

# Boot-time STM32 USB-UART link initializer for Euler Pi.
# It initializes the CH340/CH341 USB-UART and optionally runs a safe V2 query.
# Safe query sends only PING/VER/STAT, never motion or actuator commands.

VID="${VID:-1a86}"
PID="${PID:-7523}"
TTY="${TTY:-/dev/ttyUSB0}"
BASE_DIR="${BASE_DIR:-/opt/parking/stm32_uart}"
INIT_HELPER="${INIT_HELPER:-$BASE_DIR/ch341_user_init}"
SAFE_QUERY="${SAFE_QUERY:-$BASE_DIR/stm32_v2_safe_query.sh}"
LOG="${LOG:-/tmp/parking_stm32_uart_boot.log}"
STATUS="${STATUS:-/tmp/parking_stm32_uart_boot_status.json}"
MAX_WAIT_SEC="${MAX_WAIT_SEC:-60}"
QUERY_AFTER_INIT="${QUERY_AFTER_INIT:-1}"

now_sec() {
    date +%s 2>/dev/null || echo 0
}

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

write_status() {
    state="$1"
    reason="$2"
    usb_node="${3:-}"
    tty_dev="${4:-}"
    extra="${5:-}"
    ts="$(now_sec)"
    tmp="${STATUS}.$$"
    cat > "$tmp" <<EOF
{"time_sec":$ts,"state":"$(json_escape "$state")","reason":"$(json_escape "$reason")","vid":"$VID","pid":"$PID","usb_node":"$(json_escape "$usb_node")","tty":"$(json_escape "$tty_dev")","extra":"$(json_escape "$extra")"}
EOF
    mv "$tmp" "$STATUS"
}

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

{
    echo "STM32_UART_BOOT_BEGIN $(now_sec)"
    echo "vid=$VID pid=$PID tty_preferred=$TTY base_dir=$BASE_DIR"

    start="$(now_sec)"
    usb_node=""
    tty_dev=""
    while :; do
        usb_node="$(find_usb_node || true)"
        tty_dev="$(find_tty || true)"
        if [ -n "$usb_node" ] && [ -n "$tty_dev" ]; then
            break
        fi
        elapsed=$(( $(now_sec) - start ))
        if [ "$elapsed" -ge "$MAX_WAIT_SEC" ]; then
            echo "STM32_UART_BOOT_TIMEOUT usb_node=$usb_node tty=$tty_dev"
            write_status "failed" "timeout_waiting_for_usb_uart" "$usb_node" "$tty_dev"
            exit 0
        fi
        sleep 2
    done

    bus="$(cat "/sys/bus/usb/devices/$usb_node/busnum")"
    dev="$(cat "/sys/bus/usb/devices/$usb_node/devnum")"
    usbdev="$(printf "/dev/bus/usb/%03d/%03d" "$bus" "$dev")"
    echo "usb_node=$usb_node usbdev=$usbdev tty=$tty_dev"

    if [ -x "$INIT_HELPER" ]; then
        "$INIT_HELPER" "$usbdev"
        init_rc="$?"
    else
        echo "CH341_INIT_HELPER_MISSING $INIT_HELPER"
        init_rc="127"
    fi
    echo "ch341_init_rc=$init_rc"

    if [ "$init_rc" != "0" ]; then
        write_status "failed" "ch341_init_failed" "$usb_node" "$tty_dev" "rc=$init_rc"
        exit 0
    fi

    stty -F "$tty_dev" 9600 cs8 -cstopb -parenb -ixon -ixoff -crtscts -hupcl clocal cread raw -echo min 0 time 1 2>/dev/null || true

    if [ "$QUERY_AFTER_INIT" = "1" ] && [ -x "$SAFE_QUERY" ]; then
        echo "STM32_UART_BOOT_SAFE_QUERY_BEGIN"
        "$SAFE_QUERY"
        query_rc="$?"
        echo "STM32_UART_BOOT_SAFE_QUERY_RC=$query_rc"
        if [ "$query_rc" = "0" ]; then
            write_status "ready" "safe_query_pass" "$usb_node" "$tty_dev"
        else
            write_status "initialized" "safe_query_failed" "$usb_node" "$tty_dev" "rc=$query_rc"
        fi
    else
        write_status "initialized" "ch341_init_only" "$usb_node" "$tty_dev"
    fi

    echo "STM32_UART_BOOT_END $(now_sec)"
} >> "$LOG" 2>&1

exit 0
