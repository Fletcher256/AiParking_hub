#!/bin/sh

#pwm0_0
bspmm 0x0102F01E8 0x1201 > /dev/null

#pwm0_5
bspmm 0x0102F0154 0x1204 > /dev/null

#GPIO12_0
bspmm 0x0102F014C 0x1200 > /dev/null

set_gpio_out()
{
	local gpio_num=$1

	if [ ! -d "/sys/class/gpio/gpio$gpio_num" ]; then
		echo "$gpio_num" > /sys/class/gpio/export
	fi

	echo out > "/sys/class/gpio/gpio$gpio_num/direction"

	echo 1 > "/sys/class/gpio/gpio$gpio_num/value"
	echo 0 > "/sys/class/gpio/gpio$gpio_num/value"
	echo 1 > "/sys/class/gpio/gpio$gpio_num/value"
}

#2路dtof复位均为SENSOR1_RSTN，同时运行时会复位前一个dtof
#这里需要将SENSOR1_RSTN复用为GPIO控制2路dtof
#dtof0-1复位
set_gpio_out 96
