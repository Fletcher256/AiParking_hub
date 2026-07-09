#!/usr/bin/env python3
"""Check the full dtof.log to see what happens after the 92 I2C errors."""
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

    print("=== 进程状态 ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep"))

    print("=== dtof.log 总行数 ===")
    print(run(board, "wc -l /tmp/dtof.log 2>/dev/null"))

    print("=== dtof.log 第90行之后的内容（I2C错误之后） ===")
    print(run(board, "tail -n +90 /tmp/dtof.log 2>/dev/null | head -80"))

    print("=== 非I2C_WRITE行（关键状态信息） ===")
    print(run(board, "grep -v 'I2C_WRITE' /tmp/dtof.log 2>/dev/null | head -40"))

    print("=== dtof.log 最后30行 ===")
    print(run(board, "tail -30 /tmp/dtof.log 2>/dev/null"))

    # Also check if binary is outputting anything now (live)
    print("=== 等3秒后再看日志是否在增长 ===")
    lines1 = run(board, "wc -l /tmp/dtof.log 2>/dev/null").strip()
    time.sleep(3)
    lines2 = run(board, "wc -l /tmp/dtof.log 2>/dev/null").strip()
    print(f"Before: {lines1}, After 3s: {lines2}")
    if lines1 != lines2:
        print(">>> 日志在增长！二进制正在运行中")
    else:
        print(">>> 日志没有增长（可能block buffering，或已停止）")

    # Check if there's any network activity on 2368
    print("\n=== 检查是否有UDP端口2368的网络活动 ===")
    print(run(board, "netstat -un 2>/dev/null | grep 2368 || ss -un 2>/dev/null | grep 2368 || echo 'no netstat/ss'"))

    board.close()

if __name__ == "__main__":
    main()
