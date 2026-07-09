#!/usr/bin/env python3
"""Read VB constants and check what VB_WDR_RAW_CNT value is, and check ISP pipe 0 init in mode 3."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_C   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
DTOF_H   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.h"

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

    # 1. Find VB constant definitions
    print("=== VB constants (VB_YUV, VB_RAW, VB_DOUBLE, VB_WDR) ===")
    rc, out = run(c, f"grep -n 'VB_YUV_ROUTE_CNT\\|VB_RAW_CNT_NONE\\|VB_DOUBLE_YUV_CNT\\|VB_WDR_RAW_CNT' {DTOF_C} {DTOF_H}")
    print(out)

    # 2. Read dtof.h to find defines
    rc, out2 = run(c, f"grep -n 'define.*VB_' {DTOF_H} 2>/dev/null || grep -n 'define.*VB_' {DTOF_C} | head -20")
    print(f"\n=== #define VB_ ===\n{out2}")

    # 3. Search in all header files for VB constants
    rc, out3 = run(c, "grep -rn 'VB_YUV_ROUTE_CNT\\|VB_DOUBLE_YUV_CNT\\|VB_WDR_RAW_CNT\\|VB_RAW_CNT_NONE' "
                      "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/ 2>/dev/null | head -20")
    print(f"\n=== All header VB constants ===\n{out3}")

    # 4. Read the full mode 3 function after the VENC patch to see GS1860 init
    print("\n=== Mode 3 full function after VENC patch ===")
    rc, loc3 = run(c, f"grep -n 'td_s32 sample_dtof_dtof_and_rgb' {DTOF_C}")
    if loc3.strip():
        lnum3 = int(loc3.strip().split('\n')[0].split(':')[0])
        rc, func3 = run(c, f"sed -n '{lnum3},{lnum3+120}p' {DTOF_C}")
        print(func3)

    # 5. Check get_default_vb_config to understand WDR_RAW effect
    print("\n=== sample_dtof_get_default_vb_config ===")
    rc, loc_vb = run(c, f"grep -n 'td_void sample_dtof_get_default_vb_config' {DTOF_C}")
    if loc_vb.strip():
        lnum_vb = int(loc_vb.strip().split('\n')[0].split(':')[0])
        rc, func_vb = run(c, f"sed -n '{lnum_vb},{lnum_vb+50}p' {DTOF_C}")
        print(func_vb)

    # 6. Check if sample_comm_vi_start_vi does anything different based on divide_mode
    print("\n=== sample_comm_vi_set_mipi_hs_mode (lane divide handling) ===")
    COMM_VI = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
    rc, lhs = run(c, f"grep -n 'sample_comm_vi_set_mipi_hs_mode\\|set_mipi_hs_mode' {COMM_VI} | head -10")
    print(lhs)
    rc, lhs2 = run(c, f"grep -n 'td_s32 sample_comm_vi_set_mipi_hs_mode' {COMM_VI}")
    if lhs2.strip():
        lnum_hs = int(lhs2.strip().split('\n')[0].split(':')[0])
        rc, func_hs = run(c, f"sed -n '{lnum_hs},{lnum_hs+40}p' {COMM_VI}")
        print(f"\n=== set_mipi_hs_mode impl ===\n{func_hs}")

    # 7. Read sample_comm_vi_start_vi to see exactly what calls set_mipi_hs_mode
    print("\n=== sample_comm_vi_start_vi (where divide_mode is used) ===")
    rc, lstart = run(c, f"grep -n 'td_s32 sample_comm_vi_start_vi' {COMM_VI}")
    if lstart.strip():
        lnum_start = int(lstart.strip().split('\n')[0].split(':')[0])
        rc, func_start = run(c, f"sed -n '{lnum_start},{lnum_start+60}p' {COMM_VI}")
        print(func_start)

    c.close()

if __name__ == "__main__":
    main()
