#!/usr/bin/env bash
set -u

LOG=/tmp/install_foxglove_bridge.log
rm -f "$LOG"

echo "FOXGLOVE_BRIDGE_INSTALL_BEGIN"
echo "HOSTNAME $(hostname)"
echo "DATE $(date -Is)"

if ros2 pkg prefix foxglove_bridge >/dev/null 2>&1; then
  echo "FOXGLOVE_BRIDGE_ALREADY_INSTALLED $(ros2 pkg prefix foxglove_bridge)"
  exit 0
fi

echo ebaina | sudo -S env DEBIAN_FRONTEND=noninteractive \
  apt-get -o Dpkg::Use-Pty=0 -o Acquire::ForceIPv4=true \
  install -y ros-humble-foxglove-bridge >"$LOG" 2>&1
rc=$?

echo "APT_INSTALL_RC $rc"
echo "APT_INSTALL_LOG_TAIL_BEGIN"
tail -120 "$LOG" 2>/dev/null || true
echo "APT_INSTALL_LOG_TAIL_END"

if [ "$rc" -ne 0 ]; then
  echo "FOXGLOVE_BRIDGE_INSTALL_END"
  exit "$rc"
fi

source /opt/ros/humble/setup.bash
if ros2 pkg prefix foxglove_bridge >/dev/null 2>&1; then
  echo "FOXGLOVE_BRIDGE_INSTALLED $(ros2 pkg prefix foxglove_bridge)"
else
  echo "FOXGLOVE_BRIDGE_INSTALL_VERIFY_FAILED"
  echo "FOXGLOVE_BRIDGE_INSTALL_END"
  exit 2
fi

echo "FOXGLOVE_BRIDGE_INSTALL_END"
