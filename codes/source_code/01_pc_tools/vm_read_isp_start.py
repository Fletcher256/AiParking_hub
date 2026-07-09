#!/usr/bin/env python3
"""Read sample_comm_vi_start_vi and ISP start functions to understand sensor init flow."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
COMM_VI = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
COMM_ISP = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_isp.c"

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

    # Read sample_comm_vi_start_vi function - lines 1881 onwards
    print("=== sample_comm_vi_start_vi (lines 1881-1980) ===")
    rc, out = run(c, f"sed -n '1881,1980p' {COMM_VI}")
    print(out)

    # Find sample_comm_vi_isp_start
    print("\n=== sample_comm_vi_isp_start location ===")
    rc, lout = run(c, f"grep -n 'sample_comm_vi_isp_start\\|isp_run\\|isp_run_once\\|ISP_RUN\\|mpi_isp_run' {COMM_VI} | head -20")
    print(lout)

    # Find sample_comm_vi_start_one_pipe
    rc, lout2 = run(c, f"grep -n 'start_one_pipe\\|sample_comm_vi_start_one_pipe' {COMM_VI} | head -10")
    print(f"\nstart_one_pipe locations: {lout2.strip()}")
    if lout2.strip():
        lnum = int(lout2.strip().split('\n')[0].split(':')[0])
        rc, func = run(c, f"sed -n '{lnum},{lnum+80}p' {COMM_VI}")
        print(f"\n=== start_one_pipe (line {lnum}) ===")
        print(func)

    # Check sample_comm_isp.c for isp_run and sensor init
    print("\n=== sample_comm_isp.c - isp run and sensor init ===")
    rc, out2 = run(c, f"grep -n 'isp_run\\|sensor_init\\|sensor_founction\\|pfn_cmos\\|isp_start' {COMM_ISP} | head -30")
    print(out2)

    # Find isp_start or sample_comm_vi_isp_start
    rc, lout3 = run(c, f"grep -n 'td_s32 sample_comm_vi_isp_start\\|static.*isp_start' {COMM_VI} | head -5")
    print(f"\nISP start function: {lout3.strip()}")
    if lout3.strip():
        lnum3 = int(lout3.strip().split('\n')[0].split(':')[0])
        rc, func3 = run(c, f"sed -n '{lnum3},{lnum3+50}p' {COMM_VI}")
        print(func3)

    # Check what happens with OT_VI_OFFLINE
    print("\n=== Offline mode ISP handling ===")
    rc, out3 = run(c, f"grep -n 'OFFLINE\\|offline\\|run_once\\|RUN_ONCE' {COMM_VI} | head -20")
    print(out3)
    rc, out4 = run(c, f"grep -n 'OFFLINE\\|offline\\|run_once\\|RUN_ONCE' {COMM_ISP} | head -20")
    print(out4)

    # Check combo_dev_attr for OS08A20 at line 73
    print("\n=== g_mipi_4lane_chn0_sensor_os08a20_12bit_8m_nowdr_attr ===")
    rc, out5 = run(c, f"sed -n '73,97p' {COMM_VI}")
    print(out5)

    c.close()

if __name__ == "__main__":
    main()
