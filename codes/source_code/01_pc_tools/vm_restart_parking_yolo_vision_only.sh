#!/usr/bin/env bash
set -euo pipefail

STATE_DIR=${STATE_DIR:-/tmp/parking_yolo_vision_only}
PID_FILE="$STATE_DIR/parking_ros.pid"
START_SCRIPT=${START_SCRIPT:-/tmp/vm_start_parking_yolo_vision_only.sh}
RTSP_URL=${RTSP_URL:-rtsp://192.168.137.2:554/live0}
MODEL_PATH=${MODEL_PATH:-/home/ebaina/parking_models/best.onnx}

stop_pid() {
  local pid="$1"
  local label="$2"
  if [ -z "$pid" ] || [ ! -d "/proc/$pid" ]; then
    return 0
  fi
  echo "VM_STOP_PERCEPTION_${label}_PID $pid"
  kill -INT "$pid" 2>/dev/null || true
}

if [ -s "$PID_FILE" ]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  stop_pid "$old" "RECORDED"
fi

awk_pattern='parking_bridge.*parking.launch.py|parking_sensor_suite|parking_vision_preprocess|vision_preprocess_node|parking_yolo|parking_planner|parking_controller_dry_run|ffmpeg .*rtsp://192[.]168[.]137[.]2:554/live0'
for child in $(ps -eo pid,args | awk -v pat="$awk_pattern" '$0 ~ pat && $0 !~ /awk/ && $0 !~ /vm_restart_parking_yolo_vision_only/ {print $1}'); do
  stop_pid "$child" "MATCHED"
done

sleep 2
for child in $(ps -eo pid,args | awk -v pat="$awk_pattern" '$0 ~ pat && $0 !~ /awk/ && $0 !~ /vm_restart_parking_yolo_vision_only/ {print $1}'); do
  if [ -d "/proc/$child" ]; then
    echo "VM_TERM_PERCEPTION_MATCHED_PID $child"
    kill -TERM "$child" 2>/dev/null || true
  fi
done

RTSP_URL="$RTSP_URL" MODEL_PATH="$MODEL_PATH" STATE_DIR="$STATE_DIR" bash "$START_SCRIPT"
