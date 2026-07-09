#!/usr/bin/env python3
"""Wait 90s for full init, then check VI/MIPI status comprehensively."""
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

def run(client, cmd, timeout=20):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    # Kill all instances cleanly
    print("=== Kill all instances ===")
    c = connect()
    run(c, "pkill -9 -f sample_dtof_os08a20; pkill -9 -f 'sleep 7200'; sleep 2")
    c.close()
    time.sleep(3)

    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo CLEAN")
    print(ps.strip())
    c.close()

    # Start binary
    print("\n=== Starting binary ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && (sleep 7200 | ./sample_dtof_os08a20 3 %s) > /tmp/dtof.log 2>&1 & echo PID=$!" % SERVER_IP)
    print(f"Start: {out.strip()}")
    c.close()

    # Check at t=30s (still in I2C flood)
    print("\nWaiting 30s...")
    time.sleep(30)
    c = connect()
    rc, log30 = run(c, "wc -l /tmp/dtof.log; tail -3 /tmp/dtof.log")
    print(f"[t=30s] Log: {log30.strip()}")
    rc, ps30 = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"[t=30s] PID: {ps30.strip()}")
    c.close()

    # Check at t=60s
    print("\nWaiting 30 more seconds (t=60s)...")
    time.sleep(30)
    c = connect()
    rc, log60 = run(c, "wc -l /tmp/dtof.log; tail -5 /tmp/dtof.log")
    print(f"[t=60s] Log:\n{log60.strip()}")
    rc, ps60 = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"[t=60s] PID: {ps60.strip()}")
    rc, vi60 = run(c, "cat /proc/umap/vi | grep -A2 'vi pipe status'")
    print(f"[t=60s] VI status section:\n{vi60}")
    c.close()

    # Wait 30 more
    print("\nWaiting 30 more seconds (t=90s)...")
    time.sleep(30)

    c = connect()
    rc, ps90 = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"\n[t=90s] Process: {ps90.strip()}")

    print("\n=== Full binary log ===")
    rc, full_log = run(c, "cat /tmp/dtof.log", timeout=20)
    # Print last 3000 chars and count unique lines
    lines = full_log.split('\n')
    i2c_count = sum(1 for l in lines if 'I2C_WRITE error' in l)
    non_i2c = [l for l in lines if 'I2C_WRITE error' not in l]
    print(f"Total lines: {len(lines)}, I2C errors: {i2c_count}")
    print(f"Non-I2C lines ({len(non_i2c)}):")
    for l in non_i2c[:100]:
        print(l)

    print("\n=== Full /proc/umap/vi ===")
    rc, vi_full = run(c, "cat /proc/umap/vi 2>/dev/null", timeout=20)
    print(vi_full[:5000])

    print("\n=== MIPI RX at t=90s ===")
    rc, mipi = run(c, "cat /proc/umap/mipi_rx 2>/dev/null | head -40")
    print(mipi)

    print("\n=== ISP drv info ===")
    rc, isp = run(c, "cat /proc/umap/isp | grep -A5 'drv info'")
    print(isp)

    print("\n=== VPSS ===")
    rc, vpss = run(c, "cat /proc/umap/vpss | head -30")
    print(vpss)

    print("\n=== VENC ===")
    rc, venc = run(c, "cat /proc/umap/venc | head -30")
    print(venc)

    c.close()

    # Cleanup
    c = connect()
    run(c, "pkill -9 -f sample_dtof_os08a20; pkill -9 -f 'sleep 7200'")
    c.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
