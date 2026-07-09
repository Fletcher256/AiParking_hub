#!/usr/bin/env python3
"""Find DataProc.h and check what port GS1860 sends to; also sniff on VM."""
import paramiko

VM_HOST    = "192.168.137.100"
VM_USER    = "ebaina"
VM_PASS    = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

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

    # 1. Find DataProc.h on VM
    print("=== VM: find DataProc.h ===")
    rc, dp = run(vm, "find /home/ebaina/ZZIP -name 'DataProc.h' 2>/dev/null")
    print(dp.strip())

    # 2. Read DataProc.h if found
    if dp.strip():
        path = dp.strip().split('\n')[0]
        print(f"\n=== VM: DataProc.h content ({path}) ===")
        rc, content = run(vm, f"cat {path} 2>/dev/null")
        print(content[:5000])

    # 3. Find DataProc.c or DataProc.cpp
    print("\n=== VM: find DataProc.c / .cpp ===")
    rc, dpc = run(vm, "find /home/ebaina/ZZIP -name 'DataProc.c' -o -name 'DataProc.cpp' 2>/dev/null")
    print(dpc.strip())
    if dpc.strip():
        path = dpc.strip().split('\n')[0]
        rc, content = run(vm, f"grep -n 'htons\\|port\\|PORT\\|sendto\\|inet_addr\\|socket' {path} 2>/dev/null | head -30")
        print(content[:2000])

    # 4. Find any .so or .a library related to dtof/DataProc
    print("\n=== VM: find dtof/DataProc library ===")
    rc, lib = run(vm, "find /home/ebaina/ZZIP -name '*.a' -o -name '*.so' 2>/dev/null | grep -v __pycache__ | grep -i 'dtof\\|dataproc\\|gs1860\\|tof' | head -20")
    print(lib.strip())

    # 5. Find include path with DataProc.h
    print("\n=== VM: find any DataProc.h in include paths ===")
    rc, inc = run(vm, "find /home/ebaina/ZZIP -path '*/dtof/DataProc.h' 2>/dev/null")
    print(inc.strip())
    if inc.strip():
        path = inc.strip().split('\n')[0]
        rc, content = run(vm, f"cat {path} 2>/dev/null")
        print(content[:5000])

    # 6. Board: look for port in dtof.ini (config file)
    print("\n=== Board: dtof.ini ===")
    rc, ini = run(board, "cat /opt/sample/dtof/dtof.ini 2>/dev/null || echo 'no dtof.ini'")
    print(ini.strip())

    # 7. Board: check dmesg for any network/port setup messages
    print("\n=== Board: mode3 log (dtof UDP messages) ===")
    rc, log = run(board, "cat /tmp/mode3_fix.log 2>/dev/null | grep -i 'udp\\|port\\|send\\|socket\\|addr\\|192.168' | head -20")
    print(log.strip())

    # 8. Board: use tcpdump to see what udp goes out (3 sec)
    print("\n=== Board: tcpdump (if available) ===")
    rc, tcp = run(board, "which tcpdump 2>/dev/null || echo 'no tcpdump'")
    print("tcpdump:", tcp.strip())

    # 9. VM: check if anything comes from board
    print("\n=== VM: ss -unp (listening UDP) ===")
    rc, ss = run(vm, "ss -ulnp 2>/dev/null | head -20")
    print(ss.strip())

    # 10. Read the dtof.ini path from source to find the config key for port
    print("\n=== VM: dtof_init.c - full file ===")
    SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src"
    rc, init = run(vm, f"cat {SRC}/dtof/dtof_init.c 2>/dev/null | head -150")
    print(init.strip()[:5000])

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
