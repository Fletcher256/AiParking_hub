#!/usr/bin/env python3
"""Read dtof_init.sh and related scripts on board."""
import paramiko

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    board = connect()

    print("=== dtof_init.sh ===")
    out = run(board, "cat /opt/sample/dtof/dtof_init.sh")
    print(out)

    print("=== ls /opt/sample/dtof/ ===")
    out = run(board, "ls /opt/sample/dtof/")
    print(out.strip())

    # Any other shell scripts that dtof_init.sh calls
    print("\n=== grep gpio /opt/sample/dtof/dtof_init.sh ===")
    out = run(board, "grep -i gpio /opt/sample/dtof/dtof_init.sh")
    print(out.strip())

    print("\n=== Any gpio scripts ===")
    out = run(board, "find /opt/sample/dtof/ -name '*.sh' 2>/dev/null | xargs grep -l gpio 2>/dev/null")
    print(out.strip())

    # Check GPIO96 state right now
    print("\n=== GPIO96 state now ===")
    out = run(board, "cat /sys/class/gpio/gpio96/value /sys/class/gpio/gpio96/direction 2>/dev/null || echo 'gpio96 not exported'")
    print(out.strip())

    # Check which MPI functions might re-init sensor
    print("\n=== /proc/msp/vi ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -40 || echo 'no vi proc'")
    print(out.strip()[:2000])

    board.close()

if __name__ == "__main__":
    main()
