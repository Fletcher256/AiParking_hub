#!/usr/bin/env python3
"""Read sample_comm_vi_start_vi to understand the dev/isp split and where to add sleep."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
VI_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    vm = connect()

    # Find sample_comm_vi_start_vi line number
    print("=== sample_comm_vi_start_vi location ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start_vi\\|sample_comm_vi_start_dev\\|sample_comm_vi_start_pipe\\|sample_comm_vi_start_isp' {VI_COMMON} | head -30")
    print(out.strip())

    # Find the function itself
    print("\n=== Find start_vi function line ===")
    out = run(vm, f"grep -n 'td_s32 sample_comm_vi_start_vi' {VI_COMMON}")
    print(out.strip())

    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        print(f"\n=== sample_comm_vi_start_vi (line {line}, reading 80 lines) ===")
        out2 = run(vm, f"sed -n '{line},{line+80}p' {VI_COMMON}")
        print(out2)

    # Also check sensor type enum values in the header
    SNS_HEADER = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/include/hisilicon/ss_comm_sns.h"
    print("\n=== GS1860 sensor type enum ===")
    out = run(vm, f"grep -n 'GS1860\\|gs1860' {SNS_HEADER} 2>/dev/null | head -10")
    print(out.strip() or "(not found in ss_comm_sns.h)")

    # Search in all headers
    out = run(vm, "grep -rn 'GS1860' /home/ebaina/ZZIP/SS928V100_dtof_build_source/include/ 2>/dev/null | head -10")
    print(out.strip() or "(not found in includes)")

    vm.close()

if __name__ == "__main__":
    main()
