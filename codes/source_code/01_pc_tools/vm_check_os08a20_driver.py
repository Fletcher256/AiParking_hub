#!/usr/bin/env python3
"""Check OS08A20 sensor driver MIPI parameters and init sequence."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC_BASE = "/home/ebaina/ZZIP/SS928V100_dtof_build_source"

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

    # Find OS08A20 sensor driver
    print("=== Finding OS08A20 sensor driver ===")
    rc, out = run(c, f"find {SRC_BASE} -name '*os08a20*' -o -name '*OS08A20*' 2>/dev/null | head -20")
    print(out)

    # Check combo dev attr for OS08A20 in sample_comm_vi.c
    COMM_VI = f"{SRC_BASE}/src/common/sample_comm_vi.c"
    print("\n=== OS08A20 MIPI combo attr in sample_comm_vi.c ===")
    rc, lineout = run(c, f"grep -n 'OS08A20\\|os08a20\\|OV_OS08A20' {COMM_VI} | head -20")
    print(lineout)

    # Read the case for OS08A20 in get_mipi_attr
    rc, lineout2 = run(c, f"grep -n 'OV_OS08A20_MIPI_8M_30FPS_12BIT' {COMM_VI} | head -5")
    print(f"OS08A20 case location: {lineout2.strip()}")
    if lineout2.strip():
        lnum = int(lineout2.strip().split('\n')[0].split(':')[0])
        rc, case_body = run(c, f"sed -n '{lnum},{lnum+50}p' {COMM_VI}")
        print(f"\nCase body (line {lnum}):\n{case_body}")

    # Check if there's a mipi_attr_by_dev_id for OS08A20
    print("\n=== get_mipi_attr_by_dev_id for OS08A20 ===")
    rc, lineout3 = run(c, f"grep -n -A30 'OV_OS08A20_MIPI_8M_30FPS_12BIT' {COMM_VI} | grep -A30 'mipi_attr_by_dev_id\\|combo_dev_attr_t' | head -60")
    print(lineout3[:3000])

    # Also check the sample_dtof specific mipi attr
    SRC_DTOF = f"{SRC_BASE}/src/dtof/sample_dtof.c"
    print("\n=== Any MIPI attr overrides in sample_dtof.c ===")
    rc, out = run(c, f"grep -n 'combo_dev_attr\\|data_rate\\|lane_id\\|divide_mode\\|mipi_info' {SRC_DTOF} | head -20")
    print(out)

    # Check get_mipi_attr_by_dev_id function - look at what it does for dev_id=0 (OS08A20)
    print("\n=== get_mipi_attr_by_dev_id function body ===")
    rc, lout = run(c, f"grep -n 'static.*get_mipi_attr_by_dev_id' {COMM_VI}")
    if lout.strip():
        lnum = int(lout.split(':')[0])
        rc, func = run(c, f"sed -n '{lnum},{lnum+80}p' {COMM_VI}")
        print(func)

    # Also look at the SNS sensor init file
    print("\n=== OS08A20 sensor src folder ===")
    rc, out = run(c, f"find {SRC_BASE} -path '*/os08a20*' -name '*.c' 2>/dev/null | head -10")
    print(out)

    # Check what registers OS08A20 sensor init writes (streaming enable register)
    rc, files = run(c, f"find {SRC_BASE} -name 'os08a20*.c' 2>/dev/null | head -5")
    if files.strip():
        f1 = files.strip().split('\n')[0]
        print(f"\n=== OS08A20 sensor init function in {f1} ===")
        rc2, lineout4 = run(c, f"grep -n 'stream\\|STREAM\\|start\\|0x0100\\|streaming' {f1} | head -20")
        print(lineout4)

        rc2, out2 = run(c, f"grep -n 'os08a20_init\\|sensor_init' {f1} | head -10")
        print(f"Init functions: {out2}")

    c.close()

if __name__ == "__main__":
    main()
