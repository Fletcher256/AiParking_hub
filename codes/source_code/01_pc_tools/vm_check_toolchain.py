#!/usr/bin/env python3
"""Check toolchain structure and find correct gcc binary."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Check toolchain dir
    print("=== Toolchain contents ===")
    rc, out = run(c, "ls /opt/linux/x86-arm/aarch64-mix210-linux/host_bin/ | grep gcc | head -10")
    print(out.strip())

    # Try to run it directly
    print("\n=== Test direct path ===")
    rc, out = run(c, "/opt/linux/x86-arm/aarch64-mix210-linux/host_bin/aarch64-mix210-linux-gcc --version 2>&1 || echo 'FAILED'")
    print(out.strip())

    # Check what symlinks exist
    print("\n=== All gcc-like files ===")
    rc, out2 = run(c, "ls /opt/linux/x86-arm/aarch64-mix210-linux/host_bin/*gcc* 2>/dev/null | head -10")
    print(out2.strip())

    # Check if there's a env setup script or .bashrc that sets PATH
    print("\n=== .bashrc / .profile PATH settings ===")
    rc, out3 = run(c, "cat /home/ebaina/.bashrc 2>/dev/null | grep -i 'path\\|opt\\|toolchain\\|cross'")
    print(out3.strip())
    rc, out4 = run(c, "cat /home/ebaina/.profile 2>/dev/null | grep -i 'path\\|opt\\|toolchain\\|cross'")
    print(out4.strip())

    # Try bash -l to source .bashrc
    print("\n=== Try bash -l to get full env ===")
    rc, out5 = run(c, "bash -l -c 'which aarch64-mix210-linux-gcc 2>/dev/null || echo NOT_FOUND'")
    print(out5.strip())

    # Previous build succeeded at some point - check git log or recent build history
    print("\n=== How was previous binary built? (check .bash_history) ===")
    rc, hist = run(c, "grep -i 'make\\|gcc\\|build' /home/ebaina/.bash_history 2>/dev/null | tail -20")
    print(hist.strip())

    c.close()

if __name__ == "__main__":
    main()
