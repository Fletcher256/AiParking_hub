#!/usr/bin/env python3
"""Debug GS1860 I2C issue - why does it fail after cold boot?"""
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
    return out + err

def main():
    board = connect()

    # 1. Check current log size and tail
    print("=== Log tail (last 10 lines) ===")
    out = run(board, "tail -10 /tmp/dtof.log; wc -l /tmp/dtof.log")
    print(out.strip())

    # 2. Check if I2C tools are available
    print("\n=== I2C tools ===")
    out = run(board, "which i2cdetect i2cget i2cset 2>/dev/null || ls /usr/bin/i2c* /sbin/i2c* 2>/dev/null || echo 'no i2c tools'")
    print(out.strip())

    # 3. Check /dev/i2c-*
    print("\n=== /dev/i2c devices ===")
    out = run(board, "ls -la /dev/i2c-* 2>/dev/null || echo 'no i2c devs'")
    print(out.strip())

    # 4. Try I2C detect on bus 4 (GS1860 is on I2C4 = /dev/i2c-4)
    print("\n=== i2cdetect on bus 4 ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null || echo 'i2cdetect not available'", timeout=10)
    print(out.strip()[:1000])

    # 5. Check GS1860 expected I2C address from source
    # GS1860 is typically at 0x36 or similar
    print("\n=== Check GS1860 I2C addr from source ===")
    out = run(board, "grep -r 'I2C_DEV_ADDR\\|i2c_addr\\|DEV_ADDR\\|0x36\\|0x1A\\|0x1B' /opt/sample/dtof/*.ini 2>/dev/null | head -10")
    print(out.strip())

    # 6. Check what ko modules handle I2C4
    print("\n=== dmesg for i2c ===")
    out = run(board, "dmesg 2>/dev/null | grep -i 'i2c\\|I2C' | tail -20 || echo 'no dmesg'")
    print(out.strip()[:1000])

    # 7. Check binary is still running
    print("\n=== Binary status ===")
    out = run(board, "ps | grep sample_dtof | grep -v grep; cat /proc/msp/vi 2>/dev/null | head -10 || echo 'no vi proc'")
    print(out.strip()[:500])

    # 8. Try manually running dtof_init.sh again (re-pulse GPIO96)
    print("\n=== Manually re-running dtof_init.sh ===")
    out = run(board, "cd /opt/sample/dtof && sh ./dtof_init.sh 2>&1 && echo 'dtof_init done'", timeout=10)
    print(out.strip())

    # 9. Try I2C detect again after dtof_init.sh
    print("\n=== i2cdetect bus 4 after re-init ===")
    time.sleep(2)
    out = run(board, "i2cdetect -r -y 4 2>/dev/null || echo 'no i2cdetect'", timeout=10)
    print(out.strip()[:1000])

    # 10. Try raw I2C read from GS1860 address
    print("\n=== Raw i2c read attempt ===")
    for addr in ['0x36', '0x37', '0x38', '0x1A', '0x1B', '0x1C']:
        out = run(board, f"i2cget -y 4 {addr} 0x00 2>/dev/null && echo 'GS1860 at {addr}' || echo 'no resp at {addr}'", timeout=5)
        print(out.strip())

    # 11. Check GPIO96 state
    print("\n=== GPIO96 state ===")
    out = run(board, "cat /sys/class/gpio/gpio96/value 2>/dev/null || echo 'GPIO96 not exported'")
    print(out.strip())

    # 12. Export and read GPIO96
    out = run(board, "echo 96 > /sys/class/gpio/export 2>/dev/null; "
                     "cat /sys/class/gpio/gpio96/direction 2>/dev/null; "
                     "cat /sys/class/gpio/gpio96/value 2>/dev/null")
    print(f"GPIO96: {out.strip()}")

    board.close()

if __name__ == "__main__":
    main()
