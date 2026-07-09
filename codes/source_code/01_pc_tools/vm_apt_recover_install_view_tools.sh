#!/usr/bin/env bash
set -euo pipefail
SUDO_PASSWORD="${SUDO_PASSWORD:-ebaina}"
ROS_DISTRO="${ROS_DISTRO:-humble}"

sudo_run() {
  printf '%s\n' "$SUDO_PASSWORD" | sudo -S "$@"
}

echo "VM_APT_RECOVER"
echo "STOP_STALE_APT"
for pid in $(ps -eo pid,cmd | awk '/apt-get install -y ffmpeg|vm_low_latency_view_tools.sh install|\/usr\/lib\/apt\/methods\/http/ && !/awk/ {print $1}'); do
  echo "terminate $pid"
  sudo_run kill -TERM "$pid" 2>/dev/null || true
done
sleep 3
for pid in $(ps -eo pid,cmd | awk '/apt-get install -y ffmpeg|vm_low_latency_view_tools.sh install|\/usr\/lib\/apt\/methods\/http/ && !/awk/ {print $1}'); do
  echo "kill $pid"
  sudo_run kill -KILL "$pid" 2>/dev/null || true
done

echo "REPAIR_DPKG"
sudo_run dpkg --configure -a

apt_common=(
  -o Acquire::ForceIPv4=true
  -o Acquire::Retries=2
  -o Dpkg::Options::=--force-confdef
  -o Dpkg::Options::=--force-confold
)

echo "APT_UPDATE"
sudo_run apt-get "${apt_common[@]}" update

echo "INSTALL_BASE_VIEW_TOOLS"
sudo_run DEBIAN_FRONTEND=noninteractive apt-get "${apt_common[@]}" install -y --no-install-recommends \
  ffmpeg \
  gstreamer1.0-libav \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly

echo "INSTALL_FOXGLOVE_IF_AVAILABLE"
if apt-cache show "ros-${ROS_DISTRO}-foxglove-bridge" >/dev/null 2>&1; then
  sudo_run DEBIAN_FRONTEND=noninteractive apt-get "${apt_common[@]}" install -y --no-install-recommends "ros-${ROS_DISTRO}-foxglove-bridge"
else
  echo "FOXGLOVE_APT_PACKAGE_NOT_AVAILABLE"
fi

echo "FINAL_CHECK"
bash "$HOME/vm_low_latency_view_tools.sh" check
