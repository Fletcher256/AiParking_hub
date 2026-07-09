#!/usr/bin/env python3
"""Check MIPI RX proc entries while binary is running to diagnose OS08A20 interrupt=0 issue."""
import paramiko, time

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
    # Kill ALL existing instances thoroughly
    print("=== Killing all existing instances ===")
    c = connect()
    rc, out = run(c, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; pkill -9 -f 'sleep 7200' 2>/dev/null; sleep 2; ps | grep sample_dtof | grep -v grep || echo 'CLEAN'")
    print(out.strip())
    c.close()
    time.sleep(3)

    # Verify clean
    c = connect()
    rc, out = run(c, "ps | grep sample_dtof | grep -v grep || echo 'No dtof process - clean'")
    print(f"Pre-check: {out.strip()}")
    c.close()

    # Check MIPI RX BEFORE starting binary
    print("\n=== MIPI RX state BEFORE binary start ===")
    c = connect()
    rc, mipi_before = run(c, "cat /proc/umap/mipi_rx 2>/dev/null || echo 'not found'")
    print(mipi_before[:3000])
    c.close()

    # Start binary
    print("\n=== Starting binary (sleep 7200 pipe) ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && (sleep 7200 | ./sample_dtof_os08a20 3 %s) > /tmp/dtof.log 2>&1 & echo PID=$!" % SERVER_IP)
    print(f"Start: {out.strip()}")
    c.close()

    print("Waiting 15s for VI/MIPI init...")
    time.sleep(15)

    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"\nProcess: {ps.strip()}")

    print("\n=== MIPI RX state AFTER binary start (t=15s) ===")
    rc, mipi_after = run(c, "cat /proc/umap/mipi_rx 2>/dev/null || echo 'not found'")
    print(mipi_after[:4000])

    print("\n=== /proc/umap/mipi_rx full ===")
    rc, mipi_full = run(c, "cat /proc/umap/mipi_rx 2>/dev/null | head -100")
    print(mipi_full)

    print("\n=== VI proc (int_cnt check) ===")
    rc, vi = run(c, "cat /proc/umap/vi 2>/dev/null | grep -A3 'pipe_id  enable' | head -20")
    print(vi)

    print("\n=== VI pipe 0 and 2 status ===")
    rc, vi2 = run(c, "cat /proc/umap/vi 2>/dev/null")
    # Print relevant sections
    lines = vi2.split('\n')
    for i, line in enumerate(lines):
        if 'pipe' in line.lower() or 'int_cnt' in line.lower() or 'int_rat' in line.lower() or 'receive_pic' in line.lower():
            print(line)

    print("\n=== ISP proc ===")
    rc, isp = run(c, "cat /proc/umap/isp 2>/dev/null | head -40")
    print(isp)

    print("\n=== Binary log (first 50 lines) ===")
    rc, log = run(c, "head -50 /tmp/dtof.log")
    print(log)

    c.close()

    # Wait more and check again
    print("\nWaiting 15 more seconds (t=30s total)...")
    time.sleep(15)

    c = connect()
    print("\n=== VI pipe 0 int_cnt at t=30s ===")
    rc, vi3 = run(c, "cat /proc/umap/vi | grep -E 'pipe_id|int_cnt|receive_pic|frame_rate' | head -20")
    print(vi3)

    print("\n=== Binary log tail ===")
    rc, log2 = run(c, "tail -20 /tmp/dtof.log")
    print(log2)

    print("\n=== MIPI RX at t=30s (look for error counters) ===")
    rc, mipi30 = run(c, "cat /proc/umap/mipi_rx 2>/dev/null")
    print(mipi30[:5000])

    c.close()

    # Cleanup
    c = connect()
    run(c, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; pkill -9 -f 'sleep 7200' 2>/dev/null")
    c.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
