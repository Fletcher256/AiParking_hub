#!/usr/bin/env python3
"""Find GS1860 UDP destination port and check board's actual binary FDs."""
import paramiko

VM_HOST    = "192.168.137.100"
VM_USER    = "ebaina"
VM_PASS    = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SRC_BASE   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src"

def connect_vm():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def connect_board():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    vm = connect_vm()
    board = connect_board()

    # 1. Check actual binary pid's FDs (pid 1994, not shell 1992)
    print("=== Board: binary PID's FDs ===")
    rc, fds = run(board, "pid=$(ps | grep 'sample_dtof_os08a20 3' | grep -v grep | grep -v sh | awk '{print $1}' | head -1); "
                         "echo Binary_PID=$pid; ls -la /proc/$pid/fd/ 2>/dev/null; "
                         "wc -c /opt/sample/dtof/stream_chn0.h264 2>/dev/null")
    print(fds.strip())

    # 2. Search all dtof source for sendto / socket / port
    print("\n=== VM: ALL files with sendto ===")
    rc, sendto = run(vm, f"grep -rn 'sendto\\|socket(\\|AF_INET\\|SOCK_DGRAM' {SRC_BASE}/dtof/ 2>/dev/null | head -30")
    print(sendto.strip())

    # 3. Check DataProc.h or DataProc.c
    print("\n=== VM: DataProc files ===")
    rc, dp = run(vm, f"find {SRC_BASE} -name 'DataProc*' 2>/dev/null")
    print(dp.strip())

    # 4. Check the dtof subdirectory
    print("\n=== VM: dtof subdirectory contents ===")
    rc, ls = run(vm, f"ls {SRC_BASE}/dtof/dtof/ 2>/dev/null || ls {SRC_BASE}/dtof/ 2>/dev/null | head -20")
    print(ls.strip())

    # 5. Check all .c and .h files in dtof directory tree
    print("\n=== VM: All source files in dtof ===")
    rc, files = run(vm, f"find {SRC_BASE}/dtof -name '*.c' -o -name '*.h' 2>/dev/null | head -20")
    print(files.strip())

    # 6. Search ALL source files for sendto/UDP port
    print("\n=== VM: sendto in all dtof files ===")
    rc, all_sendto = run(vm, f"find {SRC_BASE}/dtof -name '*.c' | xargs grep -ln 'sendto\\|SOCK_DGRAM' 2>/dev/null")
    print(all_sendto.strip())

    # 7. Also check included libraries
    print("\n=== VM: included dtof library path ===")
    rc, lib = run(vm, f"find /home/ebaina/ZZIP -name '*dtof*' -o -name '*gs1860*' -o -name '*DataProc*' 2>/dev/null | grep -v '.o' | head -20")
    print(lib.strip())

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
