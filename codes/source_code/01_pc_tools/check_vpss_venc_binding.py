#!/usr/bin/env python3
"""Start binary with sleep 7200 pipe (like S90autorun), check VPSS/VENC binding state."""
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
    # Kill any existing
    c = connect()
    run(c, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; sleep 1")
    c.close()
    time.sleep(2)

    print("=== Starting with sleep 7200 pipe (like S90autorun) ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && (sleep 7200 | ./sample_dtof_os08a20 3 %s) > /tmp/dtof.log 2>&1 & echo PID=$!" % SERVER_IP)
    print(f"Start: {out.strip()}")
    c.close()

    # Wait 25s for full init (GS1860 INI takes ~10s, then VI/dtof/vi_bayerdump)
    print("Waiting 25s for full initialization...")
    time.sleep(25)

    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"\nProcess: {ps.strip()}")

    print("\n=== Full /proc/umap/vpss ===")
    rc, vpss_full = run(c, "cat /proc/umap/vpss 2>/dev/null | head -60")
    print(vpss_full)

    print("\n=== Full /proc/umap/venc ===")
    rc, venc_full = run(c, "cat /proc/umap/venc 2>/dev/null | head -60")
    print(venc_full)

    print("\n=== /proc/umap/sys (bind table) ===")
    rc, sys_full = run(c, "cat /proc/umap/sys 2>/dev/null | head -50")
    print(sys_full)

    print("\n=== VB pool state ===")
    rc, vb_full = run(c, "cat /proc/umap/vb 2>/dev/null | head -40")
    print(vb_full)

    print("\n=== H.264 file size ===")
    rc, h264 = run(c, "ls -la /opt/sample/dtof/stream_chn0.h264 2>/dev/null")
    print(h264.strip())

    # Check VENC sequence count (should be > 0 if frames are encoded)
    print("\n=== VENC sequence after 5 more seconds ===")
    time.sleep(5)
    rc, venc2 = run(c, "cat /proc/umap/venc | grep -A3 'chn attr 1'")
    print(venc2)

    # Cleanup
    c.close()
    c2 = connect()
    run(c2, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; kill $(pgrep 'sleep 7200') 2>/dev/null")
    c2.close()

if __name__ == "__main__":
    main()
