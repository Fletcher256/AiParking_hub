#!/bin/sh
export LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib
mkdir -p /var/lib/zerotier-one
pkill zerotier-one 2>/dev/null
sleep 1
zerotier-one -d -p9993 /var/lib/zerotier-one
sleep 3
echo "ZeroTier status:"
zerotier-one -q status 2>&1
echo "Node ID:"
zerotier-one -q info 2>&1
