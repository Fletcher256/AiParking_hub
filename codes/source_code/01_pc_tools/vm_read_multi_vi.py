#!/usr/bin/env python3
"""Read sample_dtof_start_multi_vi_vpss and related functions."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

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

    # Find sample_dtof_start_multi_vi_vpss
    print("=== sample_dtof_start_multi_vi_vpss locations ===")
    rc, locs = run(c, f"grep -n 'sample_dtof_start_multi_vi_vpss\\|start_multi_vi' {SRC}")
    print(locs)

    rc, lineout = run(c, f"grep -n 'static.*sample_dtof_start_multi_vi_vpss' {SRC}")
    if lineout.strip():
        lnum = int(lineout.split(':')[0])
        rc, func = run(c, f"sed -n '{lnum},{lnum+80}p' {SRC}")
        print(f"\n=== Function body (line {lnum}) ===")
        print(func)

    # Also look at sample_dtof_sys_init
    print("\n=== sample_dtof_sys_init ===")
    rc, lineout2 = run(c, f"grep -n 'static.*sample_dtof_sys_init\\|td_s32 sample_dtof_sys_init' {SRC}")
    print(f"Location: {lineout2.strip()}")
    if lineout2.strip():
        lnum2 = int(lineout2.split(':')[0])
        rc, func2 = run(c, f"sed -n '{lnum2},{lnum2+60}p' {SRC}")
        print(func2)

    # Check what VB_DOUBLE_YUV_CNT is
    print("\n=== VB pool defines ===")
    rc, defs = run(c, f"grep -n 'VB_DOUBLE_YUV\\|VB_WDR_RAW\\|VB_POOL\\|vb_cnt' {SRC} | head -20")
    print(defs)

    # Check the sample_comm_vi.c for start_multi_vi_vpss
    COMM = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
    rc, out = run(c, f"grep -rn 'start_multi_vi_vpss' /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/ | head -10")
    print(f"\n=== All start_multi_vi_vpss refs ===\n{out}")

    c.close()

if __name__ == "__main__":
    main()
