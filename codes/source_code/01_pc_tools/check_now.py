#!/usr/bin/env python3
"""Quick check of current board state."""
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

    print("=== uptime ===")
    print(run(board, "uptime").strip())

    print("\n=== process ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo NONE").strip())

    print("\n=== log total lines ===")
    out = run(board, "wc -l /tmp/dtof.log 2>/dev/null || echo 'no log'")
    print(out.strip())

    print("\n=== log tail (last 30 lines) ===")
    out = run(board, "tail -30 /tmp/dtof.log 2>/dev/null", timeout=15)
    print(out.strip()[:3000])

    print("\n=== I2C errors count ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")

    print("\n=== frame err count ===")
    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"frame errors: {out.strip()}")

    print("\n=== dtof init / UDP messages ===")
    out = run(board, "grep -iE 'dtofInit|UdpSend|init success|pre-warm done|real VI init' /tmp/dtof.log 2>/dev/null | tail -10")
    print(out.strip() or "(none)")

    print("\n=== I2C4 scan ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=15)
    print(out.strip()[:500])

    board.close()

if __name__ == "__main__":
    main()
