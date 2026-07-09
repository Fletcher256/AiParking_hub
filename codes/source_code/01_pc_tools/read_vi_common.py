#!/usr/bin/env python3
"""Read sample_comm_vi.c to understand vi_start internals."""
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

    # Find the sample_comm_vi_start_vi function
    print("=== sample_comm_vi_start_vi function ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start_vi\\|sample_comm_vi_create\\|sample_comm_isp_run\\|SS_MPI_VI_Enable\\|MPI_ISP_Run\\|sensor_init\\|cmos_init\\|SnsRegCb' {VI_COMMON} | head -30")
    print(out.strip())

    # Find the function definition and read it
    print("\n=== sample_comm_vi_start_vi implementation ===")
    out = run(vm, f"grep -n 'td_s32 sample_comm_vi_start_vi' {VI_COMMON}")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+60}p' {VI_COMMON}")
        print(out2.strip()[:4000])

    # Find sample_comm_vi_stop_vi
    print("\n=== sample_comm_vi_stop_vi ===")
    out = run(vm, f"grep -n 'td_s32 sample_comm_vi_stop_vi\\|void sample_comm_vi_stop_vi' {VI_COMMON}")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+40}p' {VI_COMMON}")
        print(out2.strip()[:3000])

    # Look for sensor register / ISP sensor init
    print("\n=== ISP sensor registration ===")
    out = run(vm, f"grep -n 'SnsRegCb\\|sensor_reg\\|sns_init\\|isp_run\\|ISP_Run\\|ISP_MemInit\\|cmos_init' {VI_COMMON} | head -20")
    print(out.strip())

    # Also check sample_comm_isp.c
    ISP_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_isp.c"
    print("\n=== sample_comm_isp.c - ISP run function ===")
    out = run(vm, f"grep -n 'isp_run\\|ISP_Run\\|sensor_reg\\|SnsRegCb\\|cmos_init\\|td_s32 sample_comm_isp' {ISP_COMMON} | head -30")
    print(out.strip())

    out = run(vm, f"grep -n 'td_s32 sample_comm_isp_run\\|void sample_comm_isp_run' {ISP_COMMON}")
    print(out.strip())
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+50}p' {ISP_COMMON}")
        print(out2.strip()[:3000])

    vm.close()

if __name__ == "__main__":
    main()
