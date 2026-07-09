#!/usr/bin/env bash
set -euo pipefail

STATE_DIR=${STATE_DIR:-/tmp/parking_yolo_eval}
PID_FILE="$STATE_DIR/parking_ros.pid"
START_SCRIPT=${START_SCRIPT:-/tmp/vm_start_parking_yolo_eval.sh}
RTSP_URL=${RTSP_URL:-rtsp://192.168.137.2:554/live0}
MODEL_PATH=${MODEL_PATH:-/home/ebaina/parking_models/best.onnx}

if [ -s "$PID_FILE" ]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$old" ]; then
    kill -INT "-$old" 2>/dev/null || kill -INT "$old" 2>/dev/null || true
    sleep 3
    if kill -0 "-$old" 2>/dev/null || [ -d "/proc/$old" ]; then
      kill -TERM "-$old" 2>/dev/null || kill -TERM "$old" 2>/dev/null || true
      sleep 1
    fi
    echo "STOPPED_YOLO_PID $old"
  fi
fi

for child in $(ps -eo pid,args | awk '/parking_bridge.*parking.launch.py|parking_sensor_suite|parking_yolo|parking_planner|parking_controller_dry_run/ && !/awk/ && !/vm_restart_parking_yolo_dryrun/ {print $1}'); do
  kill -INT "$child" 2>/dev/null || true
done
sleep 2
for child in $(ps -eo pid,args | awk '/parking_bridge.*parking.launch.py|parking_sensor_suite|parking_yolo|parking_planner|parking_controller_dry_run/ && !/awk/ && !/vm_restart_parking_yolo_dryrun/ {print $1}'); do
  kill -TERM "$child" 2>/dev/null || true
done

chmod +x "$START_SCRIPT"
RTSP_URL="$RTSP_URL" MODEL_PATH="$MODEL_PATH" "$START_SCRIPT"
