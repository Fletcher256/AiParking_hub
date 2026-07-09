#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
ROS_DISTRO="${ROS_DISTRO:-humble}"
PORT="${PORT:-8765}"
ADDRESS="${ADDRESS:-0.0.0.0}"
STATE_DIR="${STATE_DIR:-/tmp/parking_sensor_link}"
PID_FILE="${STATE_DIR}/foxglove_bridge.pid"
LOG_FILE="${STATE_DIR}/foxglove_bridge.log"
TOPIC_WHITELIST="${TOPIC_WHITELIST:-['^/parking/camera/image_jpeg$','^/parking/camera/yolo_input_jpeg$','^/parking/vision/line_debug$','^/parking/parking_slot_candidates$','^/parking/yolo/person_view$','^/parking/yolo/person_detections$','^/parking/yolo/parking_view$','^/parking/yolo/parking_detections$','^/parking/slot_geometry$','^/parking/slot_geometry_state$','^/parking/target_pose$','^/parking/target_pose_state$','^/parking/planner/path$','^/parking/planner/state$','^/parking/controller/dry_run_cmd$','^/parking/controller/proposed_cmd$','^/parking/controller/v2_candidate$','^/parking/controller/state$','^/parking/perception/state$','^/parking/dtof/obstacle_view$','^/parking/dtof/depth_color$','^/parking/dtof/obstacle_blocks$','^/parking/sensors/health$','^/parking/sensors/sync_pair$','^/tf_static$','^/rosout$','^/foxglove_bridge/sysinfo$']}"
SEND_BUFFER_LIMIT="${SEND_BUFFER_LIMIT:-2000000}"

mkdir -p "$STATE_DIR"

source_ros() {
  set +u
  # shellcheck disable=SC1090
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
  if [ -f "$HOME/parking_ws/install/setup.bash" ]; then
    # shellcheck disable=SC1091
    source "$HOME/parking_ws/install/setup.bash"
  fi
  set -u
}

vm_ip_for_client() {
  if [ -n "${VM_HOST_FOR_CLIENT:-}" ]; then
    printf '%s\n' "$VM_HOST_FOR_CLIENT"
  else
    hostname -I | awk '{print $1}'
  fi
}

bridge_available() {
  source_ros
  ros2 pkg prefix foxglove_bridge >/dev/null 2>&1
}

stored_pid() {
  if [ -s "$PID_FILE" ]; then
    cat "$PID_FILE" 2>/dev/null || true
  fi
}

is_running() {
  local pid="${1:-}"
  [ -n "$pid" ] && [ -d "/proc/$pid" ]
}

kill_stale_bridge_processes() {
  local pids
  pids="$(pgrep -f '/foxglove_bridge/foxglove_bridge|ros2 launch foxglove_bridge' 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 0
  fi
  for pid in $pids; do
    if [ "$pid" = "$$" ]; then
      continue
    fi
    echo "FOXGLOVE_BRIDGE_STALE_STOP_REQUESTED $pid"
    kill "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in $pids; do
    if [ "$pid" = "$$" ]; then
      continue
    fi
    if [ -d "/proc/$pid" ]; then
      echo "FOXGLOVE_BRIDGE_STALE_TERM_REQUESTED $pid"
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
}

print_common() {
  echo "FOXGLOVE_BRIDGE_CONTROL"
  echo "HOSTNAME $(hostname)"
  echo "IP_ADDRS $(hostname -I)"
  echo "ROS_DISTRO ${ROS_DISTRO}"
  echo "ADDRESS ${ADDRESS}"
  echo "PORT ${PORT}"
  echo "WS_URL ws://$(vm_ip_for_client):${PORT}"
  echo "TOPIC_WHITELIST ${TOPIC_WHITELIST}"
  echo "SEND_BUFFER_LIMIT ${SEND_BUFFER_LIMIT}"
}

status_bridge() {
  print_common
  if bridge_available; then
    echo "FOXGLOVE_BRIDGE_INSTALLED yes"
    echo "FOXGLOVE_BRIDGE_PREFIX $(ros2 pkg prefix foxglove_bridge)"
  else
    echo "FOXGLOVE_BRIDGE_INSTALLED no"
    echo "FOXGLOVE_BRIDGE_MISSING"
    echo "RECOMMENDED_PACKAGE ros-${ROS_DISTRO}-foxglove-bridge"
    return 0
  fi

  local pid
  pid="$(stored_pid)"
  if is_running "$pid"; then
    echo "FOXGLOVE_BRIDGE_RUNNING yes"
    echo "FOXGLOVE_BRIDGE_PID $pid"
  else
    echo "FOXGLOVE_BRIDGE_RUNNING no"
  fi
  echo "FOXGLOVE_BRIDGE_LOG ${LOG_FILE}"
  tail -40 "$LOG_FILE" 2>/dev/null || true
}

start_bridge() {
  print_common
  if ! bridge_available; then
    echo "FOXGLOVE_BRIDGE_INSTALLED no"
    echo "FOXGLOVE_BRIDGE_MISSING"
    echo "RECOMMENDED_PACKAGE ros-${ROS_DISTRO}-foxglove-bridge"
    exit 5
  fi

  local old
  old="$(stored_pid)"
  if is_running "$old"; then
    echo "FOXGLOVE_BRIDGE_ALREADY_RUNNING $old"
    echo "WS_URL ws://$(vm_ip_for_client):${PORT}"
    exit 0
  fi

  kill_stale_bridge_processes

  nohup bash -lc "
set -e
source /opt/ros/${ROS_DISTRO}/setup.bash
if [ -f \"\$HOME/parking_ws/install/setup.bash\" ]; then
  source \"\$HOME/parking_ws/install/setup.bash\"
fi
exec ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=${PORT} address:=${ADDRESS} capabilities:='[connectionGraph]' topic_whitelist:=\"${TOPIC_WHITELIST}\" send_buffer_limit:=${SEND_BUFFER_LIMIT}
" > "$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  sleep 1
  echo "FOXGLOVE_BRIDGE_STARTED $pid"
  echo "WS_URL ws://$(vm_ip_for_client):${PORT}"
  echo "FOXGLOVE_BRIDGE_LOG ${LOG_FILE}"
  tail -40 "$LOG_FILE" 2>/dev/null || true
}

stop_bridge() {
  print_common
  local pid
  pid="$(stored_pid)"
  if ! is_running "$pid"; then
    kill_stale_bridge_processes
    echo "FOXGLOVE_BRIDGE_RUNNING no"
    echo "FOXGLOVE_BRIDGE_STOPPED already"
    exit 0
  fi
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill_stale_bridge_processes
  if is_running "$pid"; then
    echo "FOXGLOVE_BRIDGE_STOP_REQUESTED $pid"
  else
    echo "FOXGLOVE_BRIDGE_STOPPED $pid"
  fi
}

case "$ACTION" in
  status)
    status_bridge
    ;;
  start)
    start_bridge
    ;;
  stop)
    stop_bridge
    ;;
  *)
    echo "usage: $0 {status|start|stop}" >&2
    exit 2
    ;;
esac
