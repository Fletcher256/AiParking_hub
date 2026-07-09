"""Check board glibc version and existing binary requirements."""
import paramiko

HOST_BOARD = '192.168.137.2'

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username='root', password='ebaina',
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Board glibc version
rc, o, _ = run("ldd --version 2>&1 | head -3")
print("Board glibc version:")
print(o.strip())

# What GLIBC versions the working sample_dtof requires
rc, o, _ = run("strings /opt/sample/mipi_rgb_dtof_demo/sample_dtof 2>/dev/null | grep 'GLIBC_' | sort -u")
print("\nWorking sample_dtof GLIBC requirements:")
print(o.strip() or "(not found, trying objdump)")

rc, o, _ = run("objdump -p /opt/sample/mipi_rgb_dtof_demo/sample_dtof 2>/dev/null | grep GLIBC")
print(o.strip())

# What our new binary requires
rc, o, _ = run("strings /opt/sample/mipi_rgb_dtof_demo/sample_os08a20_dtof | grep 'GLIBC_' | sort -u")
print("\nOur sample_os08a20_dtof GLIBC requirements:")
print(o.strip())

# libc on board
rc, o, _ = run("strings /lib64/libc.so.6 | grep 'GLIBC_2\.' | sort -V | tail -5")
print("\nBoard libc provides up to:")
print(o.strip())

b.close()
