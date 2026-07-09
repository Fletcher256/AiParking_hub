#!/usr/bin/env python3
"""Reboot board and monitor MIPI/VI state during S90autorun startup."""
import paramiko, time, sys

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect(timeout=60):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
              timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def wait_for_board(max_wait=120):
    """Wait for board to come back up after reboot."""
    print("Waiting for board to reboot...")
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            c = connect(timeout=10)
            c.close()
            print("Board is back up!")
            return True
        except Exception:
            time.sleep(5)
    print("ERROR: Board did not come back up in time")
    return False

def main():
    # Step 1: Reboot board
    print("=== Rebooting board ===")
    c = connect()
    try:
        # Use exec_command directly, don't wait for response (board reboots)
        c.exec_command("reboot", timeout=5)
    except Exception:
        pass
    c.close()

    # Step 2: Wait for reboot
    time.sleep(15)  # Give board time to start rebooting
    if not wait_for_board(max_wait=120):
        sys.exit(1)

    # Step 3: Wait a bit more for S90autorun to start
    print("\nWaiting 10s for S90autorun to start running binary...")
    time.sleep(10)

    # Step 4: Monitor at multiple timestamps
    for elapsed in [10, 30, 60, 90]:
        c = connect()
        print(f"\n=== t={elapsed}s after board up ===")

        rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo 'not running'")
        print(f"Binary: {ps.strip()}")

        rc, mipi = run(c, "cat /proc/umap/mipi_rx 2>/dev/null | grep -A30 'phy data\\|detect info\\|lane divide'")
        print(f"MIPI:\n{mipi}")

        rc, vi_status = run(c, "cat /proc/umap/vi 2>/dev/null | grep -A3 'vi pipe status'")
        print(f"VI status:\n{vi_status}")

        rc, isp = run(c, "cat /proc/umap/isp 2>/dev/null | grep -A3 'drv info' | head -20")
        print(f"ISP:\n{isp}")

        rc, log = run(c, "wc -l /tmp/dtof.log 2>/dev/null; tail -3 /tmp/dtof.log 2>/dev/null || echo 'no log'")
        print(f"Log: {log.strip()}")

        c.close()

        if elapsed < 90:
            wait = [10, 30, 60, 90][([10, 30, 60, 90].index(elapsed) + 1)] - elapsed
            print(f"Waiting {wait}s more...")
            time.sleep(wait)

    # Final detailed check at 90s
    print("\n=== Final detailed check (t=90s) ===")
    c = connect()

    print("\n--- Full MIPI RX ---")
    rc, mipi_full = run(c, "cat /proc/umap/mipi_rx 2>/dev/null")
    print(mipi_full[:4000])

    print("\n--- Full VI (status section) ---")
    rc, vi_full = run(c, "cat /proc/umap/vi 2>/dev/null | head -100")
    print(vi_full[:5000])

    print("\n--- Binary log (non-I2C lines) ---")
    rc, log_full = run(c, "cat /tmp/dtof.log 2>/dev/null", timeout=20)
    lines = log_full.split('\n')
    i2c_count = sum(1 for l in lines if 'I2C_WRITE error' in l)
    non_i2c = [l for l in lines if 'I2C_WRITE error' not in l and l.strip()]
    print(f"Total lines: {len(lines)}, I2C errors: {i2c_count}")
    print(f"Non-I2C lines:")
    for l in non_i2c[:50]:
        print(l)

    print("\n--- I2C5 detect (OS08A20) ---")
    rc, i2c5 = run(c, "i2cdetect -y 5 2>/dev/null | head -5 || echo 'i2cdetect not available'")
    print(i2c5)

    c.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
