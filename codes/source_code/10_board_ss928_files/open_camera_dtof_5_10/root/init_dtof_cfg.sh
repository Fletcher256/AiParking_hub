#!/bin/sh

bspmm 0x0102F014C 0x1200
echo 96 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio96/direction
echo 1 > /sys/class/gpio/gpio96/value
echo 0 > /sys/class/gpio/gpio96/value
echo 1 > /sys/class/gpio/gpio96/value
