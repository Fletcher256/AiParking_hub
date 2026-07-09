#!/usr/bin/env python3
"""Check board state after reboot - why is vi_pipe 2 failing?"""
import paramiko

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST    = "192.168.137.100"
VM_USER    = "ebaina"
VM_PASS    = "ebaina"

def connect(host, user, pw):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=30)
    return c

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)

    # 1. Get full log head (first 100 lines = startup sequence)
    print("=== Board log - startup (first 80 lines) ===")
    out = run(board, "head -80 /tmp/mode3_fix.log 2>/dev/null || head -80 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:5000])

    # 2. Check if ISP/VI is loaded
    print("\n=== Board: lsmod | grep ko ===")
    out = run(board, "lsmod 2>/dev/null | grep -E 'ot|iss|isp|vi|mipi' | head -20")
    print(out.strip())

    # 3. Check dtof_init.sh result
    print("\n=== Board: dtof_init.sh result (any errors logged?) ===")
    out = run(board, "cat /tmp/dtof_init.log 2>/dev/null || echo 'no dtof_init log'")
    print(out.strip())

    # 4. Check MIPI configuration
    print("\n=== Board: /proc/msp/mipi ===")
    out = run(board, "cat /proc/msp/mipi 2>/dev/null | head -30 || echo 'no mipi proc'")
    print(out.strip()[:2000])

    # 5. Check vi proc
    print("\n=== Board: /proc/msp/vi ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -50 || echo 'no vi proc'")
    print(out.strip()[:3000])

    # 6. Check isp proc
    print("\n=== Board: /proc/msp/isp ===")
    out = run(board, "cat /proc/msp/isp 2>/dev/null | head -30 || echo 'no isp proc'")
    print(out.strip()[:2000])

    # 7. Get line count of log to see how long it's been running
    print("\n=== Board: log size ===")
    out = run(board, "wc -l /tmp/mode3_fix.log 2>/dev/null; ls -la /tmp/mode3_fix.log 2>/dev/null")
    print(out.strip())

    # 8. Get the first non-error lines from the log
    print("\n=== Board: log - first 200 lines ===")
    out = run(board, "head -200 /tmp/mode3_fix.log 2>/dev/null | grep -v 'frame err' | head -50")
    print(out.strip()[:3000])

    # 9. Check if sample_dtof binary is responding to signals
    print("\n=== Board: kill -0 check ===")
    out = run(board, "pid=$(pgrep -f sample_dtof_os08a20 | head -1); echo PID=$pid; kill -0 $pid 2>&1 && echo 'alive' || echo 'dead'")
    print(out.strip())

    board.close()

if __name__ == "__main__":
    main()
