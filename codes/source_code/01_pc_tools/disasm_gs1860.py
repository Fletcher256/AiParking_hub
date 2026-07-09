#!/usr/bin/env python3
"""Disassemble pfn_cmos_sensor_global_init from libsns_gs1860.a to understand GPIO96 handling."""
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

    # List object files in library
    print("=== Object files in libsns_gs1860.a ===")
    out = run(vm, f"ar t {LIB}")
    print(out.strip())

    # List all symbols
    print("\n=== All symbols (nm) ===")
    out = run(vm, f"nm {LIB} 2>/dev/null | head -50")
    print(out.strip())

    # Look for global_init, gpio, sleep related symbols
    print("\n=== Symbols with global_init/gpio/sleep/delay/reset ===")
    out = run(vm, f"nm {LIB} 2>/dev/null | grep -iE 'global_init|gpio|sleep|delay|reset|usleep|nanosleep'")
    print(out.strip() or "(none found)")

    # Extract the library to /tmp and disassemble
    print("\n=== Extracting library to /tmp/gs1860_disasm/ ===")
    out = run(vm, "mkdir -p /tmp/gs1860_disasm && cd /tmp/gs1860_disasm && ar x " + LIB + " && ls -la")
    print(out.strip())

    # List extracted files
    out = run(vm, "ls /tmp/gs1860_disasm/")
    print(f"Files: {out.strip()}")

    # Disassemble each object file, look for gpio and sleep patterns
    obj_files = [f.strip() for f in out.strip().split('\n') if f.strip().endswith('.o')]
    print(f"\n=== Disassembling {len(obj_files)} object file(s) ===")

    for obj in obj_files:
        objpath = f"/tmp/gs1860_disasm/{obj}"
        print(f"\n--- {obj} ---")

        # Get symbols in this object file
        syms = run(vm, f"nm {objpath} 2>/dev/null | grep -iE 'cmos|gpio|global'")
        print(f"Symbols: {syms.strip() or '(none of interest)'}")

        # Disassemble and look for bl calls (function calls) and sleep/delay patterns
        # Also look for gpio write patterns
        disasm = run(vm, f"{OBJDUMP} -d {objpath} 2>/dev/null | head -300")
        print(disasm[:5000])

        # Look specifically for strings (to find "gpio" paths etc.)
        strings_out = run(vm, f"strings {objpath} 2>/dev/null | grep -iE 'gpio|sleep|delay|reset|usleep|I2C|value|direction|export|96'")
        if strings_out.strip():
            print(f"Strings: {strings_out.strip()}")

    vm.close()

if __name__ == "__main__":
    main()
