#!/usr/bin/env bash
set -euo pipefail
echo "VM_APT_PROBE"
date
echo "PROCESSES"
ps -eo pid,ppid,stat,etime,cmd | grep -E 'apt|dpkg|sudo|vm_low_latency' | grep -v grep || true
echo "LOCKS"
fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock /var/cache/apt/archives/lock 2>/dev/null || true
echo "DPKG_INTERRUPTED"
sudo -n dpkg --audit 2>/dev/null || true
echo "APT_TERM_TAIL"
tail -80 /var/log/apt/term.log 2>/dev/null || true
echo "VIEW_TOOL_CHECK"
bash "$HOME/vm_low_latency_view_tools.sh" check || true
