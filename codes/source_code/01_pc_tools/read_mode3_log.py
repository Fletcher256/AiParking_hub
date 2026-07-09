#!/usr/bin/env python3
"""Read full mode3 log and ISP/dmesg state from board."""
import paramiko

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Check if binary is still running
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep || echo 'NONE'")
    print(f"Binary: {ps.strip()}")

    # Read full log
    print("\n=== Full /tmp/mode3.log ===")
    rc, log = run(c, "cat /tmp/mode3.log 2>/dev/null || echo 'no log'")
    print(log)

    # dmesg - recent sensor/ISP messages
    print("\n=== dmesg (all sensor/ISP/MIPI/I2C messages since boot) ===")
    rc, dm = run(c, "dmesg | grep -i 'os08a20\\|gs1860\\|mipi\\|i2c.*error\\|i2c.*timeout\\|timeout\\|isp\\|sensor\\|sensor_cfg' | head -50")
    print(dm)

    # VI pipe status now
    print("\n=== VI pipe status ===")
    rc, vi = run(c, "cat /proc/umap/vi | grep -A4 'vi pipe status'")
    print(vi)

    # ISP status
    print("\n=== ISP drv info (pipe 0) ===")
    rc, isp = run(c, "cat /proc/umap/isp 2>/dev/null | head -50")
    print(isp)

    # OS08A20 register if accessible
    rc, reg = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"\nOS08A20 0x0100: {reg.strip()}")

    c.close()

if __name__ == "__main__":
    main()
