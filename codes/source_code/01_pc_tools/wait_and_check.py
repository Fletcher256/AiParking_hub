#!/usr/bin/env python3
"""Wait for binary to produce output and check if our sleep patch worked."""
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
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    board = connect()

    # Force flush by checking current state
    for i in range(8):
        ps = run(board, "ps | grep sample_dtof | grep -v grep | head -2")
        log_lines = run(board, "wc -l /tmp/dtof.log 2>/dev/null").strip()
        log_size = run(board, "wc -c /tmp/dtof.log 2>/dev/null").strip()
        print(f"  t+{i*5}s: PID={ps.strip()}, log={log_lines}, size={log_size}")
        time.sleep(5)

    print("\n=== Full log content ===")
    log = run(board, "cat /tmp/dtof.log 2>/dev/null")
    print(log[:6000])

    print("\n=== Key analysis ===")
    has_sleep_msg = "waiting 10s" in log or "HW reset recovery" in log
    has_i2c_errors = "I2C_WRITE error" in log
    has_dtof_init = "DtofInit success" in log
    has_frame_err = "frame err" in log
    has_dtof_start = "Dtof start" in log or "Dtof Start" in log

    print(f"Sleep message appeared: {has_sleep_msg}")
    print(f"I2C errors: {log.count('I2C_WRITE error')} total")
    print(f"DtofInit success: {has_dtof_init}")
    print(f"Frame errors: {has_frame_err}")
    print(f"Dtof start: {has_dtof_start}")

    # Force a manual stdout flush by sending SIGUSR1 or checking /proc
    print("\n=== /proc/PID/fd to check stdout ===")
    pid_out = run(board, "pgrep sample_dtof 2>/dev/null")
    if pid_out.strip():
        pid = pid_out.strip().split('\n')[0]
        print(f"PID: {pid}")
        out = run(board, f"cat /proc/{pid}/fdinfo/1 2>/dev/null | head -5")
        print(out)

    board.close()

if __name__ == "__main__":
    main()
