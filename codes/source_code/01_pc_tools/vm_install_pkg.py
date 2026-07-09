#!/usr/bin/env python3
"""Install the parking_bridge package on VM and create a run script."""
import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.137.100", username="ebaina", password="ebaina", timeout=15)

script = r"""
set -e
echo "=== pip install -e ==="
cd ~/parking_ws/src/parking_bridge
pip3 install -e . --quiet 2>&1 | tail -5

echo "=== creating run script ==="
cat > ~/run_dtof_bridge.sh << 'EOF'
#!/bin/bash
source /opt/ros/humble/setup.bash
export PYTHONPATH=/home/ebaina/parking_ws/src/parking_bridge:$PYTHONPATH
exec python3 /home/ebaina/parking_ws/src/parking_bridge/parking_bridge/dtof_bridge.py "$@"
EOF
chmod +x ~/run_dtof_bridge.sh

echo "=== verifying import ==="
source /opt/ros/humble/setup.bash
python3 -c "
import sys
sys.path.insert(0, '/home/ebaina/parking_ws/src/parking_bridge')
from parking_bridge import dtof_bridge
print('import OK:', dtof_bridge.__file__)
"
echo "Done. Run with: ~/run_dtof_bridge.sh"
"""

_, out, err = c.exec_command("bash -s", timeout=60)
out.channel.sendall(script.encode())
out.channel.shutdown_write()
o = out.read().decode("utf-8", "replace")
e = err.read().decode("utf-8", "replace")
if o: print(o)
if e: print("STDERR:", e[:500], file=sys.stderr)
rc = out.channel.recv_exit_status()
print(f"[exit={rc}]")
c.close()
