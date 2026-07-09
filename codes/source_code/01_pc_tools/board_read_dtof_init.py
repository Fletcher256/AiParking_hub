#!/usr/bin/env python3
"""Read dtof_init.sh and load_ss928v100 scripts from board to understand GPIO/PWM setup."""
import paramiko

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out

def main():
    c = connect()

    print("=== /opt/sample/dtof/dtof_init.sh ===")
    rc, out = run(c, "cat /opt/sample/dtof/dtof_init.sh")
    print(out)

    print("\n=== /opt/ko/load_ss928v100 (first 100 lines) ===")
    rc, out = run(c, "head -100 /opt/ko/load_ss928v100")
    print(out)

    print("\n=== GPIO state of sns_rst_src=0 (RTSN0 / reset pin) ===")
    rc, out = run(c, "cat /sys/class/gpio/gpio*/value 2>/dev/null | head -20; ls /sys/class/gpio/ 2>/dev/null | head -20")
    print(out)

    print("\n=== /proc/umap/mipi_rx (current state before any binary) ===")
    rc, out = run(c, "cat /proc/umap/mipi_rx 2>/dev/null | head -30")
    print(out)

    print("\n=== Running processes ===")
    rc, out = run(c, "ps | grep -E 'dtof|vio|sensor|sample' | grep -v grep")
    print(out)

    print("\n=== /opt/ko/load_ss928v100 gpio section ===")
    rc, out = run(c, "grep -n 'gpio\\|GPIO\\|reset\\|RESET\\|pwm\\|PWM\\|i2c\\|I2C\\|sensor\\|SENSOR' /opt/ko/load_ss928v100 | head -40")
    print(out)

    c.close()

if __name__ == "__main__":
    main()
