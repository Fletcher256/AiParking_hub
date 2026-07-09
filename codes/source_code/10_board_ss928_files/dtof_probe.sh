#!/bin/sh
set -eu

echo "== spi devices =="
for d in /sys/bus/spi/devices/*; do
  [ -e "$d" ] || continue
  echo "-- $d --"
  readlink -f "$d" || true
  for f in modalias driver_override statistics; do
    [ -f "$d/$f" ] && printf "%s: " "$f" && cat "$d/$f" || true
  done
  [ -L "$d/driver" ] && printf "driver: " && basename "$(readlink -f "$d/driver")"
done

echo "== can state =="
ip -details -statistics link show can0 || true

echo "== interrupts =="
cat /proc/interrupts | grep -Ei 'spi|can|mcp|11094000|gpio' || true

echo "== loaded modules =="
cat /proc/modules | grep -Ei 'can|mcp|spi' || true
