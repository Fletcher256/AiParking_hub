#!/usr/bin/env bash
set -euo pipefail

DIR="${1:-/home/ebaina/parking_yolo_records}"
PIDFILE="$DIR/current_recording.pid"
FILEFILE="$DIR/current_recording_file.txt"

if [ ! -f "$PIDFILE" ]; then
  echo "NO_PID_FILE=$PIDFILE"
  exit 2
fi

PID="$(cat "$PIDFILE")"
if [ -f "$FILEFILE" ]; then
  LATEST="$(cat "$FILEFILE")"
else
  LATEST="$(ls -t "$DIR"/camera_rtsp_*.mp4 "$DIR"/camera_rtsp_*.mkv 2>/dev/null | head -1 || true)"
fi

echo "STOPPING_PID=$PID"
if kill -0 "$PID" 2>/dev/null; then
  kill -INT "$PID"
  for _ in $(seq 1 10); do
    if kill -0 "$PID" 2>/dev/null; then
      sleep 1
    else
      break
    fi
  done
fi

if kill -0 "$PID" 2>/dev/null; then
  echo "STILL_RUNNING=1"
else
  echo "STOPPED=1"
fi

if [ -n "$LATEST" ]; then
  echo "RECORDING_FILE=$LATEST"
  ls -lh "$LATEST"
  ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$LATEST" || true
fi
