#!/usr/bin/env python3
"""Wait for board to come back after reboot and check dtof.log."""
import paramiko, time, sys

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=10)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

# Wait for board to come back
print("Waiting for board to come back after reboot...")
for attempt in range(30):
    try:
        c = connect()
        print(f"Connected on attempt {attempt+1}")
        break
    except Exception as e:
        print(f"  Attempt {attempt+1}: {e}")
        time.sleep(5)
else:
    print("Could not connect after 30 attempts!")
    sys.exit(1)

# Initial check
print("\n=== Process check ===")
print(run(c, "ps | grep sample_dtof | grep -v grep || echo not_running_yet").strip())

print("\n=== GPIO96 state ===")
print(run(c, "cat /sys/class/gpio/gpio96/value /sys/class/gpio/gpio96/direction 2>/dev/null || echo not_exported_yet").strip())

print("\n=== i2cdetect ===")
print(run(c, "i2cdetect -r -y 4 2>/dev/null", timeout=15)[:400])

# Wait a bit more if binary not running yet (S90autorun takes 15+ seconds)
for wait in range(5):
    ps = run(c, "ps | grep sample_dtof | grep -v grep")
    if "sample_dtof" in ps:
        break
    print(f"\nBinary not yet running, waiting 5s more... ({wait+1}/5)")
    time.sleep(5)

print("\n=== dtof.log (first 80 lines) ===")
log = run(c, "cat /tmp/dtof.log 2>/dev/null | head -80 || echo no_log_yet")
print(log)

print("\n=== dtof.log (last 30 lines) ===")
log_tail = run(c, "cat /tmp/dtof.log 2>/dev/null | tail -30 || echo no_log_yet")
print(log_tail)

print("\n=== Process check (final) ===")
print(run(c, "ps | grep sample_dtof | grep -v grep || echo not_running").strip())

# Count I2C errors in log
log_full = run(c, "cat /tmp/dtof.log 2>/dev/null")
i2c_errors = log_full.count("I2C_WRITE error")
print(f"\n=== I2C_WRITE error count: {i2c_errors} ===")

if i2c_errors == 0:
    print("SUCCESS: No I2C errors!")
elif i2c_errors <= 5:
    print("PARTIAL: Very few I2C errors - likely succeeded")
elif i2c_errors == 92:
    print("FAIL: 92 I2C errors (one full init failure) - but may have recovered")
elif i2c_errors > 92:
    print(f"FAIL: {i2c_errors} I2C errors (multiple failures)")

c.close()

if __name__ == "__main__":
    pass
