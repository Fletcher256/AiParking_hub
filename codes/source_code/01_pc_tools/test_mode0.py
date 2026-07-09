#!/usr/bin/env python3
"""Test mode 0 (single OS08A20 only) to verify camera MIPI works in isolation."""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect(timeout=30):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=timeout)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    # Check current state
    print("=== Current board state ===")
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo 'No binary running'")
    print(f"Binary: {ps.strip()}")
    rc, mipi = run(c, "cat /proc/umap/mipi_rx 2>/dev/null | grep -A2 'phy data info' || echo 'no mipi'")
    print(f"MIPI: {mipi.strip()}")
    c.close()

    # Make sure board is clean (no binary running)
    print("\n=== Killing any remaining processes ===")
    c = connect()
    # Use SIGTERM (not SIGKILL) so cleanup runs
    run(c, "pkill -15 -f sample_dtof_os08a20 2>/dev/null; sleep 3")
    rc, ps2 = run(c, "ps | grep sample_dtof | grep -v grep || echo 'CLEAN'")
    print(f"After kill: {ps2.strip()}")
    c.close()
    time.sleep(2)

    # Reboot to get clean ISP state
    print("\n=== Rebooting for clean state ===")
    c = connect()
    c.exec_command("reboot", timeout=5)
    c.close()

    print("Waiting for reboot (45s)...")
    time.sleep(20)

    # Wait for SSH
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            c = connect(timeout=10)
            c.close()
            print("Board is back!")
            break
        except Exception:
            time.sleep(3)
    else:
        print("Board didn't come back, exit")
        return

    # Quick check before S90autorun binary starts
    time.sleep(5)

    # Kill the mode-3 binary that S90autorun started
    print("\n=== Killing S90autorun mode-3 binary (SIGTERM for clean ISP exit) ===")
    c = connect()
    # Use SIGTERM for clean ISP cleanup, wait up to 15s for it to exit
    run(c, "pkill -15 -f sample_dtof_os08a20 2>/dev/null; sleep 8")
    rc, ps3 = run(c, "ps | grep sample_dtof | grep -v grep || echo 'CLEAN'")
    print(f"After SIGTERM (8s): {ps3.strip()}")
    # If still running, wait more
    if 'sample_dtof' in ps3:
        print("Still running, waiting 8 more seconds...")
        run(c, "sleep 8")
        rc, ps3b = run(c, "ps | grep sample_dtof | grep -v grep || echo 'CLEAN'")
        print(f"After 16s: {ps3b.strip()}")
        if 'sample_dtof' in ps3b:
            print("WARNING: binary didn't exit cleanly, force killing with SIGKILL")
            run(c, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; sleep 3")
    c.close()

    time.sleep(3)

    # Start mode 0 (single OS08A20) - redirect stdout AND stderr
    # NOTE: binary requires <index> <dst_ip> - must pass dst_ip even for mode 0
    print("\n=== Starting mode 0 (single OS08A20) ===")
    c = connect()
    rc, out = run(c, "cd /opt/sample/dtof && (sleep 7200 | ./sample_dtof_os08a20 0 192.168.137.100 2>&1) > /tmp/mode0.log 2>&1 & echo PID=$!")
    print(f"Mode 0 start: {out.strip()}")
    c.close()

    # Wait for init
    print("Waiting 20s for mode 0 to initialize...")
    time.sleep(20)

    c = connect()
    rc, ps4 = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"\n[t=20s] Binary: {ps4.strip()}")

    rc, log = run(c, "wc -l /tmp/mode0.log; head -20 /tmp/mode0.log 2>/dev/null || echo 'no log'")
    print(f"Mode 0 log:\n{log}")

    rc, vi = run(c, "cat /proc/umap/vi | grep -A6 'vi pipe status'")
    print(f"\nVI status:\n{vi}")

    rc, mipi2 = run(c, "cat /proc/umap/mipi_rx | grep -A6 'phy data info'")
    print(f"\nMIPI PHY:\n{mipi2}")

    # Read OS08A20 register 0x0100
    print("\n=== OS08A20 0x0100 register ===")
    rc, val = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"0x0100 = {val.strip()}")

    # dmesg for any I2C errors
    print("\n=== dmesg I2C errors ===")
    rc, dm = run(c, "dmesg | grep -i 'timeout\\|i2c.*error\\|os08a20' | tail -10 2>/dev/null")
    print(dm)

    # Wait more and check
    time.sleep(15)
    c2 = connect()
    print("\n[t=35s] Checking again...")
    rc, vi2 = run(c2, "cat /proc/umap/vi | grep -A4 'vi pipe status'")
    print(f"VI status:\n{vi2}")
    rc, mipi3 = run(c2, "cat /proc/umap/mipi_rx | grep -A2 'detect info'")
    print(f"MIPI detect:\n{mipi3}")
    rc, log2 = run(c2, "tail -10 /tmp/mode0.log 2>/dev/null")
    print(f"Log tail:\n{log2}")
    c2.close()

    # Cleanup
    c = connect()
    run(c, "pkill -15 -f sample_dtof_os08a20 2>/dev/null; pkill -9 -f 'sleep 7200' 2>/dev/null")
    c.close()
    print("\nMode 0 test complete.")

if __name__ == "__main__":
    main()
