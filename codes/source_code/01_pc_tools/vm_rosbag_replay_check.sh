#!/usr/bin/env bash
set +u
source /opt/ros/humble/setup.bash
if [ -f "$HOME/parking_ws/install/setup.bash" ]; then
  source "$HOME/parking_ws/install/setup.bash"
fi
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"

bag_dir="${1:-}"
if [ -z "$bag_dir" ]; then
  bag_dir="$(find "$HOME/parking_sensor_records/rosbag_smoke" -maxdepth 1 -type d -name 'bag_*' 2>/dev/null | sort | tail -1)"
fi

echo "ROSBAG_REPLAY_CHECK_BEGIN"
echo "BAG_DIR $bag_dir"
if [ -z "$bag_dir" ] || [ ! -d "$bag_dir" ]; then
  echo "BAG_DIR_MISSING"
  echo "ROSBAG_REPLAY_CHECK_END"
  exit 2
fi

ros2 bag info "$bag_dir" || true

tmp="/tmp/parking_rosbag_replay_check"
mkdir -p "$tmp"
rm -f "$tmp"/*.txt "$tmp"/play.log

timeout 10 ros2 topic echo --qos-reliability best_effort --once /parking/camera/image_jpeg sensor_msgs/msg/CompressedImage > "$tmp/camera.txt" 2>&1 &
camera_pid=$!
timeout 10 ros2 topic echo --qos-reliability best_effort --once /parking/dtof/depth sensor_msgs/msg/Image > "$tmp/depth.txt" 2>&1 &
depth_pid=$!
timeout 10 ros2 topic echo --once /parking/sensors/health std_msgs/msg/String > "$tmp/health.txt" 2>&1 &
health_pid=$!
timeout 10 ros2 topic echo --full-length --once /parking/parking_slot_candidates std_msgs/msg/String > "$tmp/candidates.txt" 2>&1 &
candidates_pid=$!
timeout 10 ros2 topic echo --full-length --once /parking/perception/state std_msgs/msg/String > "$tmp/state.txt" 2>&1 &
state_pid=$!
timeout 10 ros2 topic echo --qos-reliability best_effort --once /parking/vision/line_debug sensor_msgs/msg/CompressedImage > "$tmp/vision_debug.txt" 2>&1 &
vision_debug_pid=$!

sleep 1
timeout 8 ros2 bag play --loop "$bag_dir" > "$tmp/play.log" 2>&1
play_rc=$?

wait "$camera_pid"; camera_rc=$?
wait "$depth_pid"; depth_rc=$?
wait "$health_pid"; health_rc=$?
wait "$candidates_pid"; candidates_rc=$?
wait "$state_pid"; state_rc=$?
wait "$vision_debug_pid"; vision_debug_rc=$?

echo "BAG_PLAY_RC $play_rc"
echo "REPLAY_CAMERA_RC $camera_rc"
echo "REPLAY_DEPTH_RC $depth_rc"
echo "REPLAY_HEALTH_RC $health_rc"
echo "REPLAY_CANDIDATES_RC $candidates_rc"
echo "REPLAY_STATE_RC $state_rc"
echo "REPLAY_VISION_DEBUG_RC $vision_debug_rc"
echo "REPLAY_CAMERA_BYTES $(wc -c < "$tmp/camera.txt")"
echo "REPLAY_DEPTH_BYTES $(wc -c < "$tmp/depth.txt")"
echo "REPLAY_HEALTH_BYTES $(wc -c < "$tmp/health.txt")"
echo "REPLAY_CANDIDATES_BYTES $(wc -c < "$tmp/candidates.txt")"
echo "REPLAY_STATE_BYTES $(wc -c < "$tmp/state.txt")"
echo "REPLAY_VISION_DEBUG_BYTES $(wc -c < "$tmp/vision_debug.txt")"
echo "BAG_PLAY_LOG_TAIL_BEGIN"
tail -40 "$tmp/play.log" || true
echo "BAG_PLAY_LOG_TAIL_END"

if [ "$camera_rc" -eq 0 ] && [ "$depth_rc" -eq 0 ] && [ "$health_rc" -eq 0 ] \
  && [ "$candidates_rc" -eq 0 ] && [ "$state_rc" -eq 0 ] && [ "$vision_debug_rc" -eq 0 ]; then
  echo "ROSBAG_REPLAY_CHECK PASS"
  echo "ROSBAG_REPLAY_CHECK_END"
  exit 0
fi
echo "ROSBAG_REPLAY_CHECK FAIL"
echo "ROSBAG_REPLAY_CHECK_END"
exit 1
