#!/usr/bin/env python3
"""Check VI pipe status WHILE binary is running."""
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
    # Kill existing
    c = connect()
    run(c, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; kill $(pgrep 'sleep 7200') 2>/dev/null; sleep 2")
    c.close()
    time.sleep(3)

    print("=== Starting binary ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && (sleep 7200 | ./sample_dtof_os08a20 3 %s) > /tmp/dtof.log 2>&1 & echo PID=$!" % SERVER_IP)
    print(f"Start: {out.strip()}")
    c.close()

    print("Waiting 20s for init...")
    time.sleep(20)

    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"Process: {ps.strip()}")

    print("\n=== VI proc (full) ===")
    rc, vi_full = run(c, "cat /proc/umap/vi 2>/dev/null")
    print(vi_full)

    print("\n=== ISP proc ===")
    rc, isp = run(c, "cat /proc/umap/isp 2>/dev/null | head -100")
    print(isp)

    print("\n=== VB pool 4 detail ===")
    rc, vb = run(c, "cat /proc/umap/vb | grep -A30 'pool_id phys' | head -60")
    print(vb)

    # Check if dtof.log has init messages
    print("\n=== Binary log ===")
    rc, log = run(c, "cat /tmp/dtof.log")
    print(log[:4000])

    c.close()

    # Cleanup
    c2 = connect()
    run(c2, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; kill $(pgrep 'sleep 7200') 2>/dev/null")
    c2.close()

if __name__ == "__main__":
    main()
