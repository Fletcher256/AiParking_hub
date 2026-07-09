#!/usr/bin/env python3
"""
Disassemble sensor_global_init and pfn_cmos_init from libsns_gs1860.a.
Key question: what does sensor_global_init do? Does it have delays?
Also: examine vi start sequence timing vs i2c init.
"""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
LIB = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/lib/linux/hisilicon/libsns_gs1860.a"
OBJDUMP = "aarch64-mix210-linux-objdump"

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

    # Full disassembly of gs1860_cmos.o - looking for sensor_global_init
    print("=== Full disassembly of gs1860_cmos.o ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_cmos.o 2>/dev/null | grep -A 200 '<sensor_global_init>'")
    print(out[:8000])

    # Also look for any references to usleep in disassembly
    print("\n=== usleep references in gs1860_cmos.o ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_cmos.o 2>/dev/null | grep -i 'usleep\\|sleep\\|delay'")
    print(out.strip() or "(none found)")

    # Disassembly of gs1860_sensor_ctl.o - looking for usleep usage
    print("\n=== gs1860_sensor_ctl.o - full disassembly (looking for usleep) ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_sensor_ctl.o 2>/dev/null | head -200")
    print(out[:5000])

    # Look for all strings in gs1860_cmos.o
    print("\n=== All strings in gs1860_cmos.o ===")
    out = run(vm, "strings /tmp/gs1860_disasm/gs1860_cmos.o 2>/dev/null | head -50")
    print(out.strip())

    # Check gs1860_write_register in sensor_ctl
    print("\n=== gs1860_write_register disassembly ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_sensor_ctl.o 2>/dev/null | grep -A 80 '<gs1860_write_register>'")
    print(out[:5000])

    # Check what functions call usleep in sensor_ctl
    print("\n=== Functions calling usleep in sensor_ctl ===")
    out = run(vm, f"{OBJDUMP} -d /tmp/gs1860_disasm/gs1860_sensor_ctl.o 2>/dev/null")
    # Print full disassembly of sensor_ctl.o (it's smaller)
    print(out[:8000])

    vm.close()

if __name__ == "__main__":
    main()
