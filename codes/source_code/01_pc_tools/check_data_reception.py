#!/usr/bin/env python3
"""Check if both data streams are reachable on VM side."""
import paramiko, time, subprocess

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
    board = connect_board()
    vm = connect_vm()

    # 1. Board: binary status
    print("=== Board: binary running? ===")
    rc, ps = run(board, "ps | grep sample_dtof | grep -v grep || echo NONE")
    print(ps.strip())

    # 2. Board: what network connections does the binary have?
    print("\n=== Board: network connections of sample_dtof ===")
    rc, netstat = run(board, "pid=$(pgrep -f sample_dtof_os08a20 | head -1); "
                             "netstat -tunp 2>/dev/null | grep $pid || echo 'none / netstat N/A'")
    print(netstat.strip())

    # 3. Board: check what ports/sockets the binary uses
    print("\n=== Board: /proc/<pid>/net/udp ===")
    rc, udp = run(board, "cat /proc/net/udp 2>/dev/null | head -10")
    print(udp.strip())

    # 4. Check what dtof_init does with server_ip (look for UDP send)
    print("\n=== Board: dmesg/log for UDP/network activity ===")
    rc, log = run(board, "cat /tmp/dtof.log 2>/dev/null | head -20 || cat /tmp/mode3_fix.log 2>/dev/null | head -20 || echo 'no log'")
    print(log.strip())

    # 5. VM: check if any UDP packets arriving from board
    print("\n=== VM: listening UDP ports ===")
    rc, vm_udp = run(vm, "ss -ulnp 2>/dev/null | head -20 || netstat -ulnp 2>/dev/null | head -20")
    print(vm_udp.strip())

    # 6. VM: check for any existing dtof receiver process
    print("\n=== VM: dtof-related processes ===")
    rc, vm_ps = run(vm, "ps aux | grep -i 'dtof\\|depth\\|lidar\\|udp' | grep -v grep || echo 'none'")
    print(vm_ps.strip())

    # 7. Check what port GS1860 sends UDP to - look at dtof source
    print("\n=== VM: dtof source - what port does it send UDP to? ===")
    rc, port = run(vm, "grep -rn 'UDP\\|udp\\|port\\|PORT\\|send\\|sock' "
                       "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/ "
                       "--include='*.c' --include='*.h' 2>/dev/null | "
                       "grep -i 'port\\|udp\\|send' | grep -v 'sample_dtof.c' | head -20")
    print(port.strip())

    # 8. Check sample_comm_venc.c to understand what get_stream thread does
    print("\n=== VM: sample_comm_venc_get_stream behavior ===")
    rc, venc_src = run(vm, "grep -n 'get_stream\\|write\\|send\\|fwrite\\|fopen\\|socket' "
                           "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_venc.c "
                           "2>/dev/null | head -30")
    print(venc_src.strip())

    board.close()
    vm.close()

if __name__ == "__main__":
    main()
