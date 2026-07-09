#!/usr/bin/env bash
set -euo pipefail

DIR="${1:-/home/ebaina/parking_yolo_records}"
RTSP_URL="${2:-rtsp://172.20.10.2:554/live0}"
SCALE="${3:-1920:-2}"
FPS="${4:-15}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$DIR/camera_rtsp_${STAMP}_1080p${FPS}fps.mp4"
LOG="$DIR/camera_rtsp_${STAMP}_1080p${FPS}fps.log"
PIDFILE="$DIR/current_recording.pid"
FILEFILE="$DIR/current_recording_file.txt"

mkdir -p "$DIR"

nohup bash -lc "exec ffmpeg -hide_banner -loglevel info -rtsp_transport tcp -fflags +genpts -err_detect ignore_err -i '$RTSP_URL' -an -vf 'scale=$SCALE,fps=$FPS' -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p -movflags +faststart '$OUT'" \
  > "$LOG" 2>&1 &
PID="$!"
echo "$PID" > "$PIDFILE"
echo "$OUT" > "$FILEFILE"

echo "RECORDING_PID=$PID"
echo "RECORDING_FILE=$OUT"
echo "RECORDING_LOG=$LOG"
echo "PID_FILE=$PIDFILE"
