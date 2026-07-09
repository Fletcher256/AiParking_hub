#!/usr/bin/env python3
"""Sniff UDP packets from board on VM, and disassemble udp_client.o."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
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
    return out + err

def main():
    vm = connect_vm()
    board = connect_board()

    # 1. Use tcpdump on VM to capture UDP from board (5 seconds)
    print("=== VM: tcpdump UDP from board (5 sec) ===")
    # Start tcpdump in background, then read result
    _, stdout, stderr = vm.exec_command(
        "timeout 5 tcpdump -i any -n udp src 192.168.137.2 -c 10 2>&1 || "
        "timeout 5 tcpdump -i eth0 -n udp src 192.168.137.2 -c 10 2>&1 || "
        "timeout 5 tcpdump -i ens33 -n udp src 192.168.137.2 -c 10 2>&1",
        timeout=10)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out[:2000])
    print("err:", err[:500])

    # 2. Check network interfaces on VM
    print("\n=== VM: network interfaces ===")
    out = run(vm, "ip link show | grep -E '^[0-9]|inet '")
    print(out.strip())

    # 3. Get IP of adapter connected to board network
    print("\n=== VM: IP on 192.168.137.x network ===")
    out = run(vm, "ip addr show | grep '192.168.137'")
    print(out.strip())

    # 4. Proper tcpdump on the correct interface
    print("\n=== VM: find interface for 192.168.137.100 ===")
    out = run(vm, "ip route | grep '192.168.137'")
    print(out.strip())

    iface = "ens33"  # Will adjust based on above
    print(f"\n=== VM: tcpdump on {iface} for UDP from board (8 sec) ===")
    _, stdout, stderr = vm.exec_command(
        f"timeout 8 tcpdump -i {iface} -n 'udp and src host 192.168.137.2' -c 20 2>&1",
        timeout=12)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out[:3000])
    print("err:", err[:200])

    # 5. objdump on udp_client.o (should be in /tmp from previous script)
    print("\n=== VM: objdump -d /tmp/udp_client.o ===")
    out = run(vm, "objdump -d /tmp/udp_client.o 2>/dev/null | head -100")
    print(out.strip()[:3000])

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
