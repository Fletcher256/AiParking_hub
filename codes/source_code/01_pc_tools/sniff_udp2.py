#!/usr/bin/env python3
"""Find UDP port via sudo tcpdump or objdump disassembly."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"

def connect_vm():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def run_sudo(c, cmd, timeout=15):
    """Run with sudo using password via stdin."""
    _, stdout, stderr = c.exec_command(f"echo '{VM_PASS}' | sudo -S {cmd} 2>&1", timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()

    # 1. Try sudo tcpdump (8 seconds)
    print("=== VM: sudo tcpdump ens37 for UDP from board (8 sec) ===")
    out = run_sudo(vm, "timeout 8 tcpdump -i ens37 -n 'udp and src host 192.168.137.2' -c 20", timeout=15)
    print(out[:3000])

    # 2. Use aarch64 objdump (from toolchain) on udp_client.o
    print("\n=== VM: aarch64 objdump on udp_client.o ===")
    out = run(vm, "which aarch64-mix210-linux-objdump 2>/dev/null || "
                  "find /opt/linux -name 'aarch64*objdump' 2>/dev/null | head -3",
              timeout=10)
    print("objdump path:", out.strip())

    # Use the cross objdump
    out = run(vm, "source ~/.bashrc 2>/dev/null; "
                  "aarch64-mix210-linux-objdump -d /tmp/udp_client.o 2>/dev/null | head -150",
              timeout=15)
    print(out[:5000])

    # 3. Try login shell for objdump
    print("\n=== VM: bash -l objdump ===")
    out = run(vm, "bash -l -c 'aarch64-mix210-linux-objdump -d /tmp/udp_client.o 2>/dev/null | head -150'",
              timeout=15)
    print(out[:5000])

    # 4. hexdump the udp_client.o to find htons constants
    print("\n=== VM: hexdump .rodata from udp_client.o ===")
    out = run(vm, "objdump -s -j .rodata /tmp/udp_client.o 2>/dev/null || "
                  "readelf -x .rodata /tmp/udp_client.o 2>/dev/null", timeout=10)
    print(out[:2000])

    # 5. strings on udp_client.o (more verbose)
    print("\n=== VM: strings -n 3 on udp_client.o ===")
    out = run(vm, "strings -n 3 /tmp/udp_client.o 2>/dev/null")
    print(out.strip())

    # 6. Check if board sends to a specific port using /proc/net/udp6
    print("\n=== VM: all listening ports on VM ===")
    out = run(vm, "ss -unlp 2>/dev/null; echo '---'; ss -unlp6 2>/dev/null")
    print(out.strip())

    vm.close()

if __name__ == "__main__":
    main()
