#!/usr/bin/env python3
"""Find UdpSend library and the actual UDP port used."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src"
ZZIP = "/home/ebaina/ZZIP/SS928V100_dtof_build_source"

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

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()
    board = connect_board()

    # 1. Check dtof Makefile for link libraries
    print("=== dtof Makefile - LIBS ===")
    out = run(vm, f"grep -n 'UdpSend\\|udpsend\\|udp_send\\|LIBS\\|lib' {SRC}/dtof/Makefile 2>/dev/null | head -30")
    print(out.strip())

    # 2. Find any library with UdpSend symbol
    print("\n=== find libraries with UdpSendInit symbol ===")
    out = run(vm, f"find {ZZIP} -name '*.a' -o -name '*.so' 2>/dev/null | "
                  f"xargs -I{{}} sh -c 'nm {{}} 2>/dev/null | grep -i udpsend && echo FILE:{{}}' | head -30", timeout=30)
    print(out.strip())

    # 3. Find any .a with UdpSend (alternative approach)
    print("\n=== nm all .a files ===")
    out = run(vm, f"find {ZZIP}/lib -name '*.a' | while read f; do "
                  f"result=$(nm $f 2>/dev/null | grep -i 'UdpSend'); "
                  f"[ -n \"$result\" ] && echo \"$f: $result\"; done", timeout=30)
    print(out.strip())

    # 4. Find any .so with UdpSend
    print("\n=== nm all .so files ===")
    out = run(vm, f"find {ZZIP}/lib -name '*.so' | while read f; do "
                  f"result=$(nm $f 2>/dev/null | grep -i 'UdpSend'); "
                  f"[ -n \"$result\" ] && echo \"$f: $result\"; done", timeout=30)
    print(out.strip())

    # 5. Check 3rdparty directory
    print("\n=== 3rdparty directory ===")
    out = run(vm, f"ls -la {ZZIP}/lib/linux/hisilicon/ 2>/dev/null | grep -i 'dtof\\|tof\\|gs1860\\|udp'")
    print(out.strip())
    out2 = run(vm, f"find {ZZIP} -name '*.a' 2>/dev/null | grep -i 'dtof\\|tof\\|gs1860'")
    print(out2.strip())

    # 6. Read the full dtof Makefile
    print("\n=== Full dtof Makefile ===")
    out = run(vm, f"cat {SRC}/dtof/Makefile 2>/dev/null")
    print(out.strip())

    # 7. Board: strings on the binary to find port number
    print("\n=== Board: strings | grep port (in binary) ===")
    out = run(board, "strings /opt/sample/dtof/sample_dtof_os08a20 | grep -i 'port\\|PORT\\|udp\\|send\\|socket' | head -20", timeout=15)
    print(out.strip())

    # 8. Board: strings to find any IP/port string
    print("\n=== Board: strings binary for numbers that look like ports ===")
    out = run(board, "strings /opt/sample/dtof/sample_dtof_os08a20 | grep -E '^[0-9]{4,5}$' | head -30", timeout=15)
    print(out.strip())

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
