#!/usr/bin/env python3
"""Read sample_comm_vi_start_one_pipe_isp and stop_one_pipe_isp."""
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
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # Find start_one_pipe_isp and stop_one_pipe_isp
    print("=== start_one_pipe_isp / stop_one_pipe_isp ===")
    out = run(vm, f"grep -n 'start_one_pipe_isp\\|stop_one_pipe_isp' {VI_COMMON} | head -10")
    print(out.strip())

    # Read stop_one_pipe_isp
    print("\n=== sample_comm_vi_stop_one_pipe_isp ===")
    out = run(vm, f"grep -n 'stop_one_pipe_isp' {VI_COMMON} | head -5")
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+40}p' {VI_COMMON}")
        print(out2.strip()[:3000])

    # Read start_one_pipe_isp
    print("\n=== sample_comm_vi_start_one_pipe_isp ===")
    out = run(vm, f"grep -n 'start_one_pipe_isp' {VI_COMMON} | head -5")
    print(out.strip())
    if out.strip():
        # Find the function definition (not calls)
        lines = [l for l in out.strip().split('\n') if 'static' in l or '(' in l]
        for l in out.strip().split('\n'):
            if 'static' in l or ('start_one_pipe_isp' in l and '(' in l):
                line = int(l.split(':')[0].strip())
                out2 = run(vm, f"sed -n '{line},{line+60}p' {VI_COMMON}")
                print(out2.strip()[:3000])
                break

    # Also check what's in sample_comm_vi.h for sensor-related declarations
    VI_HEADER = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.h"
    print("\n=== sample_comm_vi.h - relevant declarations ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start\\|sample_comm_vi_stop\\|sensor\\|isp' {VI_HEADER} | head -20")
    print(out.strip())

    vm.close()

if __name__ == "__main__":
    main()
