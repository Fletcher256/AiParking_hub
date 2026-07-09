#!/usr/bin/env bash
set -u

LOG=/tmp/install_foxglove_bridge_local.log
FOX=/tmp/ros-humble-foxglove-bridge_3.3.0-1jammy.20260504.100731_amd64.deb
ROSX=/var/cache/apt/archives/ros-humble-rosx-introspection_2.3.0-1jammy.20260422.093430_amd64.deb
RAPID=/var/cache/apt/archives/rapidjson-dev_1.1.0+dfsg2-7_all.deb

rm -f "$LOG"

echo "FOXGLOVE_BRIDGE_LOCAL_INSTALL_BEGIN"
echo "DATE $(date -Is)"
ls -lh "$RAPID" "$ROSX" "$FOX"

echo ebaina | sudo -S env DEBIAN_FRONTEND=noninteractive \
  apt-get -o Dpkg::Use-Pty=0 install -y \
  "$RAPID" "$ROSX" "$FOX" >"$LOG" 2>&1
rc=$?

echo "LOCAL_APT_INSTALL_RC $rc"
echo "LOCAL_APT_INSTALL_LOG_TAIL_BEGIN"
tail -120 "$LOG" 2>/dev/null || true
echo "LOCAL_APT_INSTALL_LOG_TAIL_END"

if [ "$rc" -ne 0 ]; then
  echo "FOXGLOVE_BRIDGE_LOCAL_INSTALL_END"
  exit "$rc"
fi

source /opt/ros/humble/setup.bash
if ros2 pkg prefix foxglove_bridge >/dev/null 2>&1; then
  echo "FOXGLOVE_BRIDGE_INSTALLED $(ros2 pkg prefix foxglove_bridge)"
  dpkg -s ros-humble-foxglove-bridge | sed -n '1,12p'
else
  echo "FOXGLOVE_BRIDGE_INSTALL_VERIFY_FAILED"
  echo "FOXGLOVE_BRIDGE_LOCAL_INSTALL_END"
  exit 2
fi

echo "FOXGLOVE_BRIDGE_LOCAL_INSTALL_END"
