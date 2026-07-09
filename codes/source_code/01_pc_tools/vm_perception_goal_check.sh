#!/usr/bin/env bash

RECORD_FILE="${RECORD_FILE:-/tmp/parking_sensor_link/parking_record_dir}"
ROS_WS="${ROS_WS:-$HOME/parking_ws/install/setup.bash}"
ROSBAG_SMOKE="${ROSBAG_SMOKE:-0}"

source /opt/ros/humble/setup.bash
if [ -f "$ROS_WS" ]; then
  source "$ROS_WS"
fi
set -u

echo "PERCEPTION_GOAL_CHECK_BEGIN"
echo "HOSTNAME $(hostname)"
echo "HOST_IPS $(hostname -I)"

echo "TOOLS_BEGIN"
for cmd in ros2 ffplay gst-launch-1.0 rviz2 rqt_image_view; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "TOOL $cmd $(command -v "$cmd")"
  else
    echo "TOOL_MISSING $cmd"
  fi
done
for pkg in foxglove_bridge rviz2 rqt_image_view rosbag2_transport; do
  if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
    echo "ROS_PKG $pkg $(ros2 pkg prefix "$pkg")"
  else
    echo "ROS_PKG_MISSING $pkg"
  fi
done
echo "TOOLS_END"

echo "TOPICS_BEGIN"
ros2 topic list
echo "TOPICS_END"

echo "TOPIC_TYPES_BEGIN"
for topic in \
  /parking/camera/image_raw \
  /parking/camera/image_jpeg \
  /parking/dtof/raw_packet \
  /parking/dtof/depth \
  /parking/dtof/confidence \
  /parking/dtof/points \
  /parking/dtof/depth_color \
  /parking/dtof/obstacle_view \
  /parking/dtof/obstacle_blocks \
  /parking/vision/line_debug \
  /parking/parking_slot_candidates \
  /parking/yolo/person_view \
  /parking/yolo/person_detections \
  /parking/perception/state \
  /parking/sensors/health \
  /parking/sensors/sync_pair; do
  ros2 topic type "$topic" 2>/dev/null | sed "s|^|TOPIC_TYPE $topic |" || true
done
echo "TOPIC_TYPES_END"

echo "DTOF_HZ_BEGIN"
timeout 6 ros2 topic hz /parking/dtof/depth || true
echo "DTOF_HZ_END"

echo "DTOF_OBSTACLE_ONCE_BEGIN"
timeout 4 ros2 topic echo /parking/dtof/obstacle_blocks --once || true
echo "DTOF_OBSTACLE_ONCE_END"

echo "HEALTH_ONCE_BEGIN"
timeout 4 ros2 topic echo /parking/sensors/health --once || true
echo "HEALTH_ONCE_END"

echo "VISION_CANDIDATES_ONCE_BEGIN"
timeout 4 ros2 topic echo --full-length /parking/parking_slot_candidates std_msgs/msg/String --once || true
echo "VISION_CANDIDATES_ONCE_END"

echo "YOLO_PERSON_DETECTIONS_ONCE_BEGIN"
timeout 6 ros2 topic echo --full-length /parking/yolo/person_detections std_msgs/msg/String --once || true
echo "YOLO_PERSON_DETECTIONS_ONCE_END"

echo "PERCEPTION_STATE_ONCE_BEGIN"
timeout 4 ros2 topic echo --full-length /parking/perception/state std_msgs/msg/String --once || true
echo "PERCEPTION_STATE_ONCE_END"

echo "RECORD_DIR_BEGIN"
record_root=""
if [ -s "$RECORD_FILE" ]; then
  record_root="$(cat "$RECORD_FILE" 2>/dev/null || true)"
fi
echo "RECORD_ROOT $record_root"
if [ -n "$record_root" ] && [ -d "$record_root" ]; then
  python3 - "$record_root" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
sessions = sorted(root.glob("session_*"), key=lambda p: p.stat().st_mtime)
print("SENSOR_SESSION_COUNT", len(sessions))
if not sessions:
    raise SystemExit(0)
