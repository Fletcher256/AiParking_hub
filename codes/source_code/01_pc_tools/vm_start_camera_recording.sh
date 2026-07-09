#!/usr/bin/env bash
set -euo pipefail

DIR="${1:-/home/ebaina/parking_yolo_records}"
RTSP_URL="${2:-rtsp://172.20.10.2:554/live0}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$DIR/camera_rtsp_${STAMP}.mkv"
LOG="$DIR/camera_rtsp_${STAMP}.log"
PIDFILE="$DIR/current_recording.pid"

mkdir -p "$DIR"

nohup bash -lc "exec ffmpeg -hide_banner -loglevel info -rtsp_transport tcp -fflags +genpts -i '$RTSP_URL' -an -map 0:v:0 -c:v copy -f matroska '$OUT'" \
  > "$LOG" 2>&1 &
PID="$!"
echo "$PID" > "$PIDFILE"

echo "RECORDING_PID=$PID"
echo "RECORDING_FILE=$OUT"
echo "RECORDING_LOG=$LOG"
echo "PID_FILE=$PIDFILE"
