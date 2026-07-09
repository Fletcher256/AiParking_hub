#!/usr/bin/env python3
"""Force OS08A20 into streaming mode manually to test if MIPI starts."""
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

def read_reg(c, reg):
    hi = (reg >> 8) & 0xFF
    lo = reg & 0xFF
    rc, out = run(c, f"i2ctransfer -y 5 w2@0x36 0x{hi:02x} 0x{lo:02x} r1 2>/dev/null")
    return out.strip()

def write_reg(c, reg, val):
    hi = (reg >> 8) & 0xFF
    lo = reg & 0xFF
    rc, out = run(c, f"i2ctransfer -y 5 w3@0x36 0x{hi:02x} 0x{lo:02x} 0x{val:02x} 2>&1")
    return rc, out.strip()

def main():
    c = connect()

    # Verify binary still running
    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"Binary: {ps.strip()}")

    # Read current state
    print(f"\n=== Current OS08A20 state ===")
    print(f"  0x0100 (stream): {read_reg(c, 0x0100)}")
    print(f"  0x4800 (MIPI ctrl1): {read_reg(c, 0x4800)}")
    print(f"  0x4801 (MIPI ctrl2): {read_reg(c, 0x4801)}")
    print(f"  0x4802 (MIPI ctrl3): {read_reg(c, 0x4802)}")

    # MIPI before
    print("\n=== MIPI before streaming ===")
    rc, mipi = run(c, "cat /proc/umap/mipi_rx | grep -A4 'phy data info'")
    print(mipi)

    # Try enabling streaming
    print("\n=== Enabling OS08A20 streaming (0x0100 = 0x01) ===")
    rc, out = write_reg(c, 0x0100, 0x01)
    print(f"Write result: rc={rc}, out={out}")

    # Verify
    val = read_reg(c, 0x0100)
    print(f"  0x0100 after write: {val}")

    # Wait 2s for MIPI to come up
    time.sleep(2)

    # Check MIPI now
    print("\n=== MIPI after streaming enable ===")
    rc, mipi2 = run(c, "cat /proc/umap/mipi_rx | grep -A6 'phy data info\\|detect info'")
    print(mipi2)

    # Check VI status
    print("\n=== VI pipe 0 int_cnt after streaming enable ===")
    rc, vi = run(c, "cat /proc/umap/vi | grep -A4 'vi pipe status'")
    print(vi)

    # If MIPI is still not working, check if we need to configure MIPI first
    print("\n=== PHY data full check ===")
    rc, phy = run(c, "cat /proc/umap/mipi_rx | head -50")
    print(phy)

    # Wait 5 more seconds
    time.sleep(5)
    print("\n=== MIPI after 7s total ===")
    rc, mipi3 = run(c, "cat /proc/umap/mipi_rx | grep -B1 -A4 'detect info'")
    print(mipi3)

    rc, vi2 = run(c, "cat /proc/umap/vi | grep -A4 'vi pipe status'")
    print("\n=== VI pipe status ===")
    print(vi2)

    rc, isp = run(c, "cat /proc/umap/isp | grep -A4 'drv info' | head -15")
    print("\n=== ISP drv info ===")
    print(isp)

    c.close()

if __name__ == "__main__":
    main()