s = sessions[-1]
print("SENSOR_SESSION", s)
print("CAMERA_FRAMES", len(list((s / "camera_frames").glob("*.jpg"))))
def count_lines(name):
    p = s / name
    return len(p.read_text(errors="replace").splitlines()) if p.exists() else 0
print("DTOF_METADATA_LINES", count_lines("dtof_metadata.jsonl"))
print("SYNC_LINES", count_lines("sync_pairs.jsonl"))
print("PREVIEW_FILES", len(list((s / "preview").glob("*.jpg"))))
rows = []
p = s / "dtof_metadata.jsonl"
if p.exists():
    for line in p.read_text(errors="replace").splitlines()[-20:]:
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
print("DTOF_LAST20_ROWS", len(rows))
if rows:
    last = rows[-1]
    for key in [
        "packet_size",
        "expected_packet_size",
        "width",
        "height",
        "pixel_number",
        "expected_shape",
        "frame_rate",
        "valid_pixels",
        "depth_valid_pixels",
        "depth_unique_count",
        "depth_nonzero_pixels",
        "depth_gt20mm_pixels",
        "confidence_nonzero_pixels",
        "depth_flat",
        "depth_ok",
        "depth_min_mm",
        "depth_max_mm",
        "depth_mean_mm",
    ]:
        print("DTOF_LAST", key, last.get(key))
    packet_ok = all(
        row.get("packet_size") == row.get("expected_packet_size") == 4873
        and row.get("width") == 40
        and row.get("height") == 30
        and row.get("pixel_number") == 1200
        and row.get("expected_shape")
        for row in rows
    )
    print("DTOF_LAST20_PACKET_SHAPE_OK", packet_ok)
hp = s / "health.jsonl"
health_rows = []
if hp.exists():
    for line in hp.read_text(errors="replace").splitlines()[-60:]:
        if line.strip():
            try:
                health_rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
print("HEALTH_RECENT_ROWS", len(health_rows))
if health_rows:
    last = health_rows[-1]
    print("HEALTH_LAST_CAMERA_OK", last.get("camera", {}).get("ok"))
    print("HEALTH_LAST_DTOF_TRANSPORT_OK", last.get("dtof", {}).get("transport_ok"))
    print("HEALTH_LAST_DTOF_DEPTH_OK", last.get("dtof", {}).get("depth_ok"))
    print("HEALTH_LAST_DTOF_OK", last.get("dtof", {}).get("ok"))
    print("HEALTH_RECENT_ANY_TRANSPORT_AND_CAMERA_OK", any(row.get("camera", {}).get("ok") and row.get("dtof", {}).get("transport_ok") for row in health_rows))
    print("HEALTH_RECENT_ANY_DEPTH_AND_CAMERA_OK", any(row.get("camera", {}).get("ok") and row.get("dtof", {}).get("depth_ok") for row in health_rows))
    print("HEALTH_RECENT_ANY_BOTH_OK", any(row.get("camera", {}).get("ok") and row.get("dtof", {}).get("ok") for row in health_rows))
PY
fi
echo "RECORD_DIR_END"

if [ "$ROSBAG_SMOKE" = "1" ]; then
  echo "ROSBAG_SMOKE_BEGIN"
  bag_root="$HOME/parking_sensor_records/rosbag_smoke"
  mkdir -p "$bag_root"
  bag_dir="$bag_root/bag_$(date +%Y%m%d_%H%M%S)"
  set +e
  timeout 8 ros2 bag record -s sqlite3 -o "$bag_dir" \
    /parking/camera/image_jpeg \
    /parking/dtof/depth \
    /parking/dtof/depth_color \
    /parking/dtof/obstacle_view \
    /parking/dtof/obstacle_blocks \
    /parking/dtof/points \
    /parking/vision/line_debug \
    /parking/parking_slot_candidates \
    /parking/yolo/person_view \
    /parking/yolo/person_detections \
    /parking/perception/state \
    /parking/sensors/health \
    /parking/sensors/sync_pair
  record_rc=$?
  set -e
  echo "ROSBAG_RECORD_RC $record_rc"
  echo "ROSBAG_DIR $bag_dir"
  ros2 bag info "$bag_dir" || true
  echo "ROSBAG_SMOKE_END"
fi

echo "PERCEPTION_GOAL_CHECK_END"
