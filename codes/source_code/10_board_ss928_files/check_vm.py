"""Check VM state: gcc version, Makefile, build dir."""
import paramiko

HOST_VM = '192.168.247.129'
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST_VM, username='ebaina', password='ebaina', timeout=10)

def run(cmd, timeout=15):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

BUILD = '/home/ebaina/os08a20_dtof_build'

# GCC version
rc, o, _ = run("aarch64-linux-gnu-gcc --version")
print("GCC:", o.strip())

# Current Makefile
rc, o, _ = run(f"cat -A {BUILD}/Makefile | head -60")
print("\nMakefile (cat -A shows tabs as ^I):")
print(o)

# Previous binary
rc, o, _ = run(f"ls -lh {BUILD}/sample_os08a20_dtof 2>/dev/null || echo 'not found'")
print("Binary:", o.strip())

# Try rebuilding with old Makefile (without -static) to see if it still works
rc, o, _ = run(f"ls {BUILD}/Makefile.cross 2>/dev/null || echo 'no Makefile.cross'")
print("Makefile.cross:", o.strip())

c.close()
