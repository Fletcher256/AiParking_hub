#!/bin/sh

echo "SET_9600_8N1"
stty -F /dev/ttyUSB0 9600 cs8 -cstopb -parenb -ixon -ixoff raw -echo 2>&1 || true

echo "STTY_STATE"
stty -F /dev/ttyUSB0 -a 2>&1 || true

echo "READ_512"
timeout 10 dd if=/dev/ttyUSB0 bs=1 count=512 2>/dev/null | hexdump -C
