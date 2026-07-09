#!/usr/bin/env bash
set -euo pipefail
SUDO_PASSWORD="${SUDO_PASSWORD:-ebaina}"

sudo_run() {
  printf '%s\n' "$SUDO_PASSWORD" | sudo -S "$@"
}

echo "VM_STOP_VIEW_INSTALL"
date
echo "MATCHING_PROCESSES_BEFORE"
ps -eo pid,ppid,stat,etime,cmd | grep -E 'apt|dpkg|sudo|vm_low_latency|vm_apt_recover' | grep -v grep || true

for pid in $(ps -eo pid,cmd | awk '/apt-get|\/usr\/lib\/apt\/methods\/http|vm_low_latency_view_tools.sh install|vm_apt_recover_install_view_tools.sh/ && !/awk/ {print $1}'); do
  echo "TERM $pid"
  sudo_run kill -TERM "$pid" 2>/dev/null || true
done
sleep 3

for pid in $(ps -eo pid,cmd | awk '/apt-get|\/usr\/lib\/apt\/methods\/http|vm_low_latency_view_tools.sh install|vm_apt_recover_install_view_tools.sh/ && !/awk/ {print $1}'); do
  echo "KILL $pid"
  sudo_run kill -KILL "$pid" 2>/dev/null || true
done

echo "MATCHING_PROCESSES_AFTER"
ps -eo pid,ppid,stat,etime,cmd | grep -E 'apt|dpkg|sudo|vm_low_latency|vm_apt_recover' | grep -v grep || true

echo "DPKG_AUDIT"
sudo -n dpkg --audit 2>/dev/null || true
