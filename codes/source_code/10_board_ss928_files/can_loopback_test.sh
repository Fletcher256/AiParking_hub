#!/bin/sh
set -eu

ip link set can0 down || true
ip link set can0 type can bitrate 500000 loopback on
ip link set can0 up
echo "can0 loopback enabled"
ip -details link show can0 | sed -n '1,8p'

tmp=/tmp/can_loopback_dump.txt
rm -f "$tmp"
timeout 3 candump -L can0 > "$tmp" 2>&1 &
pid=$!
sleep 0.3
cansend can0 402#FFFFFFFFFFFFFFFF
sleep 0.7
wait "$pid" || true

echo "candump output:"
cat "$tmp"
echo "can0 statistics:"
ip -statistics link show can0 | sed -n '1,8p'
