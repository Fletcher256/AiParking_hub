#!/usr/bin/env python3
"""Check board state after reboot with double dtof_init.sh."""
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
    # Try connecting
    for i in range(12):
        try:
            board = connect()
            print(f"Connected (attempt {i+1})")
            break
        except Exception as e:
            print(f"Attempt {i+1}: {e}")
            time.sleep(8)
    else:
        print("FAILED TO CONNECT")
        return

    print("\n=== uptime ===")
    out = run(board, "uptime")
    print(out.strip())

    print("\n=== ps ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep || echo NONE")
    print(out.strip())

    # Wait for binary to fully start (might still be in sleep 10 phase)
    print("\nWaiting 25 sec for binary to complete startup...")
    time.sleep(25)

    print("\n=== Log (head 30) ===")
    out = run(board, "head -30 /tmp/dtof.log 2>/dev/null || echo 'no log'")
    print(out.strip()[:3000])

    print("\n=== Log tail ===")
    out = run(board, "tail -10 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:1000])

    print("\n=== Error counts ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")

    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"Frame errors: {out.strip()}")

    out = run(board, "grep -c 'init success' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"init success msgs: {out.strip()}")

    out = run(board, "grep -c 'ISP Dev' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"ISP Dev msgs: {out.strip()}")

    print("\n=== I2C bus 4 ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=12)
    print(out.strip()[:500])

    print("\n=== VI pipe status ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -20 || echo 'no vi proc'")
    print(out.strip()[:1000])

    board.close()

if __name__ == "__main__":
    main()
