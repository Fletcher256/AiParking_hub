#!/usr/bin/env python3
"""Fix GS1860 sns_rst_src conflict with OS08A20 in sample_dtof.c.

Root cause: GS1860 VI start calls ss_mpi_mipi_rx_reset_sensor(0) which resets OS08A20
because both sensors have sns_rst_src=0 and sns_clk_src=0.
Fix: Change GS1860's sns_rst_src and sns_clk_src to 2 (matching its vi_dev=2).
GS1860 actual reset is via GPIO96 in dtof_init.sh, not through SDK rst_src.
"""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_C   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
BUILD_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # 1. Read current GS1860 sensor_num==2 and sensor_num==3 configs
    print("=== Current dtof_sensor_vi_cfg for sensor_num 2 and 3 ===")
    rc, loc = run(c, f"grep -n 'sample_dtof_get_one_dtof_sensor_vi_cfg' {DTOF_C} | head -3")
    print(loc)
    if loc.strip():
        lnum = int(loc.strip().split('\n')[0].split(':')[0])
        rc, out = run(c, f"sed -n '{lnum},{lnum+100}p' {DTOF_C}")
        print(out)

    # 2. Show the specific lines to change
    print("\n=== Lines with sns_clk_src and sns_rst_src in get_one_dtof_sensor_vi_cfg ===")
    rc, out2 = run(c, f"grep -n 'sns_clk_src\\|sns_rst_src' {DTOF_C}")
    print(out2)

    # 3. Read the exact context around the GS1860 sns_rst_src line
    # Find line with sensor_num==2 block's sns_rst_src = 0
    # We need to change ONLY the dtof sensor ones, not the RGB sensor (sensor_num 0/1)
    # The function sample_dtof_get_one_dtof_sensor_vi_cfg starts at some line
    rc, func_loc = run(c, f"grep -n 'td_void sample_dtof_get_one_dtof_sensor_vi_cfg' {DTOF_C}")
    print(f"\nFunction location: {func_loc.strip()}")
    if func_loc.strip():
        func_lnum = int(func_loc.strip().split('\n')[0].split(':')[0])
        rc, func_body = run(c, f"sed -n '{func_lnum},{func_lnum+120}p' {DTOF_C}")
        print(f"\nFunction body:\n{func_body}")

    c.close()

    # 4. Create the patch to apply
    print("\n=== Patch plan ===")
    print("Need to change sns_rst_src and sns_clk_src in get_one_dtof_sensor_vi_cfg:")
    print("  For sensor_num==2 (GS1860 on J3, i2c4): sns_clk_src=0->2, sns_rst_src=0->2")
    print("  For sensor_num==3 (GS1860 on J4, i2c5 but different): check if change needed")
    print("  DO NOT change sample_dtof_get_one_sensor_vi_cfg (RGB sensor configs)")

if __name__ == "__main__":
    main()
