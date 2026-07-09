#!/usr/bin/env python3
"""Check board after reboot with GS1860 pre-warm patch."""
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
    print("Waiting for board to come back up...")
    for i in range(15):
        try:
            board = connect()
            print(f"Connected (attempt {i+1})")
            break
        except Exception as e:
            print(f"  Attempt {i+1}: {e}")
            time.sleep(8)
    else:
        print("FAILED TO CONNECT")
        return

    print("\n=== uptime ===")
    print(run(board, "uptime").strip())

    print("\n=== running process ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo NONE").strip())

    # Wait for pre-warm to complete (6s + 3s + 1s = ~10s of sleeps in pre-warm)
    # plus startup time. Wait 25s total.
    print("\nWaiting 30s for pre-warm sequence to complete...")
    time.sleep(30)

    print("\n=== Log head (first 40 lines) ===")
    out = run(board, "head -40 /tmp/dtof.log 2>/dev/null || echo 'no log'")
    print(out.strip()[:4000])

    print("\n=== Log tail ===")
    out = run(board, "tail -20 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:2000])

    print("\n=== Pre-warm messages ===")
    out = run(board, "grep -i 'pre-warm\\|GS1860\\|gpio96' /tmp/dtof.log 2>/dev/null | head -10")
    print(out.strip() or "(none found)")

    print("\n=== I2C error count ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")

    print("\n=== Frame error count ===")
    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"Frame errors: {out.strip()}")

    print("\n=== UdpSend / dtof init ===")
    out = run(board, "grep -i 'udp\\|DtofInit\\|init success\\|UdpSend' /tmp/dtof.log 2>/dev/null | head -10")
    print(out.strip() or "(none found)")

    print("\n=== I2C4 scan ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:500])

    print("\n=== VI pipe status ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -30 || echo 'no vi proc'")
    print(out.strip()[:1500])

    board.close()

if __name__ == "__main__":
    main()
