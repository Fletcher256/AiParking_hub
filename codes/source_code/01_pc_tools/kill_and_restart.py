#!/usr/bin/env python3
"""Kill old binary cleanly and restart fresh."""
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

    print("=== Current processes ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep")
    print(out.strip())

    print("\n=== Kill old binary with SIGTERM ===")
    out = run(board, "pkill -TERM sample_dtof; echo 'SIGTERM sent'")
    print(out.strip())

    print("Waiting 8 seconds for clean exit...")
    time.sleep(8)

    out = run(board, "ps | grep sample_dtof | grep -v grep || echo 'all gone'")
    print(f"After 8s: {out.strip()}")

    if 'sample_dtof' in out:
        print("Still running, SIGKILL...")
        run(board, "pkill -9 sample_dtof")
        time.sleep(3)
        print("WARNING: Used SIGKILL - may need reboot")

    print("\n=== GS1860 on I2C after kill ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    gs1860_up = "28" in out

    print(f"\nGS1860 responding: {gs1860_up}")

    # Try to start binary fresh
    print("\n=== Starting fresh binary ===")
    out = run(board, "cd /opt/sample/dtof && "
              "(sleep 7200 | ./sample_dtof 3 192.168.137.100 2>&1) > /tmp/dtof.log 2>&1 & echo PID=$!")
    print(out.strip())

    print("\nWaiting 20 seconds for init...")
    time.sleep(20)

    print("\n=== Fresh log head ===")
    out = run(board, "head -30 /tmp/dtof.log 2>/dev/null || echo 'no log'")
    print(out.strip()[:3000])

    print("\n=== I2C after fresh start ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:400])

    print("\n=== Success messages ===")
    out = run(board, "grep -iE 'DtofInit|init success|UdpSend|pre-warm done|MCLK' /tmp/dtof.log 2>/dev/null")
    print(out.strip() or "(none)")

    print("\n=== Error counts ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")
    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"Frame errors: {out.strip()}")

    board.close()

if __name__ == "__main__":
    main()
