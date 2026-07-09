#!/usr/bin/env python3
"""Check where H.264 is written and what port GS1860 sends UDP to."""
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

    # 1. Find GS1860 UDP port in dtof_dumpraw.c
    print("=== GS1860 UDP port/address ===")
    rc, port = run(vm, f"grep -n 'port\\|PORT\\|htons\\|addr\\|sendto\\|socket' "
                       f"{SRC_BASE}/dtof/dtof_dumpraw.c | head -30")
    print(port)

    # 2. Find sample_comm_venc_get_stream_proc to see file writing
    print("\n=== sample_comm_venc_get_stream_proc (what file is written) ===")
    rc, venc = run(vm, f"grep -n 'sample_comm_venc_get_venc_stream_proc\\|get_venc_stream_proc\\|fopen\\|stream_chn\\|h264\\|h265\\|hevc' "
                       f"{SRC_BASE}/common/sample_comm_venc.c | head -20")
    print(venc)

    # Find the actual stream proc function
    rc, loc = run(vm, f"grep -n 'sample_comm_venc_get_venc_stream_proc' {SRC_BASE}/common/sample_comm_venc.c | head -5")
    print(f"\nFunction locations: {loc.strip()}")
    if loc.strip():
        lnum = int(loc.strip().split('\n')[0].split(':')[0])
        rc, func = run(vm, f"sed -n '{lnum},{lnum+60}p' {SRC_BASE}/common/sample_comm_venc.c")
        print(f"\nFunction body:\n{func}")

    # 3. Board: check what files the binary has open (for H.264 output)
    print("\n=== Board: files open by sample_dtof_os08a20 ===")
    rc, fds = run(board, "pid=$(pgrep -f sample_dtof_os08a20 | head -1); "
                         "ls -la /proc/$pid/fd 2>/dev/null | grep -v 'pipe\\|socket\\|anon' | head -20 || "
                         "echo 'Cannot list fds'")
    print(fds.strip())

    # 4. Board: check UDP sockets in hex
    print("\n=== Board: UDP sockets (hex decode) ===")
    rc, udp = run(board, "cat /proc/net/udp 2>/dev/null")
    print(udp.strip())
    # Decode ports:
    # 0xA946 = 43334
    # 0x909C = 37020
    print("Decoded: 0xA946=43334, 0x909C=37020")

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
