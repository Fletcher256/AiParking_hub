#!/bin/sh

#GPIO
bspmm 0x0102F0058 0x1100

#sensor0 mclk
bspmm 0x11018440  0x8010

#sensor0 clk
bspmm 0x0102F01C8 0x000002D1

#sensor0 rstn
bspmm 0x0102F01CC 0x00000201

#pwm0_0
bspmm 0x0102F01E8 0x1201

#pwm5_0
bspmm 0x0102F0154 0x1204
#bspmm 0x0102F0154 0x1100

#i2c4
bspmm 0x0102f0158 0x1202
bspmm 0x0102f015C 0x1202


bspmm 0x0102F014C 0x1200
echo 96 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio96/direction
echo 1 > /sys/class/gpio/gpio96/value
echo 0 > /sys/class/gpio/gpio96/value
echo 1 > /sys/class/gpio/gpio96/value
