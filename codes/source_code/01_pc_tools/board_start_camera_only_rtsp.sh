#!/bin/sh
set -eu

FIFO="${FIFO:-/tmp/camera_only_rtsp.stdin}"
LOG="${LOG:-/tmp/camera_only_rtsp.log}"
PIDFILE="${PIDFILE:-/tmp/camera_only_rtsp.pid}"
BIN_DIR="${BIN_DIR:-/opt/sample/camera_only}"
BIN="${BIN:-./sample_camera_rtsp}"
DST_IP="${DST_IP:-192.168.137.100}"

if [ -s "$PIDFILE" ]; then
    old="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$old" ] && [ -d "/proc/$old" ]; then
        echo "CAMERA_ONLY_ALREADY_RUNNING $old"
        echo "CAMERA_ONLY_LOG $LOG"
        exit 0
    fi
fi

rm -f "$FIFO"
mkfifo "$FIFO"

(
    cd /opt/ko
    ./load_ss928v100 -a -sensor0 os08a20
    cd "$BIN_DIR"
    echo "BOARD_CAMERA_BINARY $BIN"
    cat "$FIFO" | "$BIN" 8 "$DST_IP"
    echo "CAMERA_ONLY_EXIT_CODE=$?"
) > "$LOG" 2>&1 &

pid="$!"
echo "$pid" > "$PIDFILE"
echo "CAMERA_ONLY_PID $pid"
echo "CAMERA_ONLY_LOG $LOG"
