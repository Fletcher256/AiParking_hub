#!/bin/sh
set -eu

APP_DIR=${APP_DIR:-/opt/sample/parking_yolo_seg_safe}
AUTOPARK_DIR=${AUTOPARK_DIR:-/opt/parking/autopark}
DEFAULT_BIN=./sample_parking_yolo_rtsp_conf06_quiet_displayoff
if [ -z "${BIN:-}" ]; then
  if [ -x "$APP_DIR/$DEFAULT_BIN" ]; then
    BIN="$DEFAULT_BIN"
  else
    BIN=./sample_parking_yolo_rtsp
  fi
fi
LOG=${LOG:-/tmp/parking_yolo_closed_loop_monitor.log}
PID_FILE=${PID_FILE:-/tmp/parking_yolo_closed_loop_monitor.pid}
TEE_LOG=${TEE_LOG:-/tmp/parking_yolo_udp_tee.log}
TEE_PID_FILE=${TEE_PID_FILE:-/tmp/parking_yolo_udp_tee.pid}
STDIN_FIFO=${STDIN_FIFO:-/tmp/parking_yolo_closed_loop_monitor.stdin}
FIFO_WRITER_PID_FILE=${FIFO_WRITER_PID_FILE:-/tmp/parking_yolo_closed_loop_monitor.stdin_writer.pid}
CLEANUP_BIN=${CLEANUP_BIN:-/opt/parking/autopark/mpp_sys_vb_exit}
VPSS_FMT_BIN=${VPSS_FMT_BIN:-/opt/parking/autopark/board_vpss_set_pixel_format}
VPSS_ROT_BIN=${VPSS_ROT_BIN:-/opt/parking/autopark/board_vpss_set_rotation}
ACTION=${ACTION:-start}

TEE_HOST=${TEE_HOST:-127.0.0.1}
TEE_PORT=${TEE_PORT:-24579}
LOCAL_CONTROLLER_HOST=${LOCAL_CONTROLLER_HOST:-127.0.0.1}
LOCAL_CONTROLLER_PORT=${LOCAL_CONTROLLER_PORT:-24580}
VM_HOST=${VM_HOST:-192.168.137.100}
VM_DET_PORT=${VM_DET_PORT:-24580}
VM_IMAGE_PORT=${VM_IMAGE_PORT:-24581}

