#!/usr/bin/env python3
"""Find GS1860 UDP destination port from source code."""
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

    # 1. Find all dtof source files
    print("=== dtof source files ===")
    rc, files = run(vm, f"find {SRC_BASE}/dtof -name '*.c' -o -name '*.h' 2>/dev/null | sort")
    print(files.strip())

    # 2. Search for sendto in ALL files under src/
    print("\n=== sendto grep ===")
    rc, sendto = run(vm, f"grep -rn 'sendto' {SRC_BASE}/ --include='*.c' --include='*.h' 2>/dev/null")
    print(sendto.strip()[:2000])

    # 3. Search for htons (port encoding)
    print("\n=== htons grep ===")
    rc, htons = run(vm, f"grep -rn 'htons' {SRC_BASE}/ --include='*.c' --include='*.h' 2>/dev/null")
    print(htons.strip()[:2000])

    # 4. Search for inet_addr (IP address)
    print("\n=== inet_addr grep ===")
    rc, inet = run(vm, f"grep -rn 'inet_addr' {SRC_BASE}/ --include='*.c' --include='*.h' 2>/dev/null")
    print(inet.strip()[:2000])

    # 5. Search for SOCK_DGRAM
    print("\n=== SOCK_DGRAM grep ===")
    rc, sock = run(vm, f"grep -rn 'SOCK_DGRAM' {SRC_BASE}/ --include='*.c' --include='*.h' 2>/dev/null")
    print(sock.strip()[:2000])

    # 6. Check dtof_dumpraw.c content
    print("\n=== dtof_dumpraw.c (if exists) ===")
    rc, dr = run(vm, f"cat {SRC_BASE}/dtof/dtof_dumpraw.c 2>/dev/null | head -100")
    print(dr.strip()[:3000])

    # 7. Check dtof_init.c content for UDP setup
    print("\n=== dtof_init.c snippet ===")
    rc, di = run(vm, f"grep -n 'socket\\|port\\|udp\\|send\\|addr' {SRC_BASE}/dtof/dtof_init.c 2>/dev/null | head -30")
    print(di.strip())

    # 8. Board: check with ss command if available
    print("\n=== Board: ss -unp or netstat ===")
    rc, ss_out = run(board, "ss -unp 2>/dev/null || netstat -unp 2>/dev/null || echo 'neither available'", timeout=10)
    print(ss_out.strip()[:1000])

    # 9. Board: check binary actual pid fd (more carefully)
    print("\n=== Board: binary pid and fds ===")
    rc, fds = run(board, "pid=$(ps aux 2>/dev/null | grep 'sample_dtof_os08a20 3' | grep -v grep | awk '{print $1}' | head -1); "
                         "[ -z $pid ] && pid=$(ps | grep 'sample_dtof_os08a20 3' | grep -v grep | awk '{print $1}' | head -1); "
                         "echo Binary_PID=$pid; "
                         "ls -la /proc/$pid/fd/ 2>/dev/null | head -20")
    print(fds.strip())

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
