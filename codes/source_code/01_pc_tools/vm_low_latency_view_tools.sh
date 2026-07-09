#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-check}"
BOARD_HOST="${BOARD_HOST:-172.20.10.2}"
RTSP_URL="${RTSP_URL:-rtsp://${BOARD_HOST}:554/live0}"
ROS_DISTRO="${ROS_DISTRO:-humble}"
VIEW_DIR="${VIEW_DIR:-$HOME/parking_view_tools}"
SUDO_PASSWORD="${SUDO_PASSWORD:-ebaina}"

base_packages=(
  ffmpeg
  gstreamer1.0-tools
  gstreamer1.0-libav
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-plugins-bad
  gstreamer1.0-plugins-ugly
)

ros_packages=(
  "ros-${ROS_DISTRO}-rqt-image-view"
  "ros-${ROS_DISTRO}-rviz2"
)

command_status() {
  local name="$1"
  printf "%-24s" "$name"
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
  else
    echo "missing"
  fi
}

dpkg_status() {
  local pkg="$1"
  if dpkg-query -W -f='${Status} ${Version}\n' "$pkg" 2>/dev/null | grep -q '^install ok installed'; then
    printf "%-40s installed " "$pkg"
    dpkg-query -W -f='${Version}\n' "$pkg"
  else
    printf "%-40s missing\n" "$pkg"
  fi
}

ros_pkg_status() {
  local pkg="$1"
  if bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash 2>/dev/null && ros2 pkg prefix ${pkg} >/dev/null 2>&1"; then
    printf "%-24s installed\n" "$pkg"
  else
    printf "%-24s missing\n" "$pkg"
  fi
}

check_tools() {
  echo "VM_LOW_LATENCY_VIEW_CHECK"
  echo "HOSTNAME $(hostname)"
  echo "IP_ADDRS $(hostname -I)"
  echo "BOARD_HOST ${BOARD_HOST}"
  echo "RTSP_URL ${RTSP_URL}"
  echo "DISPLAY ${DISPLAY:-}"
  echo "WAYLAND_DISPLAY ${WAYLAND_DISPLAY:-}"
  echo "ROS_DISTRO ${ROS_DISTRO}"
  echo
  echo "COMMANDS"
  for cmd in ffmpeg ffplay gst-launch-1.0 gst-inspect-1.0 rqt_image_view rviz2 ros2; do
    command_status "$cmd"
  done
  echo
  echo "APT_PACKAGES"
  for pkg in "${base_packages[@]}" "${ros_packages[@]}" "ros-${ROS_DISTRO}-foxglove-bridge"; do
    dpkg_status "$pkg"
  done
  echo
  echo "ROS_PACKAGES"
  for pkg in rqt_image_view rviz2 foxglove_bridge; do
    ros_pkg_status "$pkg"
  done
}

sudo_run() {
  printf '%s\n' "$SUDO_PASSWORD" | sudo -S "$@"
}

install_tools() {
  echo "VM_LOW_LATENCY_VIEW_INSTALL"
  local packages=("${base_packages[@]}" "${ros_packages[@]}")
  if apt-cache show "ros-${ROS_DISTRO}-foxglove-bridge" >/dev/null 2>&1; then
    packages+=("ros-${ROS_DISTRO}-foxglove-bridge")
  else
    echo "FOXGLOVE_APT_PACKAGE missing_from_apt_cache"
  fi
  sudo_run apt-get update
  sudo_run DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
}

write_text() {
  local path="$1"
  shift
  mkdir -p "$(dirname "$path")"
  cat > "$path"
  chmod +x "$path"
}

adapt_tools() {
  echo "VM_LOW_LATENCY_VIEW_ADAPT"
  mkdir -p "$VIEW_DIR"

  write_text "$VIEW_DIR/view_camera_ffplay.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RTSP_URL="\${RTSP_URL:-${RTSP_URL}}"
exec ffplay \\
  -hide_banner \\
  -loglevel warning \\
  -fflags nobuffer \\
  -flags low_delay \\
  -framedrop \\
  -rtsp_transport tcp \\
  -probesize 32 \\
  -analyzeduration 0 \\
  "\$RTSP_URL"
EOF

  write_text "$VIEW_DIR/view_camera_gst_tcp.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RTSP_URL="\${RTSP_URL:-${RTSP_URL}}"
exec gst-launch-1.0 -v \\
  rtspsrc location="\$RTSP_URL" protocols=tcp latency=0 drop-on-latency=true name=src \\
  src. ! queue leaky=downstream max-size-buffers=1 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false
EOF

  write_text "$VIEW_DIR/view_camera_gst_udp.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RTSP_URL="\${RTSP_URL:-${RTSP_URL}}"
exec gst-launch-1.0 -v \\
  rtspsrc location="\$RTSP_URL" protocols=udp latency=0 drop-on-latency=true name=src \\
  src. ! queue leaky=downstream max-size-buffers=1 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false
EOF

  write_text "$VIEW_DIR/view_ros_camera.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/${ROS_DISTRO}/setup.bash
[ -f "\$HOME/parking_ws/install/setup.bash" ] && source "\$HOME/parking_ws/install/setup.bash"
exec rqt_image_view /parking/camera/image_raw
EOF

  write_text "$VIEW_DIR/view_ros_rviz.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/${ROS_DISTRO}/setup.bash
[ -f "\$HOME/parking_ws/install/setup.bash" ] && source "\$HOME/parking_ws/install/setup.bash"
exec rviz2 -d "$VIEW_DIR/parking_dtof.rviz"
EOF

  write_text "$VIEW_DIR/start_foxglove_bridge.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/${ROS_DISTRO}/setup.bash
[ -f "\$HOME/parking_ws/install/setup.bash" ] && source "\$HOME/parking_ws/install/setup.bash"
exec ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765 address:=0.0.0.0
EOF

  cat > "$VIEW_DIR/parking_dtof.rviz" <<'EOF'
Panels:
  - Class: rviz_common/Displays
    Name: Displays
Visualization Manager:
  Class: ""
  Displays:
    - Alpha: 1
      Class: rviz_default_plugins/Image
      Enabled: true
      Name: Camera Image
      Topic:
        Value: /parking/camera/image_raw
    - Alpha: 1
      Class: rviz_default_plugins/Image
      Enabled: true
      Name: dToF Depth
      Topic:
        Value: /parking/dtof/depth
    - Alpha: 1
      Class: rviz_default_plugins/PointCloud2
      Enabled: true
      Name: dToF PointCloud
      Topic:
        Value: /parking/dtof/points
  Enabled: true
  Global Options:
    Fixed Frame: ss_ld_as01_dtof
  Name: root
EOF

  echo "VIEW_DIR $VIEW_DIR"
  find "$VIEW_DIR" -maxdepth 1 -type f -printf '%f\n' | sort
}

case "$ACTION" in
  check)
    check_tools
    ;;
  install)
    install_tools
    ;;
  adapt)
    adapt_tools
    ;;
  all)
    check_tools
    install_tools
    adapt_tools
    check_tools
    ;;
  *)
    echo "usage: $0 {check|install|adapt|all}" >&2
    exit 2
    ;;
esac
