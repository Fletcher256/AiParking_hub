#!/bin/sh
set -eu

mac="${1:-79:62:C4:AE:41:26}"

dbus_path="$(awk '/@\/tmp\/dbus-/ {p=$8; sub(/^@/, "", p); print p; exit}' /proc/net/unix)"
if [ -z "$dbus_path" ]; then
    echo "NO_DBUS_BUS"
    exit 2
fi

export DBUS_SESSION_BUS_ADDRESS="unix:abstract=$dbus_path"
export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"

echo "DBUS=$DBUS_SESSION_BUS_ADDRESS"
echo "TARGET=$mac"

(
    echo "agent KeyboardOnly"
    echo "default-agent"
    echo "power on"
    echo "pairable on"
    echo "scan on"
    sleep 5
    echo "pair $mac"
    sleep 2
    echo "1234"
    sleep 8
    echo "trust $mac"
    echo "connect $mac"
    sleep 8
    echo "info $mac"
    echo "quit"
) | bluetoothctl 2>&1

echo "PAIRED_DEVICES"
bluetoothctl paired-devices || true
echo "DEVICE_INFO"
bluetoothctl info "$mac" || true