pid_alive() {
  pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_pid_exit() {
  pid="$1"
  limit="$2"
  i=0
  while [ "$i" -lt "$limit" ]; do
    if ! pid_alive "$pid"; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

vb_max_pool_cnt() {
  if [ ! -r /proc/umap/vb ]; then
    echo 0
    return
  fi
  awk '/max_pool_cnt/{getline; gsub(/^[ \t]+|[ \t]+$/, "", $0); print $0; exit}' /proc/umap/vb 2>/dev/null || echo 0
}

wait_vb_clean() {
  i=0
  while [ "$i" -lt "${VB_CLEAN_WAIT_SEC:-20}" ]; do
    vb_cnt="$(vb_max_pool_cnt)"
    if [ "${vb_cnt:-0}" = "0" ]; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  vb_cnt="$(vb_max_pool_cnt)"
  echo "BOARD_YOLO_REFUSE_DIRTY_VB max_pool_cnt=${vb_cnt:-unknown}" >&2
  echo "BOARD_YOLO_REFUSE_DIRTY_VB_HINT reboot board before restarting camera/YOLO" >&2
  cat /proc/umap/vb 2>/dev/null | head -40 >&2 || true
  return 1
}

run_mpp_cleanup_if_dirty() {
  vb_cnt="$(vb_max_pool_cnt)"
  if [ "${vb_cnt:-0}" = "0" ]; then
    return 0
  fi
  if [ ! -x "$CLEANUP_BIN" ]; then
    echo "BOARD_YOLO_CLEANUP_SKIP missing_cleanup_bin=$CLEANUP_BIN max_pool_cnt=${vb_cnt:-unknown}" >&2
    return 0
  fi
  echo "BOARD_YOLO_CLEANUP_RUN $CLEANUP_BIN max_pool_cnt=${vb_cnt:-unknown}"
  "$CLEANUP_BIN" || true
}

stop_fifo_writer() {
  if [ -s "$FIFO_WRITER_PID_FILE" ]; then
    writer_pid="$(cat "$FIFO_WRITER_PID_FILE" 2>/dev/null || true)"
    if [ -n "$writer_pid" ]; then
      kill "$writer_pid" 2>/dev/null || true
    fi
    rm -f "$FIFO_WRITER_PID_FILE"
  fi
}

stop_yolo_pid() {
  pid="$1"
  if ! pid_alive "$pid"; then
    return 0
  fi

  if [ -p "$STDIN_FIFO" ]; then
    echo "BOARD_YOLO_STOP stdin_newline pid=$pid"
    ( printf '\n' > "$STDIN_FIFO" ) 2>/dev/null || true
    if wait_pid_exit "$pid" "${YOLO_STDIN_STOP_WAIT_SEC:-25}"; then
      stop_fifo_writer
      return 0
    fi
  fi

  echo "BOARD_YOLO_STOP sigint pid=$pid" >&2
  kill -INT "$pid" 2>/dev/null || true
  if wait_pid_exit "$pid" "${YOLO_SIGINT_WAIT_SEC:-15}"; then
    stop_fifo_writer
    return 0
  fi

  echo "BOARD_YOLO_STOP sigterm pid=$pid" >&2
  kill -TERM "$pid" 2>/dev/null || true
  if wait_pid_exit "$pid" "${YOLO_SIGTERM_WAIT_SEC:-10}"; then
    stop_fifo_writer
    return 0
  fi

  echo "BOARD_YOLO_STOP still_running pid=$pid" >&2
  return 1
}

stop_tee_pid() {
  pid="$1"
  if ! pid_alive "$pid"; then
    return 0
  fi
  kill -INT "$pid" 2>/dev/null || true
  if wait_pid_exit "$pid" "${TEE_STOP_WAIT_SEC:-5}"; then
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null || true
  wait_pid_exit "$pid" "${TEE_STOP_WAIT_SEC:-5}" || true
}

if [ -s "$PID_FILE" ]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$old" ]; then
    stop_yolo_pid "$old" || true
  fi
fi

if [ -s "$TEE_PID_FILE" ]; then
  old="$(cat "$TEE_PID_FILE" 2>/dev/null || true)"
  if [ -n "$old" ]; then
    stop_tee_pid "$old"
  fi
fi

for pattern in sample_camera_rtsp sample_parking_yolo sample_parking_yolo_rtsp; do
  for pid in $(ps | grep "$pattern" | grep -v grep | awk '{print $1}'); do
    stop_yolo_pid "$pid" || true
  done
done

for pid in $(ps | grep "board_yolo_udp_tee.py" | grep -v grep | awk '{print $1}'); do
  stop_tee_pid "$pid"
done

run_mpp_cleanup_if_dirty
wait_vb_clean

if [ "$ACTION" = "stop" ]; then
  echo "BOARD_YOLO_STOP_ONLY_DONE"
  exit 0
fi

nohup /usr/local/bin/python3 "$AUTOPARK_DIR/board_yolo_udp_tee.py" \
  --listen-host "$TEE_HOST" \
  --listen-port "$TEE_PORT" \
  --target "${LOCAL_CONTROLLER_HOST}:${LOCAL_CONTROLLER_PORT}" \
  --target "${VM_HOST}:${VM_DET_PORT}" \
  > "$TEE_LOG" 2>&1 &
tee_pid=$!
echo "$tee_pid" > "$TEE_PID_FILE"

cd "$APP_DIR"
export LD_LIBRARY_PATH=/opt/lib/npu:/opt/lib:${LD_LIBRARY_PATH:-}
export PARKING_YOLO_UDP_HOST="$TEE_HOST"
export PARKING_YOLO_UDP_PORT="$TEE_PORT"
export PARKING_YOLO_IMAGE_UDP_HOST="$VM_HOST"
export PARKING_YOLO_IMAGE_UDP_PORT="$VM_IMAGE_PORT"
export PARKING_YOLO_IMAGE_STRIDE="${PARKING_YOLO_IMAGE_STRIDE:-30}"
export PARKING_YOLO_RUN_FOREVER="${PARKING_YOLO_RUN_FOREVER:-0}"
export PARKING_YOLO_LOWLIGHT_AE="${PARKING_YOLO_LOWLIGHT_AE:-1}"
export PARKING_YOLO_AE_COMPENSATION="${PARKING_YOLO_AE_COMPENSATION:-96}"
export PARKING_YOLO_AE_MIN_EXP_US="${PARKING_YOLO_AE_MIN_EXP_US:-0}"
export PARKING_YOLO_AE_MAX_EXP_US="${PARKING_YOLO_AE_MAX_EXP_US:-944036}"
export PARKING_YOLO_VPSS_ROTATE180="${PARKING_YOLO_VPSS_ROTATE180:-1}"
export PARKING_YOLO_ROTATE180="${PARKING_YOLO_ROTATE180:-0}"
export PARKING_YOLO_VPSS_PIXEL_FORMAT="${PARKING_YOLO_VPSS_PIXEL_FORMAT:-nv12}"
if [ -z "${PARKING_YOLO_SWAP_UV+x}" ]; then
  if [ -n "$PARKING_YOLO_VPSS_PIXEL_FORMAT" ] && [ -x "$VPSS_FMT_BIN" ]; then
    PARKING_YOLO_SWAP_UV=0
  else
    PARKING_YOLO_SWAP_UV=1
  fi
fi
export PARKING_YOLO_SWAP_UV
export PARKING_YOLO_CONFIDENCE_THRESHOLD="${PARKING_YOLO_CONFIDENCE_THRESHOLD:-0.4}"

rm -f "$STDIN_FIFO"
mkfifo "$STDIN_FIFO"
tail -f /dev/null > "$STDIN_FIFO" 2>/dev/null < /dev/null &
fifo_writer_pid=$!
echo "$fifo_writer_pid" > "$FIFO_WRITER_PID_FILE"

{
  echo "BOARD_YOLO_RUNTIME_BIN $BIN"
  echo "BOARD_YOLO_RUNTIME_CONFIDENCE_THRESHOLD $PARKING_YOLO_CONFIDENCE_THRESHOLD"
  echo "BOARD_YOLO_RUNTIME_IMAGE_STRIDE $PARKING_YOLO_IMAGE_STRIDE"
  echo "BOARD_YOLO_RUNTIME_ROTATE180 $PARKING_YOLO_ROTATE180"
  echo "BOARD_YOLO_RUNTIME_SWAP_UV $PARKING_YOLO_SWAP_UV"
  echo "BOARD_YOLO_RUNTIME_VPSS_ROTATE180 $PARKING_YOLO_VPSS_ROTATE180"
  echo "BOARD_YOLO_RUNTIME_VPSS_PIXEL_FORMAT $PARKING_YOLO_VPSS_PIXEL_FORMAT"
} > "$LOG"

nohup "$BIN" < "$STDIN_FIFO" >> "$LOG" 2>&1 &
yolo_pid=$!
echo "$yolo_pid" > "$PID_FILE"

if [ "${PARKING_YOLO_VPSS_ROTATE180:-0}" = "1" ]; then
  if [ -x "$VPSS_ROT_BIN" ]; then
    i=0
    while [ "$i" -lt "${VPSS_ROTATION_RETRY:-8}" ]; do
      if "$VPSS_ROT_BIN" 0 1 180 >> "$LOG" 2>&1; then
        echo "BOARD_YOLO_VPSS_ROTATION_SET 180" >> "$LOG"
        break
      fi
      sleep 1
      i=$((i + 1))
    done
    if [ "$i" -ge "${VPSS_ROTATION_RETRY:-8}" ]; then
      echo "BOARD_YOLO_VPSS_ROTATION_SET_FAILED 180" >> "$LOG"
    fi
  else
    echo "BOARD_YOLO_VPSS_ROTATION_SKIP missing_tool=$VPSS_ROT_BIN" >> "$LOG"
  fi
elif [ -x "$VPSS_ROT_BIN" ]; then
  "$VPSS_ROT_BIN" 0 1 0 >> "$LOG" 2>&1 || true
  echo "BOARD_YOLO_VPSS_ROTATION_SET 0" >> "$LOG"
fi

if [ -n "${PARKING_YOLO_VPSS_PIXEL_FORMAT:-}" ]; then
  if [ -x "$VPSS_FMT_BIN" ]; then
    i=0
    while [ "$i" -lt "${VPSS_PIXEL_FORMAT_RETRY:-8}" ]; do
      if "$VPSS_FMT_BIN" 0 1 "$PARKING_YOLO_VPSS_PIXEL_FORMAT" >> "$LOG" 2>&1; then
        echo "BOARD_YOLO_VPSS_PIXEL_FORMAT_SET $PARKING_YOLO_VPSS_PIXEL_FORMAT" >> "$LOG"
        break
      fi
      sleep 1
      i=$((i + 1))
    done
    if [ "$i" -ge "${VPSS_PIXEL_FORMAT_RETRY:-8}" ]; then
      echo "BOARD_YOLO_VPSS_PIXEL_FORMAT_SET_FAILED $PARKING_YOLO_VPSS_PIXEL_FORMAT" >> "$LOG"
    fi
  else
    echo "BOARD_YOLO_VPSS_PIXEL_FORMAT_SKIP missing_tool=$VPSS_FMT_BIN" >> "$LOG"
  fi
fi

echo "BOARD_YOLO_CLOSED_LOOP_MONITOR_TEE_PID $tee_pid"
echo "BOARD_YOLO_CLOSED_LOOP_MONITOR_TEE_LOG $TEE_LOG"
echo "BOARD_YOLO_CLOSED_LOOP_MONITOR_PID $yolo_pid"
echo "BOARD_YOLO_CLOSED_LOOP_MONITOR_LOG $LOG"
echo "BOARD_YOLO_DETECTION_TEE ${TEE_HOST}:${TEE_PORT}"
echo "BOARD_CONTROLLER_DETECTION ${LOCAL_CONTROLLER_HOST}:${LOCAL_CONTROLLER_PORT}"
echo "VM_MONITOR_DETECTION ${VM_HOST}:${VM_DET_PORT}"
echo "VM_MONITOR_IMAGE ${VM_HOST}:${VM_IMAGE_PORT}"
echo "BOARD_YOLO_STDIN_FIFO $STDIN_FIFO"
