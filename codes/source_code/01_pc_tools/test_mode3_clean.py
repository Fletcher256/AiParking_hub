#!/usr/bin/env python3
"""Test mode 3 from clean state (reboot → SIGTERM S90autorun → start mode 3, check both sensors)."""
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

def kill_binary_clean(max_wait=30):
    """Kill sample_dtof binary with SIGTERM, wait until gone."""
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
    print("WARNING: binary didn't exit within timeout, force killing")
    c = connect()
    run(c, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; sleep 2")
    c.close()
    return False

def main():
    # 1. Current state
    print("=== Step 1: Current board state ===")
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo 'No binary'")
    print(f"Binary: {ps.strip()}")
    c.close()

    # 2. Reboot for clean ISP state
    print("\n=== Step 2: Rebooting for clean ISP state ===")
    c = connect()
    c.exec_command("reboot", timeout=5)
    c.close()
    print("Waiting for reboot...")
    time.sleep(25)
    if not wait_board(120):
        print("Board didn't come back after reboot, aborting.")
        return
    print("Board is back!")

    # 3. Give S90autorun ~5s to start, then kill cleanly
    time.sleep(5)
    print("\n=== Step 3: Killing S90autorun mode-3 binary with SIGTERM ===")
    ok = kill_binary_clean(max_wait=25)
    print(f"Binary killed cleanly: {ok}")

    # 4. Start mode 3 with log redirect
    print("\n=== Step 4: Starting mode 3 (OS08A20 + GS1860) ===")
    c = connect()
    rc, out = run(c, f"cd /opt/sample/dtof && sh ./dtof_init.sh 2>/dev/null; "
                     f"(sleep 7200 | ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1) > /tmp/mode3.log 2>&1 & echo PID=$!")
    print(f"Mode 3 start: {out.strip()}")
    c.close()

    # 5. Wait 30s for init
    print("Waiting 30s for init...")
    time.sleep(30)

    # 6. Check at t=30s
    print("\n=== Step 5: Status at t=30s ===")
    c = connect()
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"Binary running: {ps.strip()}")

    rc, vi = run(c, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"\nVI pipe status:\n{vi}")

    rc, mipi = run(c, "cat /proc/umap/mipi_rx | grep -A2 'phy data info'")
    print(f"\nMIPI PHY (header):\n{mipi}")

    rc, detect = run(c, "cat /proc/umap/mipi_rx | grep -A8 'detect info'")
    print(f"\nMIPI detect:\n{detect}")

    # OS08A20 register 0x0100
    rc, reg = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"\nOS08A20 0x0100 (streaming): {reg.strip()}")

    rc, log = run(c, "wc -l /tmp/mode3.log; tail -5 /tmp/mode3.log 2>/dev/null")
    print(f"\nMode 3 log:\n{log}")
    c.close()

    # 7. Wait another 30s and check VENC
    print("\nWaiting another 30s for VENC to produce frames...")
    time.sleep(30)

    print("\n=== Step 6: VENC + full check at t=60s ===")
    c = connect()

    rc, vi2 = run(c, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"VI pipe status:\n{vi2}")

    rc, venc = run(c, "cat /proc/umap/venc | grep -A6 'chn_id\\|seq\\|width\\|height' | head -30 2>/dev/null || echo 'no venc proc'")
    print(f"\nVENC status:\n{venc}")

    rc, isp = run(c, "cat /proc/umap/isp | grep -A4 'drv info' | head -15")
    print(f"\nISP drv info:\n{isp}")

    rc, log2 = run(c, "wc -l /tmp/mode3.log; tail -10 /tmp/mode3.log 2>/dev/null")
    print(f"\nMode 3 log:\n{log2}")

    # GS1860 check via mipi_rx proc
    rc, mipi2 = run(c, "cat /proc/umap/mipi_rx | grep -B1 -A4 'detect info'")
    print(f"\nMIPI detect (full):\n{mipi2}")

    c.close()

    # 8. Final cleanup - leave binary running if successful (S90autorun will manage it)
    print("\n=== Done. Binary left running for further verification. ===")
    print("Check /tmp/mode3.log on board, or run further tests against the stream.")

if __name__ == "__main__":
    main()
