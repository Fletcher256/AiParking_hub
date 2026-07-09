#!/usr/bin/env python3
"""Verify GS1860 pre-warm v3 result after reboot."""
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
    return out + err

def main():
    print("Waiting for board to come back...")
    for i in range(15):
        try:
            board = connect()
            print(f"Connected (attempt {i+1})")
            break
        except Exception as e:
            print(f"  {i+1}: {e}")
            time.sleep(8)
    else:
        print("FAILED")
        return

    print("\n=== uptime ===")
    print(run(board, "uptime").strip())

    print("\n=== binary running? ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo NONE").strip())

    # Pre-warm takes 1+10+1 = 12s of sleep + overhead.
    # S90autorun: modules load + dtof_init.sh + sleep 3 = ~30s
    # Total: ~45s from boot. We wait 60s after connection.
    print(f"\nWaiting 60s for pre-warm to complete (1+10+1 sleep = 12s in binary + ~30s startup)...")
    time.sleep(60)

    print("\n=== Log (first 50 lines) ===")
    out = run(board, "head -50 /tmp/dtof.log 2>/dev/null || echo 'no log'", timeout=15)
    print(out.strip()[:5000])

    print("\n=== Pre-warm messages ===")
    out = run(board, "grep -E 'pre-warm|GS1860|MCLK|real VI init|DtofInit' /tmp/dtof.log 2>/dev/null", timeout=15)
    print(out.strip() or "(none)")

    print("\n=== Error counts ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")
    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"frame errors: {out.strip()}")

    print("\n=== I2C4 scan ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    print("\n=== Log tail ===")
    out = run(board, "tail -20 /tmp/dtof.log 2>/dev/null", timeout=15)
    print(out.strip()[:2000])

    # Check log line count growth (indicates binary is running and producing output)
    count1 = run(board, "wc -l /tmp/dtof.log 2>/dev/null").strip()
    time.sleep(5)
    count2 = run(board, "wc -l /tmp/dtof.log 2>/dev/null").strip()
    print(f"\n=== Log growth: {count1} → {count2} (over 5s) ===")

    board.close()

if __name__ == "__main__":
    main()
