#!/usr/bin/env python3
"""Check new run status."""
import paramiko, time

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

    # 1. Check binary status
    print("=== Binary running ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep")
    print(out.strip())

    # 2. Check log file
    print("\n=== Log file ===")
    out = run(board, "ls -la /tmp/mode3_fix.log 2>/dev/null; wc -l /tmp/mode3_fix.log 2>/dev/null")
    print(out.strip())

    # 3. Check if log is being written (size change)
    print("\n=== Log size monitoring (2 samples 3 sec apart) ===")
    out1 = run(board, "wc -c /tmp/mode3_fix.log 2>/dev/null")
    print(f"t=0: {out1.strip()}")
    time.sleep(3)
    out2 = run(board, "wc -c /tmp/mode3_fix.log 2>/dev/null")
    print(f"t=3: {out2.strip()}")

    # 4. Read log content
    print("\n=== Log content (all) ===")
    out = run(board, "cat /tmp/mode3_fix.log 2>/dev/null | head -50")
    print(out.strip()[:5000])

    # 5. Check /proc/msp for any VI info
    print("\n=== /proc/msp contents ===")
    out = run(board, "ls /proc/msp/ 2>/dev/null")
    print(out.strip())

    # 6. Check the binary output via direct fd read
    print("\n=== Binary FDs ===")
    out = run(board, "pid=$(ps | grep './sample_dtof_os08a20' | grep -v grep | awk '{print $1}' | head -1); "
                     "echo PID=$pid; ls -la /proc/$pid/fd/ 2>/dev/null")
    print(out.strip())

    # 7. Check GS1860 VI pipe frames
    print("\n=== VI pipe 2 interrupt count ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | grep -i 'pipe 2\\|int\\|frame\\|cnt' | head -10 || echo 'vi proc empty'")
    print(out.strip())

    # 8. Wait more time and check again
    print("\n=== Waiting 15 more seconds... ===")
    time.sleep(15)

    out = run(board, "wc -l /tmp/mode3_fix.log 2>/dev/null; tail -5 /tmp/mode3_fix.log 2>/dev/null")
    print("After 15s:")
    print(out.strip()[:2000])

    board.close()

if __name__ == "__main__":
    main()
