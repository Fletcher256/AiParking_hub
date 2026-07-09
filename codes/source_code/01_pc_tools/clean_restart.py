#!/usr/bin/env python3
"""
Properly kill the sample_dtof binary by its exact PID and restart cleanly.
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

    # 1. Find all dtof binary pids (not the shell)
    print("=== Current processes ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep")
    print(out.strip())

    # 2. Kill the actual binary processes (all of them) with SIGTERM
    print("\n=== Killing all sample_dtof binaries (SIGTERM) ===")
    out = run(board, "ps | grep './sample_dtof_os08a20' | grep -v grep | awk '{print $1}' | "
                     "while read pid; do echo Killing $pid; kill -TERM $pid 2>/dev/null; done")
    print(out.strip())

    # Also use pkill
    out = run(board, "pkill -TERM -x 'sample_dtof_os08a20' 2>/dev/null; echo pkill done")
    print(out.strip())

    # 3. Wait for clean exit
    print("\n=== Waiting 8 sec for clean ISP exit... ===")
    time.sleep(8)

    # 4. Check if still alive
    out = run(board, "ps | grep sample_dtof | grep -v grep || echo 'all gone'")
    print("After SIGTERM:", out.strip())

    # 5. Force kill if still alive
    out = run(board, "pkill -9 -x 'sample_dtof_os08a20' 2>/dev/null; "
                     "ps | grep sample_dtof | grep -v grep || echo 'all gone'")
    print("After SIGKILL:", out.strip())

    time.sleep(3)

    # 6. Re-run dtof_init.sh for fresh GS1860 hardware init
    print("\n=== Re-running dtof_init.sh ===")
    out = run(board, "cd /opt/sample/dtof && sh ./dtof_init.sh 2>&1 && echo 'dtof_init OK'", timeout=15)
    print(out.strip())

    time.sleep(2)

    # 7. Start binary fresh (with a small delay for hardware settling)
    print("\n=== Starting binary (mode 3) ===")
    out = run(board, "cd /opt/sample/dtof && "
                     "(sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 2>&1) > /tmp/mode3_fix.log 2>&1 & "
                     "echo BGPID=$!")
    print(out.strip())

    # 8. Wait 20 seconds for startup and GS1860 frames
    print("\n=== Waiting 20 sec for GS1860 to start sending frames... ===")
    time.sleep(20)

    # 9. Check log
    print("\n=== Log head (first 25 lines, filtered) ===")
    out = run(board, "head -25 /tmp/mode3_fix.log 2>/dev/null | grep -v '^$'")
    print(out.strip()[:3000])

    # 10. Check last few lines
    print("\n=== Log tail ===")
    out = run(board, "tail -10 /tmp/mode3_fix.log 2>/dev/null")
    print(out.strip()[:1000])

    # 11. Count frame errors
    out = run(board, "grep -c 'frame err' /tmp/mode3_fix.log 2>/dev/null")
    print(f"\nFrame error count: {out.strip()}")

    # 12. Check vi pipe 2
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -20 || echo 'no vi proc'")
    print(f"\nVI status: {out.strip()[:1000]}")

    # 13. Check if binary is running and stable
    out = run(board, "ps | grep './sample_dtof_os08a20' | grep -v grep | head -3")
    print(f"\nBinary status: {out.strip()}")

    board.close()

if __name__ == "__main__":
    main()
