#!/usr/bin/env python3
"""Check VENC encoding status and if H.264 stream is being produced."""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Full VENC proc
    print("=== Full /proc/umap/venc ===")
    rc, venc = run(c, "cat /proc/umap/venc 2>/dev/null | head -60")
    print(venc)

    # Check VI and VPSS status
    print("\n=== VPSS status ===")
    rc, vpss = run(c, "cat /proc/umap/vpss 2>/dev/null | grep -A4 'grp_id\\|send\\|recv\\|sequence' | head -30")
    print(vpss)

    # ISP int_cnt - should be counting now
    print("\n=== ISP drv info ===")
    rc, isp = run(c, "cat /proc/umap/isp | grep -A4 'drv info' | head -20")
    print(isp)

    # Check dmesg for any errors
    print("\n=== Recent dmesg errors ===")
    rc, dm = run(c, "dmesg | grep -i 'error\\|timeout\\|fail' | tail -10 2>/dev/null")
    print(dm[:1000])

    c.close()

    print("\n=== Waiting 10s, checking VENC sequence again ===")
    time.sleep(10)
    c = connect()
    rc, venc2 = run(c, "cat /proc/umap/venc 2>/dev/null | grep -A2 'venc stream state\\|sequence\\|frame_rate' | head -20")
    print(venc2)
    c.close()

if __name__ == "__main__":
    main()
