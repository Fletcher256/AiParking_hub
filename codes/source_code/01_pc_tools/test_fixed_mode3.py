#!/usr/bin/env python3
"""Test mode 3 with the fixed binary (sns_rst_src=2 for GS1860)."""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SERVER_IP   = "192.168.137.100"

def connect(timeout=30):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=timeout)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def wait_board(timeout_s=120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            c = connect(timeout=8)
            c.close()
            return True
        except Exception:
            time.sleep(3)
    return False

def kill_binary_clean(max_wait=25):
    c = connect()
    run(c, "pkill -15 -f sample_dtof_os08a20 2>/dev/null")
    c.close()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(3)
        c = connect()
        rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo CLEAN")
        c.close()
        if "CLEAN" in ps or "sample_dtof" not in ps:
            return True
    # Force kill if needed
    c = connect()
    run(c, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; sleep 2")
    c.close()
    return False

def main():
    print("=== Rebooting for clean state ===")
    c = connect()
    c.exec_command("reboot", timeout=5)
    c.close()
    print("Waiting...")
    time.sleep(25)
    if not wait_board(120):
        print("Board unreachable!")
        return
    print("Board back!")

    # Let S90autorun start, then kill it
    time.sleep(5)
    print("\n=== Killing S90autorun binary ===")
    kill_binary_clean(max_wait=25)

    time.sleep(3)

    # Start mode 3 with log
    print("\n=== Starting fixed mode 3 binary ===")
    c = connect()
    rc, out = run(c,
        "cd /opt/sample/dtof && sh ./dtof_init.sh 2>/dev/null; "
        f"(sleep 7200 | ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1) > /tmp/mode3_fix.log 2>&1 & echo PID=$!")
    print(f"PID: {out.strip()}")
    c.close()

    print("Waiting 30s...")
    time.sleep(30)

    print("\n=== [t=30s] Results ===")
    c = connect()

    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo GONE")
    print(f"Binary: {ps.strip()}")

    rc, vi = run(c, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"\nVI status:\n{vi}")

    rc, mipi = run(c, "cat /proc/umap/mipi_rx | grep -A2 'phy data info'")
    print(f"\nMIPI:\n{mipi}")

    rc, reg = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"\nOS08A20 0x0100: {reg.strip()}")

    rc, log_head = run(c, "head -6 /tmp/mode3_fix.log 2>/dev/null")
    print(f"\nLog head:\n{log_head}")
    c.close()

    print("\nWaiting 30 more seconds...")
    time.sleep(30)

    print("\n=== [t=60s] Full check ===")
    c = connect()

    rc, vi2 = run(c, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"VI status:\n{vi2}")

    rc, venc = run(c, "cat /proc/umap/venc | grep 'sequence\\|width\\|height\\|started' | head -8 2>/dev/null")
    print(f"\nVENC:\n{venc}")

    rc, detect = run(c, "cat /proc/umap/mipi_rx | grep -A6 'detect info'")
    print(f"\nMIPI detect:\n{detect}")

    rc, reg2 = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"\nOS08A20 0x0100: {reg2.strip()}")

    rc, log = run(c, "wc -l /tmp/mode3_fix.log; head -10 /tmp/mode3_fix.log 2>/dev/null")
    print(f"\nLog:\n{log}")
    c.close()

    print("\n=== Test complete. Binary left running. ===")

if __name__ == "__main__":
    main()
