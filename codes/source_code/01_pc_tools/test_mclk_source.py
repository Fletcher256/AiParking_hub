#!/usr/bin/env python3
"""
Critical test: Does GS1860 appear on I2C without binary running?
Tests whether MCLK comes from PWM (dtof_init.sh bspmm) or VI framework (binary).
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

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    board = connect()

    print("=== Kill binary ===")
    run(board, "pkill -TERM sample_dtof")
    time.sleep(5)
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo 'gone'").strip())

    print("\n=== I2C4 before dtof_init.sh (binary stopped) ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    # Run dtof_init.sh
    print("\n=== Running dtof_init.sh ===")
    out = run(board, "sh /opt/sample/dtof/dtof_init.sh && echo 'done'")
    print(out.strip())

    # Wait various intervals
    for wait_secs in [5, 10, 15, 20]:
        time.sleep(5)  # each iteration waits 5 more seconds
        total = wait_secs
        print(f"\n=== I2C4 after {total}s ===")
        out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
        # Just show row with 0x28
        lines = out.strip().split('\n')
        print(out.strip()[:400])
        if "28" in out:
            print(f"*** GS1860 APPEARED at 0x28 after {total}s! ***")
            print("CONCLUSION: MCLK comes from PWM (dtof_init.sh bspmm), not VI framework!")
            break
    else:
        print("\n*** GS1860 did NOT appear after 20s without binary ***")
        print("CONCLUSION: MCLK comes from VI framework (binary must run)")

    # Also check GPIO96 state
    print("\n=== GPIO96 state ===")
    out = run(board, "cat /sys/class/gpio/gpio96/value /sys/class/gpio/gpio96/direction 2>/dev/null")
    print(out.strip())

    # Check what bspmm does for MCLK
    print("\n=== Check if any clock-related proc entry ===")
    out = run(board, "ls /proc/msp/ 2>/dev/null | head -20")
    print(out.strip())

    board.close()

if __name__ == "__main__":
    main()
