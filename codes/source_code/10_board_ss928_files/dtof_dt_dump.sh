#!/bin/sh
set -eu

node=/sys/firmware/devicetree/base/soc/amba/spi@11070000/can@0
cd "$node"
for f in compatible interrupts reg spi-max-frequency status clocks interrupt-parent; do
  echo "== $f =="
  hexdump -Cv "$f"
done
