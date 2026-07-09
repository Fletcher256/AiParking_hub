#!/usr/bin/env python3
"""
Restart sample_dtof_os08a20 cleanly and verify GS1860 is producing frames.
Steps:
1. Kill current binary (SIGTERM)
2. Re-run dtof_init.sh
3. Restart binary
4. Monitor log for 30 seconds
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

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    board = connect()

    # 1. Show dtof_init.sh
    print("=== dtof_init.sh content ===")
    out = run(board, "cat /opt/sample/dtof/dtof_init.sh")
    print(out.strip())

    # 2. Kill current binary with SIGTERM
    print("\n=== Killing current binary with SIGTERM ===")
    out = run(board, "pid=$(pgrep -f 'sample_dtof_os08a20' | head -1); echo PID=$pid; "
                     "kill -TERM $pid 2>/dev/null; sleep 3; "
                     "kill -9 $pid 2>/dev/null; "
                     "ps | grep sample_dtof | grep -v grep || echo 'binary stopped'")
    print(out.strip())

    # 3. Check lsmod for ko modules
    print("\n=== lsmod (all) ===")
    out = run(board, "lsmod 2>/dev/null | head -40")
    print(out.strip())

    # 4. Re-run dtof_init.sh to re-initialize GS1860
    print("\n=== Re-running dtof_init.sh ===")
    out = run(board, "cd /opt/sample/dtof && sh ./dtof_init.sh 2>&1; echo 'dtof_init done'", timeout=30)
    print(out.strip())

    # 5. Start binary fresh
    print("\n=== Starting binary (mode 3) ===")
    out = run(board, "cd /opt/sample/dtof && "
                     "(sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 2>&1) > /tmp/mode3_fix.log 2>&1 & "
                     "echo PID=$!")
    print(out.strip())
    new_pid = None
    for line in out.strip().split('\n'):
        if 'PID=' in line:
            try:
                new_pid = int(line.split('PID=')[1].strip())
            except:
                pass
    print(f"New PID: {new_pid}")

    # 6. Wait 15 seconds and check log
    print("\n=== Waiting 15 sec for startup... ===")
    time.sleep(15)

    out = run(board, "head -30 /tmp/mode3_fix.log 2>/dev/null")
    print("=== Log head (30 lines) ===")
    print(out.strip()[:3000])

    # 7. Check if frames are coming in (no frame err? or int_cnt?)
    print("\n=== Tail of log ===")
    out = run(board, "tail -20 /tmp/mode3_fix.log 2>/dev/null")
    print(out.strip()[:2000])

    # 8. Count frame errors
    out = run(board, "grep -c 'frame err' /tmp/mode3_fix.log 2>/dev/null || echo '0'")
    print(f"\nFrame error count: {out.strip()}")

    # 9. Count frames received (if any success prints)
    out = run(board, "grep -c 'UdpSend\\|depth\\|distance\\|frame_cnt' /tmp/mode3_fix.log 2>/dev/null || echo '0'")
    print(f"Successful frame count: {out.strip()}")

    # 10. Check vi pipe 2 int_cnt
    out = run(board, "cat /proc/msp/vi 2>/dev/null | grep 'pipe 2\\|pipe2\\|int_cnt' | head -5 || echo 'no vi proc'")
    print(f"\nVI pipe 2 status: {out.strip()}")

    board.close()

if __name__ == "__main__":
    main()
