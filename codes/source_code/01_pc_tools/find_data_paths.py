#!/usr/bin/env python3
"""Find where H.264 file is written and what port dToF UDP sends to."""
import paramiko, socket, time, threading

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

    # 1. Check for H.264 files on board
    print("=== Board: H.264 files in /opt/sample/dtof/ ===")
    rc, ls = run(board, "ls -la /opt/sample/dtof/*.h264 /opt/sample/dtof/*.h265 /tmp/*.h264 /tmp/*.h265 2>/dev/null || echo 'none found'")
    print(ls.strip())

    # 2. Check all open files of the binary more carefully
    print("\n=== Board: all fd of sample_dtof ===")
    rc, fds = run(board, "pid=$(pgrep -f 'sample_dtof_os08a20' | grep -v grep | head -1); "
                         "echo pid=$pid; ls -la /proc/$pid/fd/ 2>/dev/null; "
                         "cat /proc/$pid/fdinfo/3 2>/dev/null || echo 'no fd3'")
    print(fds.strip())

    # 3. Read dtof_init.c or dtof_dumpraw.c for UDP port
    print("\n=== VM: dtof_init.c - UDP port/socket setup ===")
    rc, init = run(vm, f"find {SRC_BASE}/dtof -name '*.c' -o -name '*.h' | "
                       f"xargs grep -l 'socket\\|sendto\\|port' 2>/dev/null | head -5")
    print(f"Files with socket/port: {init.strip()}")

    # Read dtof_init.c
    rc, dtof_init = run(vm, f"grep -n 'socket\\|sendto\\|port\\|PORT\\|htons\\|bind\\|addr' "
                            f"{SRC_BASE}/dtof/dtof_init.c 2>/dev/null | head -30")
    print(f"\ndtof_init.c socket code:\n{dtof_init}")

    # 4. Check dtof_dumpraw.c for full UDP setup
    print("\n=== VM: dtof_dumpraw.c - full UDP code ===")
    rc, loc = run(vm, f"grep -n 'socket\\|sendto\\|port\\|bind\\|htons\\|inet_addr' "
                       f"{SRC_BASE}/dtof/dtof_dumpraw.c 2>/dev/null | head -20")
    print(loc)

    # Find and read the UDP init function
    rc, sock_func = run(vm, f"grep -n 'td_s32.*socket\\|static.*socket\\|udp_init\\|sock_init\\|send_init' "
                            f"{SRC_BASE}/dtof/dtof_dumpraw.c 2>/dev/null | head -5")
    print(f"\nSocket function: {sock_func.strip()}")

    # Read the full socket setup part
    rc, full = run(vm, f"sed -n '1,80p' {SRC_BASE}/dtof/dtof_dumpraw.c 2>/dev/null")
    print(f"\nFirst 80 lines of dtof_dumpraw.c:\n{full}")

    # 5. Check sample_comm_venc_start_get_stream signature
    print("\n=== VM: sample_comm_venc_start_get_stream signature ===")
    rc, sig = run(vm, f"grep -n 'sample_comm_venc_start_get_stream' "
                      f"{SRC_BASE}/common/sample_comm_venc.c | head -5")
    print(sig)
    if sig.strip():
        lnum = int(sig.strip().split('\n')[-1].split(':')[0])
        rc, func = run(vm, f"sed -n '{lnum},{lnum+20}p' {SRC_BASE}/common/sample_comm_venc.c")
        print(func)

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
