#!/usr/bin/env python3
"""Read sample_comm_vi_start_isp and stop_isp implementations."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
VI_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
VI_HEADER = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.h"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # Find start_isp and stop_isp
    print("=== sample_comm_vi_start_isp / stop_isp ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start_isp\\|sample_comm_vi_stop_isp' {VI_COMMON} | head -10")
    print(out.strip())

    # Read start_isp
    print("\n=== sample_comm_vi_start_isp implementation ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start_isp' {VI_COMMON} | head -3")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+60}p' {VI_COMMON}")
        print(out2.strip()[:4000])

    # Read stop_isp
    print("\n=== sample_comm_vi_stop_isp implementation ===")
    out = run(vm, f"grep -n 'void sample_comm_vi_stop_isp\\|td_s32 sample_comm_vi_stop_isp\\|^static.*vi_stop_isp' {VI_COMMON}")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+40}p' {VI_COMMON}")
        print(out2.strip()[:3000])

    # Check if start_isp/stop_isp are in the header
    print("\n=== Header declarations ===")
    out = run(vm, f"grep -n 'start_isp\\|stop_isp' {VI_HEADER} 2>/dev/null | head -10")
    print(out.strip() or "(not in header)")

    # Check if they're static
    print("\n=== Are these static? ===")
    out = run(vm, f"grep -n '^static.*vi_start_isp\\|^static.*vi_stop_isp\\|^td_s32 sample_comm_vi_start_isp\\|^td_void sample_comm_vi_stop_isp' {VI_COMMON}")
    print(out.strip())

    vm.close()

if __name__ == "__main__":
    main()
