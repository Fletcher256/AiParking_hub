#!/usr/bin/env bash
# Restart the VM foxglove_bridge with a whitelist that also exposes the
# standalone single-dToF topics (/dtof/points, /dtof/depth, /dtof/info),
# while keeping the existing /parking/* perception topics for later.
ROS_DISTRO="${ROS_DISTRO:-humble}"
PORT="${PORT:-8765}"
ADDRESS="0.0.0.0"
STATE_DIR="/tmp/parking_sensor_link"
LOG_FILE="${STATE_DIR}/foxglove_bridge.log"
PID_FILE="${STATE_DIR}/foxglove_bridge.pid"
mkdir -p "$STATE_DIR"

WL="['^/dtof/points\$','^/dtof/depth\$','^/dtof/depth_color\$','^/dtof/info\$','^/parking/camera/image_jpeg\$','^/parking/vision/line_debug\$','^/parking/parking_slot_candidates\$','^/parking/yolo/person_view\$','^/parking/yolo/person_detections\$','^/parking/perception/state\$','^/parking/dtof/obstacle_view\$','^/parking/dtof/depth_color\$','^/parking/dtof/obstacle_blocks\$','^/parking/sensors/health\$','^/parking/sensors/sync_pair\$','^/tf_static\$','^/rosout\$','^/foxglove_bridge/sysinfo\$']"

echo "Stopping any running foxglove_bridge ..."
for pid in $(pgrep -f '/foxglove_bridge/foxglove_bridge|ros2 launch foxglove_bridge' 2>/dev/null || true); do
  echo "  kill $pid"
  kill "$pid" 2>/dev/null || true
done
sleep 2
for pid in $(pgrep -f '/foxglove_bridge/foxglove_bridge|ros2 launch foxglove_bridge' 2>/dev/null || true); do
  kill -9 "$pid" 2>/dev/null || true
done
sleep 1

source "/opt/ros/${ROS_DISTRO}/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

nohup bash -lc "
source /opt/ros/${ROS_DISTRO}/setup.bash
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
exec ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=${PORT} address:=${ADDRESS} capabilities:='[connectionGraph]' topic_whitelist:=\"${WL}\" send_buffer_limit:=2000000
" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 4
echo "FOXGLOVE_RESTARTED pid=$(cat $PID_FILE)"
echo "WS_URL ws://$(hostname -I | awk '{print $1}'):${PORT}"
echo "IP_ADDRS $(hostname -I)"
echo "WHITELIST includes /dtof/points /dtof/depth /dtof/info"
echo "---LOG_TAIL---"
tail -25 "$LOG_FILE" 2>/dev/null || true
