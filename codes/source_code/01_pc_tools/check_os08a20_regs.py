#!/usr/bin/env python3
"""Check OS08A20 sensor register state and combo_dev_attr details."""
import paramiko, time

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
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Check binary is still running
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"Binary: {ps.strip()}")

    # Read OS08A20 key registers via i2ctransfer (16-bit register addresses)
    # OS08A20 is at I2C5, address 0x36
    # Register 0x0100 = streaming control (0x01 = stream, 0x00 = standby)
    print("\n=== OS08A20 register reads (I2C5, addr 0x36) ===")

    # i2ctransfer: write 2-byte reg addr, then read 1 byte
    regs_to_read = [
        (0x0100, "Streaming mode (0x01=ON, 0x00=standby)"),
        (0x0103, "Software reset"),
        (0x3801, "X start high"),
        (0x3820, "Format control 1 (flip)"),
        (0x3C80, "MIPI ctrl"),
        (0x4800, "MIPI ctrl 1"),
        (0x4837, "MIPI PCLK (data rate related)"),
        (0x0300, "PLL ctrl0 - pre-divider"),
        (0x0302, "PLL ctrl2 - multiplier"),
    ]

    for reg, desc in regs_to_read:
        reg_hi = (reg >> 8) & 0xFF
        reg_lo = reg & 0xFF
        cmd = f"i2ctransfer -y 5 w2@0x36 0x{reg_hi:02x} 0x{reg_lo:02x} r1 2>/dev/null"
        rc, out = run(c, cmd)
        val = out.strip()
        print(f"  0x{reg:04X} ({desc}): {val}")

    # Also check via i2cget with word mode
    print("\n=== Direct i2cget check ===")
    rc, out = run(c, "i2cget -y 5 0x36 0x01 2>/dev/null || echo 'failed'")
    print(f"  i2cget reg 0x01: {out.strip()}")

    # Check what i2ctransfer shows for chip ID
    print("\n=== OS08A20 chip ID (should be 0x5308) ===")
    # Chip ID high at 0x300A, low at 0x300B
    rc, id_hi = run(c, "i2ctransfer -y 5 w2@0x36 0x30 0x0A r1 2>/dev/null")
    rc, id_lo = run(c, "i2ctransfer -y 5 w2@0x36 0x30 0x0B r1 2>/dev/null")
    print(f"  Chip ID: hi={id_hi.strip()}, lo={id_lo.strip()}")

    # Check the ISP thread state more carefully
    print("\n=== ISP thread state ===")
    rc, isp = run(c, "cat /proc/umap/isp | grep -A10 'drv info' | head -20")
    print(isp)

    # Check if ISP alarm (sensor init failed)
    print("\n=== /proc/umap/isp full module/control param ===")
    rc, isp2 = run(c, "cat /proc/umap/isp | head -30")
    print(isp2)

    # Check the VI dev detect status (should show valid frame dimensions if MIPI works)
    print("\n=== VI dev detect info ===")
    rc, vi_det = run(c, "cat /proc/umap/vi | grep -A4 'vi dev detect'")
    print(vi_det)

    # Also check via kernel message (dmesg) for sensor init messages
    print("\n=== dmesg - sensor/MIPI related messages ===")
    rc, dmesg = run(c, "dmesg | grep -i 'os08a20\\|mipi\\|sensor\\|i2c.*5\\|isp\\|csi' | tail -30 2>/dev/null")
    print(dmesg[:3000])

    c.close()

if __name__ == "__main__":
    main()
