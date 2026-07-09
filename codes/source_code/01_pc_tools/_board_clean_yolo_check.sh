#!/bin/sh
set -eu

for pattern in sample_camera_rtsp sample_parking_yolo sample_parking_yolo_rtsp; do
  for pid in $(ps | grep "$pattern" | grep -v grep | awk '{print $1}'); do
    kill -INT "$pid" 2>/dev/null || true
  done
done

sleep 3

ps -ef | grep -E 'sample_parking_yolo|sample_camera_rtsp|board_yolo_udp_tee' | grep -v grep || true
