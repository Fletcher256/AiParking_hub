#!/bin/sh

for b in 115200 9600 57600 38400; do
    echo "===ttyUSB0-$b==="
    stty -F /dev/ttyUSB0 "$b" cs8 -cstopb -parenb -ixon -ixoff -crtscts raw -echo
    timeout 5 dd if=/dev/ttyUSB0 bs=1 count=256 2>/dev/null | hexdump -C
done
