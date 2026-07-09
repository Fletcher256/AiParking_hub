#!/usr/bin/env python3
"""Read full mode 3 function and helper functions from VM."""
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

    # Read lines 477-570 (mode 3 function)
    print("=== sample_dtof_dtof_and_rgb (lines 477-570) ===")
    rc, out = run(c, f"sed -n '477,570p' {SRC}")
    print(out)

    # Find sample_dtof_get_one_sensor_vi_cfg
    print("\n=== sample_dtof_get_one_sensor_vi_cfg ===")
    rc, lineout = run(c, f"grep -n 'sample_dtof_get_one_sensor_vi_cfg' {SRC}")
    print(f"Locations: {lineout.strip()}")

    # Read the helper function
    rc, lineno_out = run(c, f"grep -n 'static.*sample_dtof_get_one_sensor_vi_cfg\\|void sample_dtof_get_one_sensor' {SRC}")
    print(f"Function def: {lineno_out.strip()}")
    if lineno_out.strip():
        lnum = int(lineno_out.split(':')[0])
        rc, func = run(c, f"sed -n '{lnum},{lnum+60}p' {SRC}")
        print(func)

    # Also read lines before 477 (the common vi_cfg setup for mode 3)
    print("\n=== Lines 460-480 (context before mode 3) ===")
    rc, out = run(c, f"sed -n '460,480p' {SRC}")
    print(out)

    # Check sample_dtof_start_vi_common or similar helper
    print("\n=== Grep for vi_start, isp_start in sample_dtof.c ===")
    rc, out = run(c, f"grep -n 'vi_start_vi\\|isp_start\\|comm_vi_start\\|start_vi' {SRC} | head -40")
    print(out)

    # Check lines around 498-535 more carefully (the OS08A20 start)
    print("\n=== Lines 490-545 (OS08A20 VI start region) ===")
    rc, out = run(c, f"sed -n '490,545p' {SRC}")
    print(out)

    c.close()

if __name__ == "__main__":
    main()
