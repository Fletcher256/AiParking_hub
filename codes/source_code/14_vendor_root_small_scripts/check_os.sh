#!/bin/sh
echo "=== OS info ==="
cat /etc/openEuler-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null || cat /etc/issue 2>/dev/null | head -3
uname -a
echo "=== rpm db ==="
rpm -qa 2>/dev/null | head -20 || echo "rpm db empty or unavailable"
echo "=== lib check ==="
ls /lib64/libc-*.so 2>/dev/null || ls /lib/libc-*.so 2>/dev/null
echo "=== network repos ==="
ls /etc/yum.repos.d/ 2>/dev/null || ls /etc/dnf/dnf.conf 2>/dev/null || echo "no repo config"
