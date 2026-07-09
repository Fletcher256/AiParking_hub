#!/usr/bin/env python3
"""Check sensor_global_init more carefully."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
OBJDUMP = "aarch64-mix210-linux-objdump"
NM = "aarch64-mix210-linux-nm"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # Check files exist
    print("=== Files in /tmp/gs1860_disasm/ ===")
    out = run(vm, "ls -lh /tmp/gs1860_disasm/")
    print(out.strip())

    # Try disassembling with verbose
    print("\n=== objdump version ===")
    out = run(vm, f"{OBJDUMP} --version 2>&1 | head -3")
    print(out.strip())

    # Try disassembly directly
    print("\n=== Disassemble gs1860_cmos.o (first 100 lines) ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_cmos.o 2>&1 | head -100")
    print(out)

    # Try with -D (disassemble all sections including data)
    print("\n=== gs1860_cmos.o sections ===")
    out = run(vm, f"{OBJDUMP} -h /tmp/gs1860_disasm/gs1860_cmos.o 2>&1 | head -50")
    print(out)

    # NM with demangling
    print("\n=== nm -C gs1860_cmos.o ===")
    out = run(vm, f"{NM} -C /tmp/gs1860_disasm/gs1860_cmos.o 2>&1 | head -30")
    print(out)

    # Try sensor_ctl.o
    print("\n=== Disassemble gs1860_sensor_ctl.o ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_sensor_ctl.o 2>&1 | head -200")
    print(out)

    # Check if the binary has sensor_global_init in it (since it's statically linked)
    BINARY = "/opt/sample/dtof/sample_dtof"
    print("\n=== Check if board binary has sensor_global_init ===")
    # We'd need to access board for this. Let's check the built binary on VM instead.
    BIN_VM = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
    out = run(vm, f"{NM} {BIN_VM} 2>/dev/null | grep -iE 'global_init|sensor_global' | head -10")
    print(out.strip() or "(stripped binary - no symbols)")

    # Disassemble the full binary and look for gpio/usleep patterns
    print("\n=== Disassemble binary - look for usleep/gpio calls ===")
    out = run(vm, f"{OBJDUMP} -d {BIN_VM} 2>/dev/null | grep -i 'usleep\\|gpio\\|sleep' | head -20")
    print(out.strip() or "(none found in disassembly)")

    # Check strings in binary for GPIO paths
    print("\n=== Strings in sample_dtof binary ===")
    out = run(vm, f"strings {BIN_VM} 2>/dev/null | grep -iE 'gpio|96|/sys/class|export|direction|value|usleep' | head -20")
    print(out.strip() or "(none found)")

    vm.close()

if __name__ == "__main__":
    main()
