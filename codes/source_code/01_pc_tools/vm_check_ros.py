#!/usr/bin/env python3
import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.137.100", username="ebaina", password="ebaina", timeout=15)

script = """
source /opt/ros/humble/setup.bash
python3 - <<'PYEOF'
try:
    import rclpy
    print("rclpy:", rclpy.__file__)
except Exception as e:
    print("rclpy FAIL:", e)
try:
    import sensor_msgs
    print("sensor_msgs:", sensor_msgs.__file__)
except Exception as e:
    print("sensor_msgs FAIL:", e)
try:
    import numpy as np
    print("numpy:", np.__version__)
except Exception as e:
    print("numpy FAIL:", e)
PYEOF
which colcon 2>/dev/null || echo "colcon: not found"
pip3 list 2>/dev/null | grep -i colcon || echo "colcon pip: not found"
ls ~/parking_ws/src/parking_bridge/
"""

_, out, err = c.exec_command(f"bash -s", timeout=60)
out.channel.sendall(script.encode())
out.channel.shutdown_write()
o = out.read().decode("utf-8", "replace")
e = err.read().decode("utf-8", "replace")
if o: print(o)
if e: print("STDERR:", e[:500], file=sys.stderr)
c.close()
