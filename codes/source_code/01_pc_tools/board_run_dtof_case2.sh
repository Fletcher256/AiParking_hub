#!/bin/sh
set -e

for pid in $(ps | awk '/[s]ample_dtof/ {print $1}'); do
  kill "$pid" 2>/dev/null || true
done
sleep 2

mkdir -p /tmp/parking_sensor_link
rm -f /tmp/parking_sensor_link/case2.stdin /tmp/parking_sensor_link/case2.log /tmp/parking_sensor_link/case2.pid
mkfifo /tmp/parking_sensor_link/case2.stdin

(
  cd /opt/sample/official_dtof
  ./dtof_init.sh
  cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
  cd /opt/sample/official_dtof
  echo BOARD_CASE2_BINARY ./sample_dtof_rtsp_sensor3_keepattr_dbg
  cat /tmp/parking_sensor_link/case2.stdin | ./sample_dtof_rtsp_sensor3_keepattr_dbg 2 192.168.137.100
  echo CASE2_EXIT_CODE=$?
) > /tmp/parking_sensor_link/case2.log 2>&1 &

echo $! > /tmp/parking_sensor_link/case2.pid
sleep 5
tail -80 /tmp/parking_sensor_link/case2.log
