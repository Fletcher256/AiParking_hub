#!/bin/sh
# Start camera H265 TCP streaming on SS928 board.
#
# IMPORTANT: sample_vio and sample_dtof share ot_mpi_sys_init and CANNOT
# run simultaneously.  Before running this script, make sure sample_dtof
# is NOT running:
#   killall sample_dtof
#
# Usage:
#   sh start_camera.sh           # start in foreground
#   sh start_camera.sh &         # start in background
#
# The script loads kernel modules (with camera support), then starts the
# Python TCP server which internally launches sample_vio 0 1.

set -e

echo "[start_camera] stopping any running sample_dtof..."
killall sample_dtof 2>/dev/null || true
sleep 1

echo "[start_camera] loading kernel modules with camera support..."
cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20

echo "[start_camera] starting camera TCP server..."
cd /opt/sample/mipi_rx/os08a20
python3 /opt/sample/mipi_rx/os08a20/camera_tcp_server.py
