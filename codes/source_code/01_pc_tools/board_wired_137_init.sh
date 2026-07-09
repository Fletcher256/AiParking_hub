#!/bin/sh

# Keep the direct Windows/VM wired link available after board reboot.
# Prefer the BusyBox ip applet; /usr/local/bin/ip needs /usr/local/lib during
# early boot and can fail before the library path is exported.
IP_BIN="${IP_BIN:-/sbin/ip}"
if [ ! -x "$IP_BIN" ]; then
	IP_BIN="$(command -v ip 2>/dev/null || echo /usr/local/bin/ip)"
fi

if ! "$IP_BIN" addr show dev eth0 | grep -q '192.168.137.2/24'; then
	"$IP_BIN" addr add 192.168.137.2/24 dev eth0
fi
"$IP_BIN" link set eth0 up
