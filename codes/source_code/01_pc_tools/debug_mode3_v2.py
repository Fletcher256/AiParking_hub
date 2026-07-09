#!/usr/bin/env python3
"""Debug mode 3 - run binary, check proc at precise moments."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SERVER_IP = "192.168.137.100"

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client

def run(client, cmd, timeout=15):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    # Kill any existing processes
    c = connect()
    run(c, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; sleep 1")
    c.close()
    time.sleep(2)

    print("=== Starting binary via nohup ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && nohup ./sample_dtof_os08a20 3 %s > /tmp/dtof.log 2>&1 & echo PID=$!" % SERVER_IP)
    print(f"Start: {out.strip()}")
    c.close()

    # Check quickly (3s) - before GS1860 I2C errors
    time.sleep(3)
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof_os08a20 | grep -v grep")
    print(f"\n[t=3s] Process: {ps.strip()}")
    rc, vb = run(c, "cat /proc/umap/vb | grep -A2 'pub config'")
    print(f"[t=3s] VB: {vb.strip()}")
    rc, vpss = run(c, "cat /proc/umap/vpss | grep -A3 'grp attr1'")
    print(f"[t=3s] VPSS:\n{vpss}")
    rc, venc = run(c, "cat /proc/umap/venc | grep -A3 'chn attr 1'")
    print(f"[t=3s] VENC:\n{venc}")
    rc, log3 = run(c, "cat /tmp/dtof.log | head -5")
    print(f"[t=3s] Log (first 5 lines): {log3.strip()}")
    c.close()

    # Check at 15s (deep in GS1860 I2C phase)
    time.sleep(12)
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof_os08a20 | grep -v grep")
    print(f"\n[t=15s] Process: {ps.strip()}")
    rc, vb = run(c, "cat /proc/umap/vb | grep -A2 'pub config'")
    print(f"[t=15s] VB: {vb.strip()}")
    rc, log_lines = run(c, "wc -l /tmp/dtof.log; tail -3 /tmp/dtof.log")
    print(f"[t=15s] Log lines + tail: {log_lines.strip()}")
    rc, venc2 = run(c, "cat /proc/umap/venc | grep -A5 'recv state'")
    print(f"[t=15s] VENC recv state:\n{venc2}")
    c.close()

    # Check at 30s (should be past DtofInit)
    time.sleep(15)
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof_os08a20 | grep -v grep")
    print(f"\n[t=30s] Process: {ps.strip()}")
    rc, log_tail = run(c, "tail -10 /tmp/dtof.log")
    print(f"[t=30s] Log tail:\n{log_tail}")
    rc, venc3 = run(c, "cat /proc/umap/venc | grep -A5 'chn attr 1'")
    print(f"[t=30s] VENC:\n{venc3}")
    rc, h264 = run(c, "ls -la /opt/sample/dtof/stream_chn0.h264 2>/dev/null")
    print(f"[t=30s] H.264 file: {h264.strip()}")
    c.close()

    # Cleanup
    c = connect()
    run(c, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null")
    c.close()

if __name__ == "__main__":
    main()
