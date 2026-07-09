#!/usr/bin/env python3
"""Read mode 3 vs mode 0 sys_init and vi_cfg to find what's different for OS08A20."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_C   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
COMM_VI  = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
COMM_SYS = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_sys.c"

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

    # 1. Find sample_dtof_one_sensor (mode 0) vs sample_dtof_dtof_and_rgb (mode 3)
    print("=== Mode 0: sample_dtof_one_sensor location ===")
    rc, loc0 = run(c, f"grep -n 'td_s32 sample_dtof_one_sensor\\|static.*sample_dtof_one_sensor' {DTOF_C}")
    print(loc0.strip())
    if loc0.strip():
        lnum = int(loc0.strip().split('\n')[0].split(':')[0])
        rc, func0 = run(c, f"sed -n '{lnum},{lnum+60}p' {DTOF_C}")
        print(func0)

    # 2. Read mode 3 sys_init call to see what mode_type and video_mode are used
    print("\n=== Mode 3: sample_dtof_dtof_and_rgb - sys_init args ===")
    rc, loc3 = run(c, f"grep -n 'td_s32 sample_dtof_dtof_and_rgb\\|static.*sample_dtof_dtof_and_rgb' {DTOF_C}")
    print(loc3.strip())
    if loc3.strip():
        lnum3 = int(loc3.strip().split('\n')[0].split(':')[0])
        rc, func3 = run(c, f"sed -n '{lnum3},{lnum3+40}p' {DTOF_C}")
        print(func3)

    # 3. Find sample_dtof_sys_init
    print("\n=== sample_dtof_sys_init ===")
    rc, lsys = run(c, f"grep -n 'td_s32 sample_dtof_sys_init\\|static.*sample_dtof_sys_init' {DTOF_C}")
    print(lsys.strip())
    if lsys.strip():
        lnum_s = int(lsys.strip().split('\n')[0].split(':')[0])
        rc, fsys = run(c, f"sed -n '{lnum_s},{lnum_s+80}p' {DTOF_C}")
        print(fsys)

    # 4. Find sample_dtof_get_one_sensor_vi_cfg
    print("\n=== sample_dtof_get_one_sensor_vi_cfg ===")
    rc, lvi = run(c, f"grep -n 'sample_dtof_get_one_sensor_vi_cfg' {DTOF_C} | head -5")
    print(lvi.strip())
    if lvi.strip():
        lnum_vi = int(lvi.strip().split('\n')[0].split(':')[0])
        rc, fvi = run(c, f"sed -n '{lnum_vi},{lnum_vi+60}p' {DTOF_C}")
        print(fvi)

    # 5. Check LANE_DIVIDE_MODE usage
    print("\n=== LANE_DIVIDE_MODE usage in dtof.c ===")
    rc, ldiv = run(c, f"grep -n 'LANE_DIVIDE\\|lane_divide\\|combo_dev\\|COMBO' {DTOF_C} | head -20")
    print(ldiv)

    # 6. Check sample_comm_vi for lane divide and combo dev attr setting
    print("\n=== LANE_DIVIDE in sample_comm_vi.c ===")
    rc, ldiv2 = run(c, f"grep -n 'LANE_DIVIDE\\|lane_divide' {COMM_VI} | head -20")
    print(ldiv2)

    # 7. Check if there's a combine sensor VI cfg function
    print("\n=== sample_dtof_start_multi_vi_vpss details ===")
    rc, lmulti = run(c, f"grep -n 'td_s32 sample_dtof_start_multi_vi_vpss' {DTOF_C}")
    print(lmulti.strip())
    if lmulti.strip():
        lnum_m = int(lmulti.strip().split('\n')[0].split(':')[0])
        rc, fmulti = run(c, f"sed -n '{lnum_m},{lnum_m+60}p' {DTOF_C}")
        print(fmulti)

    # 8. Check what video_mode is used in mode 3
    print("\n=== VIDEO_MODE and pipe_num in dtof.c ===")
    rc, lvm = run(c, f"grep -n 'VIDEO_MODE\\|video_mode\\|pipe_num\\|OT_VI_OFFLINE\\|OT_VI_ONLINE' {DTOF_C} | head -20")
    print(lvm)

    c.close()

if __name__ == "__main__":
    main()
