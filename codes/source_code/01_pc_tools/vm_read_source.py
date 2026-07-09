#!/usr/bin/env python3
"""Read sample_dtof.c mode 3 function from VM."""
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
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Find sample_dtof_dtof_and_rgb function
    print("=== Finding sample_dtof_dtof_and_rgb ===")
    rc, out = run(c, f"grep -n 'sample_dtof_dtof_and_rgb\\|sample_dtof_one_sensor\\|vi_get_vi_cfg\\|vi_start_vi\\|sensor0\\|SENSOR0\\|sensor2\\|SENSOR2\\|vi_pipe\\[' {SRC} | head -80")
    print(out)

    # Get the full mode 3 function (find its line range)
    print("\n=== sample_dtof_dtof_and_rgb function ===")
    rc, line_start = run(c, f"grep -n 'sample_dtof_dtof_and_rgb' {SRC} | head -5")
    print(f"Function locations: {line_start.strip()}")

    # Read around the function start
    # Find the function definition line
    rc, func_def = run(c, f"grep -n 'td_void sample_dtof_dtof_and_rgb\\|sample_dtof_dtof_and_rgb(' {SRC} | head -5")
    print(f"Function def: {func_def.strip()}")

    # Read the function - get line number then extract
    rc, linenum_out = run(c, f"grep -n 'td_void sample_dtof_dtof_and_rgb' {SRC}")
    print(f"Line: {linenum_out.strip()}")

    if linenum_out.strip():
        linenum = int(linenum_out.split(':')[0])
        # Read 150 lines from function start
        rc, func_body = run(c, f"sed -n '{linenum},{linenum+150}p' {SRC}")
        print(f"\n=== Function body (lines {linenum}-{linenum+150}) ===")
        print(func_body)

    # Also check sample_comm_vi.c for how VI starts both sensors
    print("\n\n=== sample_comm_vi.c: start_vi for multi-sensor ===")
    COMM_VI = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
    rc, out2 = run(c, f"grep -n 'start_vi\\|sns_type\\|vi_cfg\\[\\|sensor_num\\|SNS_NUM\\|sns_num' {COMM_VI} | head -60")
    print(out2)

    c.close()

if __name__ == "__main__":
    main()
