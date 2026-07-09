"""Restore working Makefile on VM and get full build output."""
import paramiko, stat

HOST_VM = '192.168.247.129'
BUILD = '/home/ebaina/os08a20_dtof_build'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST_VM, username='ebaina', password='ebaina', timeout=10)

def run(cmd, timeout=120):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

sftp = c.open_sftp()

# Upload local Makefile.cross as Makefile on VM
with open(r'D:\parking_board_agent\board_files\os08a20_dtof\Makefile.cross', 'rb') as f:
    sftp.putfo(f, f'{BUILD}/Makefile')
sftp.chmod(f'{BUILD}/Makefile', stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
print("Uploaded Makefile (no -static)")

# Clean and build, capture FULL output
print("\n=== Building ===")
rc, o, e = run(f"cd {BUILD} && make clean && make 2>&1")
combined = o + e
print(combined)  # full output, no truncation
print(f"\nrc={rc}")

if rc == 0:
    # Check GLIBC deps of the resulting binary
    rc2, o2, _ = run(f"strings {BUILD}/sample_os08a20_dtof | grep GLIBC_ | sort -u")
    print("\nGLIBC dependencies:")
    print(o2.strip())

sftp.close()
c.close()
