#!/usr/bin/env python3
"""Read sample_comm_isp_run and sample_comm_vi_start_one_pipe_isp to understand threading."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
COMM_ISP = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_isp.c"
COMM_VI = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out

def main():
    c = connect()

    # Read sample_comm_isp_run (line 643)
    print("=== sample_comm_isp_run (line 643+) ===")
    rc, out = run(c, f"sed -n '610,680p' {COMM_ISP}")
    print(out)

    # Read sample_comm_vi_start_one_pipe_isp (line 1769)
    print("\n=== sample_comm_vi_start_one_pipe_isp (line 1769) ===")
    rc, out2 = run(c, f"sed -n '1769,1860p' {COMM_VI}")
    print(out2)

    # Check sample_comm_vi_start_isp function
    print("\n=== sample_comm_vi_start_isp ===")
    rc, lout = run(c, f"grep -n 'td_s32 sample_comm_vi_start_isp\\|static.*sample_comm_vi_start_isp' {COMM_VI}")
    print(f"Location: {lout.strip()}")
    if lout.strip():
        lnum = int(lout.strip().split('\n')[0].split(':')[0])
        rc, func = run(c, f"sed -n '{lnum},{lnum+80}p' {COMM_VI}")
        print(func)

    # Check if there are pthread calls
    print("\n=== pthread usage in sample_comm_vi.c ===")
    rc, out3 = run(c, f"grep -n 'pthread\\|create.*thread\\|isp.*thread\\|thread.*isp' {COMM_VI} | head -20")
    print(out3)

    print("\n=== pthread usage in sample_comm_isp.c ===")
    rc, out4 = run(c, f"grep -n 'pthread\\|create.*thread' {COMM_ISP} | head -20")
    print(out4)

    # Also check sample_comm_isp.c for sensor_founction_cfg
    print("\n=== sample_comm_isp_sensor_founction_cfg (line 626) ===")
    rc, out5 = run(c, f"sed -n '626,680p' {COMM_ISP}")
    print(out5)

    c.close()

if __name__ == "__main__":
    main()
