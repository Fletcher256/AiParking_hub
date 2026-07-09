#!/usr/bin/env python3
"""Read sample_comm_vi_start_isp and start_one_pipe_isp to find where reset happens."""
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

    # Read sample_comm_vi_start_isp
    print("=== sample_comm_vi_start_isp ===")
    out = run(vm, f"grep -n 'td_s32 sample_comm_vi_start_isp\\|static.*vi_start_isp' {VI_COMMON}")
    print(out.strip())

    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        code = run(vm, f"sed -n '{line},{line+80}p' {VI_COMMON}")
        print(code)

    # Read sample_comm_vi_start_one_pipe_isp
    print("\n=== sample_comm_vi_start_one_pipe_isp ===")
    out = run(vm, f"grep -n 'start_one_pipe_isp' {VI_COMMON} | head -5")
    print(out.strip())

    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        code = run(vm, f"sed -n '{line},{line+100}p' {VI_COMMON}")
        print(code)

    # Also look for where ss_mpi_isp_init is called and what surrounds it
    print("\n=== ss_mpi_isp_init call context ===")
    out = run(vm, f"grep -n 'ss_mpi_isp_init\\|ss_mpi_isp_mem_init\\|register_sensor_lib\\|pfn_cmos' {VI_COMMON} | head -20")
    print(out.strip())

    vm.close()

if __name__ == "__main__":
    main()
