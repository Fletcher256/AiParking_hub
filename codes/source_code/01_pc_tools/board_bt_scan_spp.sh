#!/bin/sh
set -eu

dbus_path="$(awk '/@\/tmp\/dbus-/ {p=$8; sub(/^@/, "", p); print p; exit}' /proc/net/unix)"
if [ -z "$dbus_path" ]; then
    echo "NO_DBUS_BUS"
    exit 2
fi

export DBUS_SESSION_BUS_ADDRESS="unix:abstract=$dbus_path"
export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"

echo "DBUS=$DBUS_SESSION_BUS_ADDRESS"
echo "CONTROLLER_BEFORE"
bluetoothctl list || true
bluetoothctl power on || true
bluetoothctl pairable on || true

echo "SCAN_INTERACTIVE_BEGIN"
(
    echo "agent KeyboardOnly"
    echo "default-agent"
    echo "scan clear"
    echo "scan duplicate-data on"
    echo "scan on"
    sleep 35
    echo "devices"
    echo "scan off"
    echo "quit"
) | bluetoothctl 2>&1
echo "SCAN_INTERACTIVE_END"

echo "DEVICES_FINAL"
bluetoothctl devices || true
