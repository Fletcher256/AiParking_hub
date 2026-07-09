#!/usr/bin/env bash
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-humble}"
STATE_DIR="${STATE_DIR:-/tmp/parking_sensor_link}"
BRIDGE_LOG="${STATE_DIR}/foxglove_bridge.log"
BRIDGE_PID_FILE="${STATE_DIR}/foxglove_bridge.pid"
TMP_DIR="${TMPDIR:-/tmp}/parking_foxglove_audit"

mkdir -p "$TMP_DIR"

set +u
# shellcheck disable=SC1090
source "/opt/ros/${ROS_DISTRO}/setup.bash"
if [ -f "$HOME/parking_ws/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  source "$HOME/parking_ws/install/setup.bash"
fi
set -u

pass=0
fail=0

check() {
  local name="$1"
  local status="$2"
  local detail="$3"
  if [ "$status" = "PASS" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
  fi
  printf '%s %s - %s\n' "$status" "$name" "$detail"
}

echo "FOXGLOVE_LOW_BANDWIDTH_AUDIT_BEGIN"
echo "HOSTNAME $(hostname)"
echo "IP_ADDRS $(hostname -I)"
echo "ROS_DISTRO ${ROS_DISTRO}"

topics="$TMP_DIR/topics.txt"
ros2 topic list | sort > "$topics"
echo "TOPICS_BEGIN"
cat "$topics"
echo "TOPICS_END"

for topic in \
  /parking/camera/image_jpeg \
  /parking/vision/line_debug \
  /parking/parking_slot_candidates \
  /parking/yolo/person_view \
  /parking/yolo/person_detections \
  /parking/perception/state \
  /parking/dtof/obstacle_view \
  /parking/dtof/depth_color \
  /parking/dtof/obstacle_blocks \
  /parking/sensors/health \
  /parking/sensors/sync_pair; do
  if grep -Fxq "$topic" "$topics"; then
    check "topic_present:${topic}" PASS "topic is available"
  else
    check "topic_present:${topic}" FAIL "topic is missing"
  fi
done

if grep -Fxq "/parking/dtof/points" "$topics"; then
  check "points_topic_graph_present" PASS "publisher exists, but message audit below must prove it is idle"
else
  check "points_topic_graph_present" PASS "topic absent from graph"
fi

echo_once() {
  local topic="$1"
  local type_name="$2"
  local outfile="$3"
  set +e
  timeout 8 ros2 topic echo --full-length --qos-reliability best_effort --once "$topic" "$type_name" > "$outfile" 2>&1
  local rc=$?
  set -e
  printf '%s' "$rc"
}

camera_echo="$TMP_DIR/camera_image_jpeg.txt"
camera_rc="$(echo_once /parking/camera/image_jpeg sensor_msgs/msg/CompressedImage "$camera_echo")"
if [ "$camera_rc" = "0" ] && grep -q "format: jpeg" "$camera_echo"; then
  check "camera_image_jpeg_echo" PASS "received jpeg CompressedImage"
else
  check "camera_image_jpeg_echo" FAIL "rc=${camera_rc}"
fi

vision_echo="$TMP_DIR/vision_line_debug.txt"
vision_rc="$(echo_once /parking/vision/line_debug sensor_msgs/msg/CompressedImage "$vision_echo")"
if [ "$vision_rc" = "0" ] && grep -q "format: jpeg" "$vision_echo"; then
  check "vision_line_debug_echo" PASS "received jpeg CompressedImage"
else
  check "vision_line_debug_echo" FAIL "rc=${vision_rc}"
fi

candidates_echo="$TMP_DIR/parking_slot_candidates.txt"
candidates_rc="$(echo_once /parking/parking_slot_candidates std_msgs/msg/String "$candidates_echo")"
if [ "$candidates_rc" = "0" ] && grep -Eq "pixel_only_uncalibrated|pixel_only_un|line_count|processed_image_size|schema_version" "$candidates_echo"; then
  check "parking_slot_candidates_echo" PASS "received pixel-only candidate JSON"
else
  check "parking_slot_candidates_echo" FAIL "rc=${candidates_rc}"
fi

yolo_view_echo="$TMP_DIR/yolo_person_view.txt"
yolo_view_rc="$(echo_once /parking/yolo/person_view sensor_msgs/msg/CompressedImage "$yolo_view_echo")"
if [ "$yolo_view_rc" = "0" ] && grep -q "format: jpeg" "$yolo_view_echo"; then
  check "yolo_person_view_echo" PASS "received jpeg CompressedImage"
else
  check "yolo_person_view_echo" FAIL "rc=${yolo_view_rc}"
fi

yolo_det_echo="$TMP_DIR/yolo_person_detections.txt"
yolo_det_rc="$(echo_once /parking/yolo/person_detections std_msgs/msg/String "$yolo_det_echo")"
if [ "$yolo_det_rc" = "0" ] && grep -Eq "person_count|class_filter|motion_enabled|actuator_control_allowed" "$yolo_det_echo"; then
  check "yolo_person_detections_echo" PASS "received person detector JSON"
else
  check "yolo_person_detections_echo" FAIL "rc=${yolo_det_rc}"
fi

state_echo="$TMP_DIR/perception_state.txt"
state_rc="$(echo_once /parking/perception/state std_msgs/msg/String "$state_echo")"
if [ "$state_rc" = "0" ] && grep -Eq "perception_only|motion_enabled|actuator_control_allowed" "$state_echo"; then
  check "perception_state_echo" PASS "received perception-only state JSON"
else
  check "perception_state_echo" FAIL "rc=${state_rc}"
fi

obstacle_echo="$TMP_DIR/obstacle_view.txt"
obstacle_rc="$(echo_once /parking/dtof/obstacle_view sensor_msgs/msg/CompressedImage "$obstacle_echo")"
if [ "$obstacle_rc" = "0" ] && grep -q "format: jpeg" "$obstacle_echo"; then
  check "dtof_obstacle_view_echo" PASS "received jpeg CompressedImage"
else
  check "dtof_obstacle_view_echo" FAIL "rc=${obstacle_rc}"
fi

depth_color_echo="$TMP_DIR/depth_color.txt"
depth_color_rc="$(echo_once /parking/dtof/depth_color sensor_msgs/msg/CompressedImage "$depth_color_echo")"
if [ "$depth_color_rc" = "0" ] && grep -q "format: jpeg" "$depth_color_echo"; then
  check "dtof_depth_color_echo" PASS "received jpeg CompressedImage"
else
  check "dtof_depth_color_echo" FAIL "rc=${depth_color_rc}"
fi

blocks_echo="$TMP_DIR/obstacle_blocks.txt"
blocks_rc="$(echo_once /parking/dtof/obstacle_blocks std_msgs/msg/String "$blocks_echo")"
if [ "$blocks_rc" = "0" ] && grep -Eq "valid_pixels|nearest_zone|state" "$blocks_echo"; then
  check "dtof_obstacle_blocks_echo" PASS "received obstacle JSON"
else
  check "dtof_obstacle_blocks_echo" FAIL "rc=${blocks_rc}"
fi

points_echo="$TMP_DIR/points.txt"
points_rc="$(echo_once /parking/dtof/points sensor_msgs/msg/PointCloud2 "$points_echo")"
if [ "$points_rc" != "0" ] && ! grep -q "^header:" "$points_echo"; then
  check "dtof_points_no_messages" PASS "no PointCloud2 message observed in 8s, rc=${points_rc}"
else
  check "dtof_points_no_messages" FAIL "PointCloud2 message observed or echo succeeded, rc=${points_rc}"
fi

if [ -s "$BRIDGE_PID_FILE" ] && [ -d "/proc/$(cat "$BRIDGE_PID_FILE")" ]; then
  bridge_pid="$(cat "$BRIDGE_PID_FILE")"
  check "foxglove_bridge_running" PASS "pid=${bridge_pid}"
  ps -p "$bridge_pid" -o args= | sed 's/^/FOXGLOVE_PROCESS /' || true
else
  check "foxglove_bridge_running" FAIL "pid file missing or process not running"
fi

if [ -f "$BRIDGE_LOG" ]; then
  if grep -E 'Advertising new channel .*(/parking/dtof/points|/parking/dtof/raw_packet|/parking/camera/image_raw)' "$BRIDGE_LOG" >/dev/null 2>&1; then
    check "foxglove_no_high_bandwidth_channels" FAIL "bridge advertised a blocked high-bandwidth topic"
  else
    check "foxglove_no_high_bandwidth_channels" PASS "no points/raw_packet/image_raw advertisements in bridge log"
  fi
  echo "FOXGLOVE_RECENT_CHANNELS_BEGIN"
  grep -E 'Advertising new channel|Removing channel' "$BRIDGE_LOG" | tail -30 || true
  echo "FOXGLOVE_RECENT_CHANNELS_END"
else
  check "foxglove_bridge_log_present" FAIL "$BRIDGE_LOG missing"
fi

echo "FOXGLOVE_LOW_BANDWIDTH_AUDIT_PASS_COUNT ${pass}"
echo "FOXGLOVE_LOW_BANDWIDTH_AUDIT_FAIL_COUNT ${fail}"
if [ "$fail" -eq 0 ]; then
  echo "FOXGLOVE_LOW_BANDWIDTH_AUDIT PASS"
  exit 0
fi
echo "FOXGLOVE_LOW_BANDWIDTH_AUDIT FAIL"
exit 1
