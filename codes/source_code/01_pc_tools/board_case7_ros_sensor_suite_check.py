#!/usr/bin/env python3
"""Run board sample_dtof_rtsp case7 and verify the ROS2 VM sensor suite."""

from __future__ import annotations

import argparse
import subprocess
import time


BOARD_COMMAND = """cd /opt/ko
./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
cd /opt/sample/official_dtof
( sleep 35; echo ) | timeout 70 ./sample_dtof_rtsp 7 192.168.137.100
rc=$?
echo CASE7_RC=$rc"""


def vm_command(record_dir: str, duration: int) -> str:
    return f"""bash -lc '
set -e
source /opt/ros/humble/setup.bash
source ~/parking_ws/install/setup.bash
export RECORD_DIR={record_dir}
mkdir -p "$RECORD_DIR"
rm -f /tmp/parking_sensor_case7.log
(timeout {duration} ros2 launch parking_bridge parking.launch.py \\
  record_dir:="$RECORD_DIR" \\
  camera_scale:=0.5 \\
  sync_slop_ms:=700.0 \\
  visualize_window:=false \\
  enable_recording:=true > /tmp/parking_sensor_case7.log 2>&1 || true)
echo ROS_SENSOR_LOG_BEGIN
tail -120 /tmp/parking_sensor_case7.log || true
echo ROS_SENSOR_LOG_END
python3 - <<\"PY\"
from pathlib import Path
import json
import os
root = Path(os.environ["RECORD_DIR"])
sessions = sorted(root.glob(\"session_*\"))
print(\"ROS_RECORD_ROOT\", root)
print(\"ROS_SESSIONS\", len(sessions))
if not sessions:
    raise SystemExit(1)
s = sessions[-1]
print(\"ROS_SESSION\", s)
def count_lines(name):
    p = s / name
    return len(p.read_text(errors=\"replace\").splitlines()) if p.exists() else -1
camera_frames = list((s / \"camera_frames\").glob(\"*.jpg\"))
dtof_depth = list((s / \"dtof_depth_npy\").glob(\"*.npy\"))
preview = list((s / \"preview\").glob(\"*.jpg\"))
print(\"CAMERA_FRAMES\", len(camera_frames))
print(\"DTOF_BIN_BYTES\", (s / \"dtof_packets.bin\").stat().st_size if (s / \"dtof_packets.bin\").exists() else -1)
print(\"DTOF_METADATA_LINES\", count_lines(\"dtof_metadata.jsonl\"))
print(\"DTOF_INDEX_LINES\", count_lines(\"dtof_packets.jsonl\"))
print(\"HEALTH_LINES\", count_lines(\"health.jsonl\"))
print(\"SYNC_LINES\", count_lines(\"sync_pairs.jsonl\"))
print(\"DTOF_DEPTH_NPY\", len(dtof_depth))
print(\"PREVIEW_FILES\", len(preview))
health = s / \"health.jsonl\"
health_rows = []
if health.exists():
    for line in health.read_text(errors=\"replace\").splitlines():
        if line.strip():
            health_rows.append(json.loads(line))
last = health_rows[-1] if health_rows else None
if last:
    print(\"LAST_CAMERA_OK\", last[\"camera\"][\"ok\"])
    print(\"LAST_CAMERA_FRAMES\", last[\"camera\"][\"frames\"])
    print(\"LAST_DTOF_OK\", last[\"dtof\"][\"ok\"])
    print(\"LAST_DTOF_PACKETS\", last[\"dtof\"][\"packets\"])
any_camera_ok = any(row[\"camera\"][\"ok\"] for row in health_rows)
any_dtof_ok = any(row[\"dtof\"][\"ok\"] for row in health_rows)
any_both_ok = any(row[\"camera\"][\"ok\"] and row[\"dtof\"][\"ok\"] for row in health_rows)
print(\"ANY_CAMERA_OK\", any_camera_ok)
print(\"ANY_DTOF_OK\", any_dtof_ok)
print(\"ANY_BOTH_OK\", any_both_ok)
record_ok = (
    len(camera_frames) > 0 and
    count_lines(\"dtof_metadata.jsonl\") > 0 and
    count_lines(\"dtof_packets.jsonl\") > 0 and
    count_lines(\"sync_pairs.jsonl\") > 0 and
    any_both_ok
)
print(\"ROS_SENSOR_RECORD_CHECK\", \"PASS\" if record_ok else \"FAIL\")
raise SystemExit(0 if record_ok else 2)
PY
'"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-dir", default="/home/ebaina/parking_sensor_records/case7_ros_check")
    parser.add_argument("--vm-duration", type=int, default=55)
    parser.add_argument("--board-timeout", default="180")
    parser.add_argument("--login-password", default="ebaina")
    args = parser.parse_args()

    vm_cmd = [
        r".\.venv\Scripts\python",
        r".\tools\vm_ssh_run.py",
        "--host",
        "192.168.137.100",
        "--user",
        "ebaina",
        "--password",
        "ebaina",
        "--timeout",
        str(args.vm_duration + 40),
        "--allow-risk",
        "run",
        vm_command(args.record_dir, args.vm_duration),
    ]
    board_cmd = [
        r".\.venv\Scripts\python",
        r".\tools\board_serial.py",
        "--login-password",
        args.login_password,
        "--timeout",
        args.board_timeout,
        "--allow-risk",
        "run",
        BOARD_COMMAND,
    ]

    print("VM ROS sensor suite command:")
    print(" ".join(vm_cmd))
    print("\nBoard-side command:")
    print(BOARD_COMMAND)

    vm_proc = subprocess.Popen(vm_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(5)
    board_result = subprocess.run(board_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    vm_out, _ = vm_proc.communicate(timeout=args.vm_duration + 45)

    print("\n=== Board output ===")
    print(board_result.stdout, end="")
    print("\n=== VM ROS sensor suite output ===")
    print(vm_out, end="")

    ok = (
        board_result.returncode == 0
        and "CASE7_RC=0" in board_result.stdout
        and "ROS_SENSOR_RECORD_CHECK PASS" in vm_out
    )
    print(f"\nROS_SENSOR_SUITE_CHECK={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
