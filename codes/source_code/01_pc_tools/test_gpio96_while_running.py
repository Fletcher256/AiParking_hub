#!/usr/bin/env python3
"""
Test: pulse GPIO96 while binary is running (MCLK on).
Check if GS1860 appears at 0x28 after pulse.
"""
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
    board = connect()

    print("=== Binary running? ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep || echo NONE")
    print(out.strip())

    print("\n=== Log line count before ===")
    out = run(board, "wc -l /tmp/dtof.log 2>/dev/null")
    print(out.strip())

    print("\n=== I2C4 BEFORE pulse ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    # Run dtof_init.sh (bspmm + GPIO96 1→0→1)
    print("\n=== Running dtof_init.sh (GPIO96 pulse) ===")
    out = run(board, "sh /opt/sample/dtof/dtof_init.sh && echo 'done'")
    print(out.strip())

    # Wait for GS1860 to boot
    print("\nWaiting 8 seconds for GS1860 to boot...")
    time.sleep(8)

    print("\n=== I2C4 AFTER pulse (8s later) ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    # Check log for new messages
    print("\n=== Log tail (recent messages) ===")
    out = run(board, "tail -10 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:1000])

    # If GS1860 appeared, try to restart binary cleanly
    if "28" in out or "28" in run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15):
        print("\n*** GS1860 APPEARED! Now kill binary and restart ***")
        # SIGTERM
        out = run(board, "pkill -TERM -x 'sample_dtof'; sleep 5; ps | grep sample_dtof | grep -v grep || echo 'binary gone'")
        print(out.strip())

        print("Starting binary fresh...")
        out = run(board, "cd /opt/sample/dtof && "
                  "(sleep 7200 | ./sample_dtof 3 192.168.137.100 2>&1) > /tmp/dtof2.log 2>&1 & echo PID=$!")
        print(out.strip())

        time.sleep(15)

        print("\n=== Fresh start log ===")
        out = run(board, "head -30 /tmp/dtof2.log 2>/dev/null || echo 'no log'")
        print(out.strip()[:3000])

        print("\n=== I2C4 after restart ===")
        out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
        print(out.strip()[:400])
    else:
        print("\nGS1860 did NOT appear. Need different approach.")

    board.close()

if __name__ == "__main__":
    main()
