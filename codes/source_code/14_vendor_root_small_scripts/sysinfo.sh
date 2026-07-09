#!/bin/sh
echo "=== Storage ==="
df -h
echo "=== RAM ==="
free -h
echo "=== CPU ==="
grep -E 'processor|Hardware|model name|CPU' /proc/cpuinfo | head -8
echo "=== Python ==="
python3 --version 2>&1 || python --version 2>&1 || echo "no python"
echo "=== pip ==="
pip3 --version 2>&1 || pip --version 2>&1 || echo "no pip"
echo "=== cmake/gcc ==="
cmake --version 2>&1 | head -1 || echo "no cmake"
gcc --version 2>&1 | head -1 || echo "no gcc"
echo "=== Package manager ==="
which dnf yum rpm apt 2>/dev/null
