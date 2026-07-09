"""Check I2C bus 4 and GS1860 communication."""
import paramiko

HOST_BOARD = '192.168.137.2'; USER_B = 'root'; PASS_B = 'ebaina'

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=15):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode() + err.read().decode()

print("=== I2C devices on board ===")
rc, o = run("ls /dev/i2c*")
print(o)

print("\n=== i2cdetect bus 4 (GS1860 expected ~0x30) ===")
rc, o = run("i2cdetect -y -r 4 2>/dev/null || echo 'i2cdetect failed'", timeout=30)
print(o)

print("\n=== i2cdetect bus 5 (OS08A20 expected ~0x36 or 0x10) ===")
rc, o = run("i2cdetect -y -r 5 2>/dev/null || echo 'i2cdetect failed'", timeout=30)
print(o)

print("\n=== Check gs1860 cmos init file to understand I2C addr ===")
rc, o = run("find /opt -name '*.c' 2>/dev/null | head -5")
print("opt c files:", o.strip())

print("\n=== Check dtof_init.sh ===")
rc, o = run("cat /opt/ko/dtof_init.sh 2>/dev/null || find /opt -name 'dtof_init.sh' 2>/dev/null | head -5")
print(o)

print("\n=== Check other I2C test tools ===")
rc, o = run("ls /opt/sample/mipi_imx347_dtof_only/ 2>/dev/null || ls /opt/sample/ | head -20")
print(o)

print("\n=== gs1860 I2C address ===")
rc, o = run("grep -r 'GS1860_I2C\|GS1860.*addr\|i2c.*addr\|0x34\|0x36\|0x30' /opt/ko/ 2>/dev/null | head -10")
print(o or "(not found in /opt/ko)")

# Check sensor_i2c kernel module for registered devices
print("\n=== sensor_i2c module info ===")
rc, o = run("cat /proc/umap/sensor_i2c 2>/dev/null | head -30")
print(o or "(no sensor_i2c proc)")

b.close()
