#!/usr/bin/env python3
"""
Listen for dToF UDP data on VM port 2368 from board 192.168.137.2.
Also check board log and dtof_init status.
"""
import paramiko
import socket
import threading
import time
import struct

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

DTOF_PORT = 2368  # 0x0940 from disassembly

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

    # 1. Check board log for dtof status
    print("=== Board log tail ===")
    out = run(board, "tail -30 /tmp/mode3_fix.log 2>/dev/null || tail -30 /tmp/dtof.log 2>/dev/null", timeout=10)
    print(out.strip()[:2000])

    # 2. Check if GS1860 pipe is actually running
    print("\n=== Board: GS1860 vi_pipe status ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -30 || echo 'no vi proc'", timeout=10)
    print(out.strip()[:1000])

    # 3. Check binary pid and what it's doing
    print("\n=== Board: binary PID status ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep | head -5", timeout=10)
    print(out.strip())

    # 4. Try Python UDP listen on port 2368 (via SSH to VM) - background
    print(f"\n=== VM: Python UDP listener on port {DTOF_PORT} (5 sec) ===")
    listen_cmd = f"""python3 -c "
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', {DTOF_PORT}))
s.settimeout(1)
count = 0
start = time.time()
while time.time() - start < 5:
    try:
        data, addr = s.recvfrom(65535)
        count += 1
        print(f'PKT from {{addr}}: {{len(data)}} bytes')
        if count >= 5:
            break
    except socket.timeout:
        pass
print(f'Total packets: {{count}}')
s.close()
" 2>&1"""
    out = run(vm, listen_cmd, timeout=10)
    print(out.strip())

    # 5. Also try port 9001, 9000, 8080, 5000 in case port calc was wrong
    for port in [9001, 9000, 8001, 5000, 7788, 37020, 43334, 1234, 65535, 16393]:
        print(f"\n=== VM: Quick listen port {port} (2 sec) ===")
        cmd = f"""python3 -c "
import socket, time
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', {port}))
    s.settimeout(0.5)
    count = 0
    start = time.time()
    while time.time() - start < 2:
        try:
            data, addr = s.recvfrom(65535)
            count += 1
            print(f'PKT from {{addr}}: {{len(data)}} bytes')
        except socket.timeout:
            pass
    print(f'port {port}: {{count}} pkts')
    s.close()
except Exception as e:
    print(f'port {port}: error {{e}}')
" 2>&1"""
        out = run(vm, cmd, timeout=5)
        print(out.strip())
        if "PKT from" in out:
            print(f"*** FOUND DATA ON PORT {port} ***")
            break

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
