#!/usr/bin/env python3
"""
GS1860 is now ready on I2C (0x28).
Kill current binary, wait for ISP cleanup, restart it.
"""
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

    # 1. Verify GS1860 is responding on I2C
    print("=== GS1860 on I2C4 before kill ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null | grep -v '00\\|10\\|20\\|30\\|40\\|50\\|60\\|70' | head -3; "
                     "echo 'scanning I2C4...'; i2cdetect -r -y 4 2>/dev/null", timeout=10)
    print(out.strip()[:1000])

    # 2. Kill binary cleanly (SIGTERM only - let it clean up ISP)
    print("\n=== Killing binary with SIGTERM ===")
    out = run(board, "pkill -TERM -x 'sample_dtof_os08a20'; echo 'SIGTERM sent'")
    print(out.strip())

    # 3. Wait for clean exit
    print("Waiting 10 sec for ISP cleanup...")
    time.sleep(10)

    out = run(board, "ps | grep sample_dtof | grep -v grep || echo 'binary gone'")
    print(f"After SIGTERM: {out.strip()}")

    # If still running after 10s, try SIGKILL
    if 'sample_dtof' in out:
        print("Still running, sending SIGKILL...")
        run(board, "pkill -9 -x 'sample_dtof_os08a20'")
        time.sleep(3)

    # 4. Verify GS1860 still on I2C after binary exit
    print("\n=== GS1860 on I2C4 after kill ===")
    out = run(board, "i2cdetect -r -y 4 2>/dev/null", timeout=10)
    print(out.strip()[:500])

    # 5. Start binary fresh
    print("\n=== Starting binary fresh ===")
    out = run(board, "cd /opt/sample/dtof && "
                     "(sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 2>&1) > /tmp/dtof.log 2>&1 & "
                     "echo PID=$!")
    print(out.strip())

    # 6. Wait for initialization
    print("\nWaiting 20 sec for startup...")
    time.sleep(20)

    # 7. Check log
    print("\n=== Log (first 30 lines) ===")
    out = run(board, "head -30 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:4000])

    # 8. Check tail
    print("\n=== Log tail ===")
    out = run(board, "tail -10 /tmp/dtof.log 2>/dev/null")
    print(out.strip()[:1000])

    # 9. Count frame errors vs success
    print("\n=== Error counts ===")
    out = run(board, "grep -c 'I2C_WRITE error' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"I2C errors: {out.strip()}")
    out = run(board, "grep -c 'frame err' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"Frame errors: {out.strip()}")
    out = run(board, "grep -c 'init success\\|DtofInit\\|UdpSend' /tmp/dtof.log 2>/dev/null || echo 0")
    print(f"Success messages: {out.strip()}")

    # 10. Check vi pipe status
    print("\n=== VI status ===")
    out = run(board, "cat /proc/msp/vi 2>/dev/null | head -20 || echo 'no vi proc'")
    print(out.strip()[:1000])

    board.close()

if __name__ == "__main__":
    main()
