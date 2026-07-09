#!/usr/bin/env python3
"""Read GS1860 sensor driver source to understand init sequence."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src"
INCLUDE = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/include"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # 1. Find gs1860_cmos.h
    print("=== find gs1860_cmos.h ===")
    out = run(vm, f"find /home/ebaina/ZZIP -name 'gs1860*' 2>/dev/null")
    print(out.strip())

    # 2. Read gs1860_cmos.h (should have I2C address and init sequence)
    gs1860_h = f"{INCLUDE}/3rdparty/dtof/gs1860_cmos.h"
    print(f"\n=== gs1860_cmos.h ({gs1860_h}) ===")
    out = run(vm, f"cat {gs1860_h} 2>/dev/null | head -100")
    print(out.strip()[:3000])

    # 3. Find gs1860_cmos.c or any other GS1860 source
    print("\n=== find gs1860 source ===")
    out = run(vm, "find /home/ebaina/ZZIP -name 'gs1860*' 2>/dev/null | grep -E '\\.c|\\.h'")
    print(out.strip())

    # 4. Look for I2C address in GS1860 library
    print("\n=== strings libsns_gs1860.a | grep addr ===")
    out = run(vm, f"strings /home/ebaina/ZZIP/SS928V100_dtof_build_source/lib/linux/hisilicon/libsns_gs1860.a 2>/dev/null | grep -iE 'addr|i2c|0x2|0x1' | head -20")
    print(out.strip())

    # 5. Look for sample_dtof.c where sensor is initialized
    print("\n=== sample_dtof.c: GS1860 init sequence ===")
    out = run(vm, f"grep -n 'dtof\\|gs1860\\|sensor_num.*2\\|vi_pipe.*2\\|sleep\\|usleep' {SRC}/dtof/sample_dtof.c 2>/dev/null | head -40")
    print(out.strip())

    # 6. Read the key function in sample_dtof.c
    print("\n=== sample_dtof_dtof_and_rgb function ===")
    out = run(vm, f"grep -n 'sample_dtof_dtof_and_rgb' {SRC}/dtof/sample_dtof.c")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+80}p' {SRC}/dtof/sample_dtof.c")
        print(out2.strip()[:3000])

    # 7. Read sample_dtof_one_dtof_sensor
    print("\n=== sample_dtof_one_dtof_sensor function ===")
    out = run(vm, f"grep -n 'sample_dtof_one_dtof_sensor' {SRC}/dtof/sample_dtof.c | head -5")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+60}p' {SRC}/dtof/sample_dtof.c")
        print(out2.strip()[:2000])

    vm.close()

if __name__ == "__main__":
    main()
